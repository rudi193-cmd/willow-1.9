"""
events/stop.py — Stop hook: per-turn cleanup + session composite writer.
Depth stack and thread file cleanup. Session composite written to hanuman/sessions/store.
Heavy pipeline (handoff writing) lives in events/shutdown.py — run via /shutdown skill.
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

from willow.fylgja._state import get_trust_state, save_trust_state

try:
    from willow.fylgja._mcp import call
except Exception:
    call = None  # type: ignore[assignment]

try:
    from core.yggdrasil import ask_structured as _ygg_structured
except Exception:
    def _ygg_structured(prompt: str, timeout: int = 30) -> dict:  # type: ignore
        return {"summary": None, "importance": 0}

DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")
THREAD_FILE = Path("/tmp/willow-context-thread.json")
_AGENT = "hanuman"


def read_turns_since(cursor: str, turns_file: Path) -> list[str]:
    """Return lines from turns_file whose timestamp is after cursor."""
    if not turns_file.exists():
        return []
    lines = []
    try:
        for line in turns_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("[") and "]" in line:
                ts = line[1:line.index("]")]
                if ts > cursor:
                    lines.append(line)
    except Exception:
        pass
    return lines


def _compute_affect(session_id: str) -> str:
    """Derive affect from trace atoms. No LLM — pattern matching only."""
    if call is None:
        return "neutral"
    try:
        traces = call("store_list", {
            "app_id": _AGENT,
            "collection": "hanuman/turns/store",
        }, timeout=5) or []
    except Exception:
        return "neutral"

    session_traces = [t for t in traces if t.get("session_id") == session_id]
    if not session_traces:
        return "neutral"

    pairs = Counter((t.get("tool", ""), t.get("target", "")) for t in session_traces)
    repeated = sum(1 for count in pairs.values() if count > 1)
    return "friction" if repeated >= 1 else "clean"


def _write_failure_atom(session_id: str, traces: list) -> None:
    """Write failure atom to hanuman/atoms/store. Only called for friction sessions."""
    if call is None:
        return
    pairs = Counter((t.get("tool", ""), t.get("target", "")) for t in traces)
    primary_target = pairs.most_common(1)[0][0][1] if pairs else "unknown"
    n_retries = sum(c - 1 for c in pairs.values() if c > 1)

    try:
        call("store_put", {
            "app_id": _AGENT,
            "collection": "hanuman/atoms/store",
            "record": {
                "id": f"failure-{session_id[:8]}",
                "type": "failure",
                "source": "failure",
                "session_id": session_id,
                "target": primary_target,
                "summary": (
                    f"Session had friction on {primary_target}. "
                    f"{n_retries} repeated tool+target pair(s) detected."
                ),
                "affect": "friction",
                "resolved": False,
                "valid_at": datetime.now(timezone.utc).isoformat(),
                "invalid_at": None,
            },
        }, timeout=4)
    except Exception:
        pass


def _write_reflection_atom(session_id: str, affect: str, traces: list) -> None:
    """Write reflection atom (yggdrasil for friction) or pending flag (clean/neutral)."""
    if call is None:
        return

    if affect == "friction":
        trace_lines = "\n".join(
            f"- {t.get('tool', '?')} on {t.get('target', '?')}: {t.get('summary', '')}"
            for t in traces[:10]
        )
        prompt = (
            f"Session {session_id[:8]} trace atoms:\n{trace_lines}\n\n"
            "Write one sentence: what does the next instance need to know "
            "that isn't in these raw traces?\n"
            "Format exactly: SUMMARY: <sentence> | IMPORTANCE: <1-10>"
        )
        result = _ygg_structured(prompt, timeout=4)
        if result["summary"]:
            next_review = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
            try:
                call("store_put", {
                    "app_id": _AGENT,
                    "collection": "hanuman/atoms/store",
                    "record": {
                        "id": f"reflection-{session_id[:8]}",
                        "type": "reflection",
                        "source": "reflection",
                        "session_id": session_id,
                        "summary": result["summary"],
                        "importance": result["importance"],
                        "affect": affect,
                        "next_review": next_review,
                        "review_interval_days": 2,
                        "stability": 1.0,
                        "valid_at": datetime.now(timezone.utc).isoformat(),
                        "invalid_at": None,
                        "superseded_by": None,
                    },
                }, timeout=4)
                return
            except Exception:
                pass

    # Fallback: write pending flag for norn_pass
    try:
        call("store_put", {
            "app_id": _AGENT,
            "collection": "hanuman/atoms/store",
            "record": {
                "id": f"reflection-pending-{session_id[:8]}",
                "type": "reflection_pending",
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }, timeout=3)
    except Exception:
        pass


def mark_session_clean(turn_count: int = 0) -> None:
    if turn_count == 0:
        return
    state = get_trust_state()
    if not state:
        return
    state["clean_session_count"] = state.get("clean_session_count", 0) + 1
    save_trust_state(state)


def _write_session_composite(session_id: str) -> None:
    """Write session composite atom. Fast — no LLM, pure store_put.
    next_bite is populated later by the /handoff skill via store_update.
    """
    if call is None:
        return
    try:
        sid = (session_id or "unknown")[:8]
        record = {
            "id": f"session-{sid}",
            "session_id": session_id or "unknown",
            "date": datetime.now(timezone.utc).isoformat(),
            "turn_count": 0,
            "tools_fired": [],
            "next_bite": "",
            "type": "session",
        }
        call("store_put", {
            "app_id": _AGENT,
            "collection": "hanuman/sessions/store",
            "record": record,
        }, timeout=4)
    except Exception:
        pass


def main():
    try:
        data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "")

    # Cleanup depth stack
    try:
        depth = int(DEPTH_FILE.read_text().strip()) if DEPTH_FILE.exists() else 0
        if depth > 1:
            DEPTH_FILE.write_text(str(depth - 1))
        else:
            DEPTH_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    # Cleanup context thread
    try:
        THREAD_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    # Write session composite
    _write_session_composite(session_id)

    # Affect tagging + failure atom
    affect = "neutral"
    session_traces: list = []
    try:
        affect = _compute_affect(session_id)
        if affect == "friction" and call is not None:
            try:
                all_traces = call("store_list", {
                    "app_id": _AGENT,
                    "collection": "hanuman/turns/store",
                }, timeout=5) or []
                session_traces = [t for t in all_traces if t.get("session_id") == session_id]
            except Exception:
                session_traces = []
            _write_failure_atom(session_id, session_traces)
    except Exception:
        pass

    # Reflection atom (affect-gated)
    try:
        _write_reflection_atom(session_id, affect, session_traces)
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
