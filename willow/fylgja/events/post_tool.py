"""
events/post_tool.py — PostToolUse hook handler.
ToolSearch completion directive + mid-session trace atom writer.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from willow.fylgja._mcp import call
except Exception:
    call = None  # type: ignore[assignment]

_RATE_FILE = Path("/tmp/willow-post-tool-rate.json")
_RATE_WINDOW = 60  # seconds

_SIGNIFICANT = {
    "Edit", "Write",
    "store_put", "store_update",
    "mcp__willow__store_add_edge",
    "mcp__willow__willow_knowledge_ingest",
    "mcp__willow__willow_knowledge_at",
}

_AGENT = "hanuman"


def _target_from_input(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("Edit", "Write"):
        return tool_input.get("file_path", "")[:120]
    if tool_name in ("store_put", "store_update"):
        return tool_input.get("collection", "")[:80]
    if tool_name == "mcp__willow__store_add_edge":
        return f"{tool_input.get('from_id','')}→{tool_input.get('to_id','')}"
    if tool_name == "mcp__willow__willow_knowledge_ingest":
        return tool_input.get("title", "")[:80]
    return ""


def _summary_from(tool_name: str, target: str) -> str:
    verbs = {
        "Edit": "edited",
        "Write": "wrote",
        "store_put": "stored atom in",
        "store_update": "updated atom in",
        "mcp__willow__store_add_edge": "added edge",
        "mcp__willow__willow_knowledge_ingest": "ingested KB atom",
        "mcp__willow__willow_knowledge_at": "replayed KB at",
    }
    verb = verbs.get(tool_name, tool_name)
    return f"{verb} {target}".strip()


def _rate_key(tool_name: str, target: str) -> str:
    return f"{tool_name}::{target}"


def _is_rate_limited(key: str) -> bool:
    try:
        if not _RATE_FILE.exists():
            return False
        data = json.loads(_RATE_FILE.read_text())
        last = data.get(key, 0)
        return (time.time() - last) < _RATE_WINDOW
    except Exception:
        return False


def _record_rate(key: str) -> None:
    try:
        data = {}
        if _RATE_FILE.exists():
            try:
                data = json.loads(_RATE_FILE.read_text())
            except Exception:
                pass
        data[key] = time.time()
        now = time.time()
        data = {k: v for k, v in data.items() if now - v < _RATE_WINDOW * 2}
        _RATE_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _write_trace(session_id: str, tool_name: str, tool_input: dict) -> None:
    try:
        target = _target_from_input(tool_name, tool_input)
        key = _rate_key(tool_name, target)
        if _is_rate_limited(key):
            return
        now_ms = int(time.time() * 1000)
        sid = (session_id or "unknown")[:8]
        record = {
            "id": f"turn-{sid}-{now_ms}",
            "session_id": session_id or "unknown",
            "tool": tool_name,
            "target": target,
            "summary": _summary_from(tool_name, target),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "trace",
        }
        call("store_put", {
            "app_id": _AGENT,
            "collection": "hanuman/turns/store",
            "record": record,
        }, timeout=3)
        _record_rate(key)
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        session_id = data.get("session_id", "")
    except Exception:
        tool_name = ""
        tool_input = {}
        session_id = ""

    if tool_name == "ToolSearch":
        print("[TOOL-SEARCH-COMPLETE] Schema loaded. Call the fetched tool NOW "
              "in this same response. Do NOT say 'Tool loaded.' "
              "Do NOT end your turn. Invoke the tool immediately.")

    if tool_name in _SIGNIFICANT:
        _write_trace(session_id, tool_name, tool_input)

    sys.exit(0)


if __name__ == "__main__":
    main()
