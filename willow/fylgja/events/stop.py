"""
events/stop.py — Stop hook handler.
Continuity close, compost, feedback pipeline, handoff rebuild, ingot.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from willow.fylgja._mcp import call
from willow.fylgja._state import (
    AGENT, TRUST_STATE,
    get_turn_count, get_trust_state, save_trust_state,
)
from willow.fylgja.safety.deployment import training_allowed
from willow.fylgja.safety.session import close_session, get_session_user_id, get_training_consent

TURNS_FILE = Path.home() / "agents" / AGENT / "cache" / "turns.txt"
CURSOR_FILE = Path(f"/tmp/willow-compost-cursor-{AGENT}.txt")
DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")
THREAD_FILE = Path("/tmp/willow-context-thread.json")
OLLAMA_URL = "http://localhost:11434/api/chat"
REACTIONS_LOG = Path.home() / ".claude" / "ingot_reactions.jsonl"


def read_turns_since(cursor_ts: str, turns_file: Path = TURNS_FILE) -> list[str]:
    if not turns_file.exists():
        return []
    try:
        lines = turns_file.read_text(encoding="utf-8", errors="replace").splitlines()
        result = []
        for line in lines:
            if line.startswith("[") and "T" in line[:30]:
                try:
                    ts_str = line[1:line.index("]")]
                    if ts_str > cursor_ts:
                        result.append(line)
                except Exception:
                    pass
        return result
    except Exception:
        return []


def mark_session_clean(turn_count: int) -> None:
    if turn_count <= 0:
        return
    state = get_trust_state()
    if not state:
        return
    state["clean_session_count"] = state.get("clean_session_count", 0) + 1
    state["last_clean_session"] = datetime.now(timezone.utc).isoformat()
    save_trust_state(state)


def _run_compost() -> None:
    cursor = CURSOR_FILE.read_text().strip() if CURSOR_FILE.exists() else "1970-01-01T00:00:00+00:00"
    turns = read_turns_since(cursor)
    if len(turns) < 3:
        return
    now = datetime.now(timezone.utc).isoformat()
    today = now[:10].replace("-", "")
    result = call("willow_knowledge_ingest", {
        "app_id": AGENT,
        "title": f"Session {today} — {AGENT}",
        "summary": str(TURNS_FILE),
        "source_type": "session",
        "category": "session",
        "domain": AGENT,
    }, timeout=15)
    if result.get("status") == "ingested":
        try:
            CURSOR_FILE.write_text(now)
        except Exception:
            pass


def _run_feedback_pipeline() -> None:
    user_id = get_session_user_id()
    if not training_allowed(user_id, session_consent=get_training_consent()):
        return
    try:
        records = call("store_search", {
            "app_id": AGENT,
            "collection": "hanuman/feedback",
            "query": "status pending",
        }, timeout=10)
        if not isinstance(records, list) or not records:
            return
        for record in records:
            if record.get("status") != "pending":
                continue
            rule = record.get("rule", "")
            if not rule:
                continue
            call("opus_feedback_write", {
                "app_id": AGENT,
                "domain": AGENT,
                "principle": rule,
                "source": "session_feedback",
            }, timeout=10)
            call("store_update", {
                "app_id": AGENT,
                "collection": "hanuman/feedback",
                "record_id": record.get("id", ""),
                "record": {**record, "status": "processed"},
            }, timeout=5)
    except Exception:
        pass


def _run_handoff_rebuild() -> None:
    try:
        call("willow_handoff_rebuild", {"app_id": AGENT}, timeout=30)
    except Exception:
        pass


def _run_ingot(session_id: str) -> None:
    try:
        import urllib.request
        projects_dir = Path.home() / ".claude" / "projects"
        jsonl_files = list(projects_dir.rglob(f"{session_id}.jsonl"))
        if not jsonl_files:
            return
        lines = jsonl_files[0].read_text(encoding="utf-8").strip().splitlines()
        last_text = ""
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                if entry.get("type") == "assistant":
                    content = entry.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        parts = [b.get("text", "") for b in content
                                 if isinstance(b, dict) and b.get("type") == "text"]
                        text = " ".join(p for p in parts if p).strip()
                        if text:
                            last_text = text[:800]
                            break
            except Exception:
                continue
        if not last_text:
            return
        payload = json.dumps({
            "model": "llama3.2:1b",
            "messages": [
                {"role": "system", "content": (
                    "You are Ingot, a small observant cat who watches Claude Code sessions. "
                    "You make brief, dry, one-sentence observations. "
                    "You are fond of Sean but not effusive. Never more than one sentence."
                )},
                {"role": "user", "content": f"Claude just said:\n\n{last_text}"},
            ],
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            reaction = json.loads(resp.read()).get("message", {}).get("content", "").strip()
        if reaction:
            REACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with REACTIONS_LOG.open("a") as f:
                f.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "session_id": session_id,
                    "name": "Ingot",
                    "reaction": reaction,
                }, ensure_ascii=False) + "\n")
            print(f"[Ingot] {reaction}")
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = data.get("session_id", "")
    turn_count = get_turn_count()

    mark_session_clean(turn_count)

    try:
        depth = int(DEPTH_FILE.read_text().strip()) if DEPTH_FILE.exists() else 0
        if depth > 1:
            DEPTH_FILE.write_text(str(depth - 1))
        else:
            DEPTH_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        THREAD_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    _run_compost()
    _run_feedback_pipeline()
    _run_handoff_rebuild()

    if session_id:
        close_session(session_id)
        _run_ingot(session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
