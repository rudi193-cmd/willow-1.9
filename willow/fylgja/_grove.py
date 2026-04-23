"""
_grove.py — Grove MCP subprocess client.
Mirror of _mcp.py but routes to grove-mcp binary.
b17: B2DA2  ΔΣ=42
"""
import json
import os
import subprocess
from pathlib import Path

_GROVE_MCP = Path(os.environ.get(
    "GROVE_MCP_BIN",
    str(Path.home() / ".local" / "bin" / "grove-mcp")
))


def call(tool_name: str, arguments: dict, timeout: int = 10) -> dict:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    })
    try:
        result = subprocess.run(
            [str(_GROVE_MCP)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return {"error": "subprocess_error", "stderr": result.stderr[:200], "tool": tool_name}
        data = json.loads(result.stdout)
        return data.get("result", data)
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "tool": tool_name}
    except Exception as e:
        return {"error": str(e), "tool": tool_name}
