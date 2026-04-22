"""
events/pre_tool.py — PreToolUse hook handler.
MCP guard (Bash + Agent), KB-first read advisory, WWSDN neighborhood scan.
Safety hard stop gate (stub — wired when safety subsystem is built in Plan 2).
"""
import json
import os
import re
import sys
from pathlib import Path

from willow.fylgja._mcp import call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
MAX_DEPTH = int(os.environ.get("WILLOW_AGENT_MAX_DEPTH", "3"))
DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")

BASH_BLOCKS = [
    (r"\bpsql\b|\bpg_dump\b|\bpg_restore\b",
     "Direct Postgres access is not allowed. Use MCP: store_get / store_list for store reads, "
     "willow_knowledge_search for KB reads, store_put / willow_knowledge_ingest for writes."),
    (r"\bsqlite3\b",
     "Direct SQLite access is not allowed. Use MCP: store_get / store_list, or Glob + Read for schema inspection."),
    (r"\bcat\s+[\w/~\.\"]",
     "File read → use the Read tool."),
    (r"(?:^|[;&])\s*grep\s+|(?:^|[;&])\s*rg\s+",
     "Content search → use the Grep tool."),
    (r"\bfind\s+[\w/~\.\"]",
     "File search → use the Glob tool."),
    (r"^\s*ls\s*$|\bls\s+[\w/~\.\"]",
     "File listing / discovery → use the Glob tool."),
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


def _mcp_store_search(collection: str, query: str) -> list:
    result = call("store_search", {"app_id": AGENT, "collection": collection, "query": query}, timeout=3)
    if isinstance(result, list):
        return result
    return []


def check_kb_first(file_path: str) -> str | None:
    try:
        filename = Path(file_path).name
        records = _mcp_store_search("hanuman/file-index", filename)
        if records:
            r = records[0]
            return (
                f"[KB-FIRST] Store record exists for this file.\n"
                f"  id: {r.get('id','?')}  type: {r.get('type','?')}\n"
                f"  title: {r.get('title','?')}\n"
                f"  collection: {r.get('collection','?')}\n"
                f"  Check the store record before reading the full file."
            )
    except Exception:
        pass
    return None


def check_f5_canon(tool_name: str, tool_input: dict) -> str | None:
    field = F5_PROSE_TOOLS.get(tool_name)
    if not field:
        return None
    content = tool_input.get(field, "")
    if not isinstance(content, str) or not content.strip():
        return None
    c = content.strip()
    if c.startswith("/") and len(c) < 300 and "\n" not in c:
        return None
    if len(c) > 150 or c.count("\n") > 2 or c.count(". ") > 1:
        preview = c[:80].replace("\n", " ")
        return (
            f"\n[WWSDN/F5] ⚠  CANON DRIFT — content is prose, not a file path\n"
            f"[WWSDN/F5]    tool: {tool_name}  field: {field}\n"
            f"[WWSDN/F5]    content ({len(c)} chars): \"{preview}...\"\n"
            f"[WWSDN/F5]    fix: write content to a file, store the path instead\n"
        )
    return None


def _run_wwsdn(tool_name: str, tool_input: dict) -> None:
    f5 = check_f5_canon(tool_name, tool_input)
    if f5:
        print(json.dumps({"decision": "block", "reason": f5}))
        sys.exit(0)
    signal = " ".join(
        v[:100] for v in tool_input.values()
        if isinstance(v, str) and len(v) > 3
    )[:200]
    if not signal:
        return
    try:
        results = call("willow_knowledge_search", {
            "app_id": AGENT, "query": signal, "limit": 3
        }, timeout=5)
        knowledge = results.get("knowledge", []) if isinstance(results, dict) else []
        if knowledge:
            lines = [f"[WWSDN] {tool_name} — neighborhood", f"[WWSDN] Signal: {signal[:80]}"]
            for k in knowledge[:3]:
                lines.append(f"  {k.get('title','?')} [{k.get('source_type','?')}]")
            print("\n".join(lines))
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

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

    # Read tool — KB-first advisory
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        advisory = check_kb_first(file_path) if file_path else None
        if advisory:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": advisory,
                }
            }))
        sys.exit(0)

    # Write tools — WWSDN
    if tool_name in F5_PROSE_TOOLS:
        _run_wwsdn(tool_name, tool_input)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
