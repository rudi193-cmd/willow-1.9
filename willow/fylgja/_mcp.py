"""
_mcp.py — Willow MCP direct client.
b17: FYGJ1  ΔΣ=42

Dispatches hook→MCP calls directly to Python implementations.
No subprocess. No stale binary. No init handshake. No auth gap.

Tool groups:
  store_*                → core.willow_store.WillowStore
  grove_*                → core.grove_client
  willow_knowledge_*     → core.pg_bridge + core.embedder
  willow_handoff_*       → sap.sap_mcp (via subprocess fallback)
  everything else        → subprocess fallback (willow-mcp binary)
"""
import json
import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent  # willow-1.9/
_WILLOW_MCP = Path(os.environ.get(
    "WILLOW_MCP_BIN",
    str(Path.home() / ".local" / "bin" / "willow-mcp")
))

# ---------------------------------------------------------------------------
# Direct store dispatch
# ---------------------------------------------------------------------------

_store = None


def _get_store():
    global _store
    if _store is None:
        import sys
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from core.willow_store import WillowStore
        _store = WillowStore()
    return _store


def _dispatch_store(tool_name: str, arguments: dict):
    store = _get_store()
    col = arguments.get("collection", "")

    if tool_name == "store_put":
        record = arguments.get("record", {})
        record_id = arguments.get("record_id") or record.get("id")
        result = store.put(col, record, record_id=record_id)
        if isinstance(result, tuple):
            rid, action = result[0], result[1]
            return {"id": rid, "action": action}
        return {"id": record_id or "", "action": "written"}

    if tool_name == "store_get":
        record_id = arguments.get("record_id") or arguments.get("id", "")
        result = store.get(col, record_id)
        return result if result is not None else {"error": "not_found"}

    if tool_name == "store_list":
        return store.all(col) or []

    if tool_name == "store_search":
        query = arguments.get("query", "")
        after = arguments.get("after")
        return store.search(col, query, after=after) or []

    if tool_name == "store_search_all":
        return store.search_all(arguments.get("query", "")) or []

    if tool_name == "store_delete":
        record_id = arguments.get("record_id", "")
        return store.delete(col, record_id)

    if tool_name == "store_update":
        record_id = arguments.get("record_id", "")
        record = arguments.get("record", {})
        result = store.update(col, record_id, record)
        if isinstance(result, tuple):
            return {"id": result[0], "action": result[1]}
        return {"id": record_id, "action": "updated"}

    if tool_name == "store_add_edge":
        return store.add_edge(
            arguments.get("from_collection", ""),
            arguments.get("from_id", ""),
            arguments.get("to_collection", ""),
            arguments.get("to_id", ""),
            arguments.get("label", ""),
        )

    if tool_name == "store_edges_for":
        return store.edges_for(col, arguments.get("record_id", "")) or []

    if tool_name == "store_stats":
        return store.stats() or {}

    if tool_name == "store_audit":
        return store.audit() or {}

    return {"error": f"unknown store tool: {tool_name}"}


# ---------------------------------------------------------------------------
# Direct grove dispatch — raw psycopg2 to grove.* schema
# ---------------------------------------------------------------------------

def _grove_connect():
    import psycopg2
    db = os.environ.get("WILLOW_PG_DB", "willow_19")
    user = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", ""))
    conn = psycopg2.connect(dbname=db, user=user)
    conn.autocommit = True
    return conn


def _dispatch_grove(tool_name: str, arguments: dict):
    try:
        conn = _grove_connect()
        cur = conn.cursor()

        if tool_name == "grove_send_message":
            channel = arguments.get("channel_name", arguments.get("channel", ""))
            cur.execute("SELECT id FROM grove.channels WHERE name=%s LIMIT 1", (channel,))
            row = cur.fetchone()
            if not row:
                return {"error": f"channel not found: {channel}"}
            cur.execute(
                "INSERT INTO grove.messages (channel_id, sender, content) VALUES (%s, %s, %s) RETURNING id",
                (row[0], arguments.get("sender", ""), arguments.get("content", "")),
            )
            msg_id = cur.fetchone()[0]
            conn.close()
            return {"id": msg_id, "ok": True}

        if tool_name == "grove_reply":
            cur.execute("SELECT channel_id FROM grove.messages WHERE id=%s LIMIT 1",
                        (arguments.get("parent_id", 0),))
            row = cur.fetchone()
            if not row:
                return {"error": "parent message not found"}
            cur.execute(
                "INSERT INTO grove.messages (channel_id, sender, content, parent_id) VALUES (%s, %s, %s, %s) RETURNING id",
                (row[0], arguments.get("sender", ""), arguments.get("content", ""), arguments.get("parent_id")),
            )
            msg_id = cur.fetchone()[0]
            conn.close()
            return {"id": msg_id, "ok": True}

        if tool_name == "grove_get_history":
            channel = arguments.get("channel_name", arguments.get("channel", ""))
            cur.execute("SELECT id FROM grove.channels WHERE name=%s LIMIT 1", (channel,))
            row = cur.fetchone()
            if not row:
                return {"result": []}
            since_id = arguments.get("since_id", 0)
            limit = min(arguments.get("limit", 50), 200)
            cur.execute(
                "SELECT id, sender, content, created_at FROM grove.messages "
                "WHERE channel_id=%s AND id>%s AND is_deleted=0 ORDER BY id ASC LIMIT %s",
                (row[0], since_id, limit),
            )
            rows = cur.fetchall()
            conn.close()
            return {"result": [{"id": r[0], "sender": r[1], "content": r[2],
                                 "created_at": str(r[3])} for r in rows]}

        if tool_name == "grove_heartbeat":
            cur.execute("SELECT id FROM grove.channels WHERE name='heartbeat' LIMIT 1")
            row = cur.fetchone()
            if row:
                cur.execute(
                    "INSERT INTO grove.messages (channel_id, sender, content) VALUES (%s, %s, %s)",
                    (row[0], arguments.get("sender", ""), "♥"),
                )
            conn.close()
            return {"ok": True}

        conn.close()
    except Exception as e:
        return {"error": f"grove dispatch error: {e}"}
    return {"error": f"unknown grove tool: {tool_name}"}


# ---------------------------------------------------------------------------
# Subprocess fallback (for tools not covered by direct dispatch)
# Sends proper MCP initialize handshake.
# ---------------------------------------------------------------------------

def _subprocess_call(tool_name: str, arguments: dict, timeout: int) -> dict:
    init_msg = json.dumps({
        "jsonrpc": "2.0", "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "willow-hook", "version": "1"},
        },
    })
    tool_msg = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })
    payload = init_msg + "\n" + tool_msg + "\n"

    env = os.environ.copy()
    # Ensure auth-critical vars reach the subprocess
    env.setdefault("WILLOW_SAFE_ROOT", str(Path.home() / "SAFE" / "Applications"))
    env.setdefault("WILLOW_PG_DB", "willow_19")
    env.setdefault("WILLOW_PG_USER", os.environ.get("USER", ""))

    try:
        result = subprocess.run(
            [str(_WILLOW_MCP)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            return {"error": "subprocess_error", "stderr": result.stderr[:200], "tool": tool_name}
        # stdout has two JSON lines — init response then tool response
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        for line in reversed(lines):
            try:
                data = json.loads(line)
                if data.get("id") == 1:
                    inner = data.get("result", data)
                    # Unwrap MCP content envelope if present
                    if isinstance(inner, dict) and "content" in inner:
                        for block in inner["content"]:
                            if block.get("type") == "text":
                                try:
                                    return json.loads(block["text"])
                                except Exception:
                                    return {"text": block["text"]}
                    return inner
            except Exception:
                continue
        return {"error": "no_tool_response", "tool": tool_name}
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "tool": tool_name}
    except Exception as e:
        return {"error": str(e), "tool": tool_name}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def call(tool_name: str, arguments: dict, timeout: int = 10) -> dict:
    """Dispatch a tool call. Direct path for store/grove; subprocess fallback for all else."""
    if tool_name.startswith("store_"):
        try:
            return _dispatch_store(tool_name, arguments)
        except Exception as e:
            return {"error": f"store dispatch error: {e}", "tool": tool_name}

    if tool_name.startswith("grove_"):
        try:
            return _dispatch_grove(tool_name, arguments)
        except Exception as e:
            return {"error": f"grove dispatch error: {e}", "tool": tool_name}

    return _subprocess_call(tool_name, timeout=timeout, arguments=arguments)
