"""
events/stop.py — Stop hook: per-turn cleanup + session composite writer.
Depth stack and thread file cleanup. Session composite written to hanuman/sessions/store.
Heavy pipeline (handoff writing) lives in events/shutdown.py — run via /shutdown skill.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from willow.fylgja._state import get_trust_state, save_trust_state

try:
    from willow.fylgja._mcp import call
except Exception:
    call = None  # type: ignore[assignment]

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


def mark_session_clean(turn_count: int = 0) -> None:
    if turn_count == 0:
        return
    state = get_trust_state()
    if not state:
        return
    state["clean_session_count"] = state.get("clean_session_count", 0) + 1
    save_trust_state(state)


def _write_session_composite(session_id: str) -> None:
    """Write session composite atom. Fast — no LLM, pure store_put."""
    if call is None:
        return
    try:
        sid = (session_id or "unknown")[:8]
        record = {
            "id": f"session-{sid}",
            "session_id": session_id or "unknown",
            "date": datetime.now(timezone.utc).isoformat(),
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

    sys.exit(0)


if __name__ == "__main__":
    main()
