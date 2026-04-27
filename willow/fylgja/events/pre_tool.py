"""
events/pre_tool.py — PreToolUse hook handler.
Safety gate → MCP guard (Bash + Agent) → F5 canon guard (write tools).
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from willow.fylgja._mcp import call
from willow.fylgja.safety.platform import check_all as _safety_check_all
from willow.fylgja.safety.session import get_session_user_id, get_session_role, get_training_consent

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
MAX_DEPTH = int(os.environ.get("WILLOW_AGENT_MAX_DEPTH", "3"))
DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")

BASH_BLOCKS = [
    (r"\bsqlite3\b",
     "Direct SQLite access is not allowed. Use MCP: store_get / store_list, or Read for schema inspection."),
    (r"^\s*psql\s",
     "Direct psql access is not allowed. Use MCP: willow_query or pg_bridge via Python. "
     "Schema inspection: Read pg_bridge.py or use store_list."),
    (r"^\s*(cat|head|tail)\s",
     "Use the Read tool instead of cat/head/tail — it provides line numbers and better context."),
    (r"^\s*ls\s",
     "Use Glob tool for file listings — it supports patterns and integrates with the KB."),
]

F5_PROSE_TOOLS = {
    "mcp__willow__store_put": "record",
    "mcp__willow__store_update": "record",
    "mcp__willow__willow_knowledge_ingest": "content",
}


def check_bash_block(command: str) -> str | None:
    for pattern, reason in BASH_BLOCKS:
        if re.search(pattern, command, re.MULTILINE):
            return reason
    return None


def check_agent_block(subagent_type: str) -> str | None:
    if subagent_type == "Explore":
        return ("Explore subagent is blocked. Use MCP: store_search, willow_knowledge_search, "
                "store_get, store_list — or Glob/Grep/Read directly.")
    return None


def _mcp_store_search(query: str) -> list:
    try:
        result = call("store_search", {
            "app_id": AGENT,
            "collection": "hanuman/file-index",
            "query": query,
        }, timeout=3)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def check_kb_first(path: str) -> str | None:
    """
    Check if a file path is indexed in the KB file-index.
    Returns a KB-FIRST advisory if found (suggesting reading from KB instead of disk),
    or None if not indexed.
    """
    filename = Path(path).name
    results = _mcp_store_search(filename)
    if not results:
        return None
    hit = results[0]
    return (
        f"[KB-FIRST] '{filename}' is indexed (collection: {hit.get('collection', 'hanuman/file-index')}, "
        f"id: {hit.get('id', '?')}). Consider reading from KB before disk."
    )


def _read_depth() -> int:
    try:
        return int(DEPTH_FILE.read_text().strip()) if DEPTH_FILE.exists() else 0
    except Exception:
        return 0


def _write_depth(n: int) -> None:
    try:
        if n <= 0:
            DEPTH_FILE.unlink(missing_ok=True)
        else:
            DEPTH_FILE.write_text(str(n))
    except Exception:
        pass


_F5_DOC_FIELDS = {"content", "body", "raw_content"}


def _is_prose(s: str) -> bool:
    """True if s looks like a prose document rather than a file path or short value."""
    c = s.strip()
    if c.startswith("/") and len(c) < 300 and "\n" not in c:
        return False
    return len(c) > 150 or c.count("\n") > 2 or c.count(". ") > 1


def check_f5_canon(tool_name: str, tool_input: dict) -> str | None:
    field = F5_PROSE_TOOLS.get(tool_name)
    if not field:
        return None
    content = tool_input.get(field, "")

    # Dict record: only flag if a doc-content field (content/body/raw_content) is prose.
    # Structured metadata fields (description, summary, resolution, etc.) are always allowed.
    if isinstance(content, dict):
        for doc_field in _F5_DOC_FIELDS:
            val = content.get(doc_field, "")
            if isinstance(val, str) and _is_prose(val):
                preview = val[:80].replace("\n", " ")
                return (
                    f"\n[WWSDN/F5] ⚠  CANON DRIFT — record.{doc_field} is prose, not a file path\n"
                    f"[WWSDN/F5]    tool: {tool_name}  field: {field}.{doc_field}\n"
                    f"[WWSDN/F5]    content ({len(val)} chars): \"{preview}...\"\n"
                    f"[WWSDN/F5]    fix: write content to a file, store the path instead\n"
                )
        return None

    # String record (model serialised the dict as JSON): parse and apply same check.
    if not isinstance(content, str) or not content.strip():
        return None
    c = content.strip()
    if c.startswith("{"):
        try:
            import json as _json
            parsed = _json.loads(c)
            if isinstance(parsed, dict):
                return check_f5_canon(tool_name, {field: parsed})
        except Exception:
            pass

    if _is_prose(c):
        preview = c[:80].replace("\n", " ")
        return (
            f"\n[WWSDN/F5] ⚠  CANON DRIFT — content is prose, not a file path\n"
            f"[WWSDN/F5]    tool: {tool_name}  field: {field}\n"
            f"[WWSDN/F5]    content ({len(c)} chars): \"{preview}...\"\n"
            f"[WWSDN/F5]    fix: write content to a file, store the path instead\n"
        )
    return None


def _run_safety_gate(tool_name: str, tool_input: dict, session_id: str) -> str | None:
    """Run platform hard stops. Returns block JSON string or None."""
    try:
        user_id = get_session_user_id()
        user_role = get_session_role(user_id)
        training_consented = get_training_consent()
        result = _safety_check_all(
            tool_name=tool_name,
            tool_input=tool_input,
            user_role=user_role,
            training_consented=training_consented,
        )
        if result:
            try:
                call("store_put", {
                    "app_id": AGENT,
                    "collection": "willow/safety_log",
                    "record": {
                        "id": f"hs-{session_id[:8]}-{abs(hash(tool_name + str(tool_input))) % 99999:05d}",
                        "user_id": user_id,
                        "tool_name": tool_name,
                        "hard_stop_id": result["hard_stop_id"],
                        "reason": result["reason"],
                        "session_id": session_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                }, timeout=3)
            except Exception:
                pass
            return json.dumps({"decision": "block", "reason": result["reason"]})
    except Exception:
        pass
    return None


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    session_id = payload.get("session_id", "")

    # Safety gate — runs before all other checks
    block = _run_safety_gate(tool_name, tool_input, session_id)
    if block:
        print(block)
        sys.exit(0)

    # Agent tool
    subagent_type = tool_input.get("subagent_type", "")
    if subagent_type or tool_name == "Agent":
        reason = check_agent_block(subagent_type) if subagent_type else None
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
            sys.exit(0)
        depth = _read_depth()
        if depth >= MAX_DEPTH:
            print(json.dumps({
                "decision": "block",
                "reason": (f"Agent depth limit reached ({depth}/{MAX_DEPTH}). "
                           f"Complete the work directly or surface to parent session."),
            }))
            sys.exit(0)
        _write_depth(depth + 1)
        sys.exit(0)

    # Bash tool
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        reason = check_bash_block(command) if command else None
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)

    # Write tools — F5 canon guard
    if tool_name in F5_PROSE_TOOLS:
        f5 = check_f5_canon(tool_name, tool_input)
        if f5:
            print(json.dumps({"decision": "block", "reason": f5}))
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
