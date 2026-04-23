"""
SAP Delivery Layer
b17: 7LLE2
ΔΣ=42

Takes assembled context and formats it for injection into a model's context window.
Logs every delivery transaction for audit.

Usage:
    ctx = context.assemble("utety-chat", query="what is the current task")
    prompt_header = deliver.to_string(ctx)
    # or
    deliver.to_window(ctx)   # prints to stdout for Claude Code / pipe injection
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sap.deliver")

LOG_DIR = Path(__file__).parent.parent / "log"


def _log_delivery(app_id: str, atom_count: int, char_count: int) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "app_id": app_id,
        "event": "delivered",
        "atoms": atom_count,
        "chars": char_count,
    }
    log_path = LOG_DIR / "deliveries.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def to_string(ctx: Optional[dict]) -> str:
    """
    Format assembled context as a string suitable for prepending to a system prompt.
    Returns empty string if ctx is None (unauthorized).
    """
    if not ctx:
        return ""

    app_id = ctx.get("app_id", "unknown")
    query = ctx.get("query", "")
    atoms = ctx.get("atoms", [])
    cache = ctx.get("cache")
    manifest = ctx.get("manifest", {})

    lines = [
        f"--- SAP CONTEXT: {app_id} ---",
        f"app: {manifest.get('name', app_id)}",
        f"query: {query}",
        f"permitted_streams: {', '.join(ctx.get('permitted_streams', []))}",
        "",
    ]

    if cache:
        lines.append("[CACHED CONTEXT]")
        lines.append(cache[:2000])
        lines.append("")

    if atoms:
        lines.append("[KB ATOMS]")
        for atom in atoms:
            text = atom.get("_injectable") or str(atom.get("summary", atom.get("content", "")))[:400]
            source = atom.get("source_type", "")
            category = atom.get("category", "")
            lines.append(f"[{category}/{source}] {text}")
        lines.append("")

    lines.append("--- END SAP CONTEXT ---")

    result = "\n".join(lines)
    _log_delivery(app_id, len(atoms), len(result))
    return result


def to_window(ctx: Optional[dict]) -> None:
    """
    Print formatted context to stdout.
    Used for Claude Code / pipe-based injection.
    """
    output = to_string(ctx)
    if output:
        print(output)


def grove_send(channel: str, content: str, sender: str = "hanuman") -> bool:
    """
    Send a message to a Grove channel via the grove MCP server subprocess.
    Returns True on success, False on failure. Never raises.
    """
    import os
    import subprocess
    grove_mcp = os.environ.get(
        "GROVE_MCP_BIN",
        str(Path.home() / ".local" / "bin" / "grove-mcp")
    )
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {
            "name": "grove_send_message",
            "arguments": {"channel_name": channel, "content": content, "sender": sender},
        },
    })
    try:
        result = subprocess.run(
            [grove_mcp], input=payload, capture_output=True, text=True, timeout=8
        )
        return result.returncode == 0
    except Exception:
        return False
