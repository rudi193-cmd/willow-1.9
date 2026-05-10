"""
_grove.py — Grove hook client.
b17: B2DA2  ΔΣ=42

Delegates to _mcp.call() which has direct psycopg2 grove dispatch.
grove-mcp binary does not exist — this was always a dead path.
"""
from willow.fylgja._mcp import call as _mcp_call


def call(tool_name: str, arguments: dict, timeout: int = 10) -> dict:
    return _mcp_call(tool_name, arguments, timeout=timeout)
