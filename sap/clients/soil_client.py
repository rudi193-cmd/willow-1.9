"""
soil_client.py — Sync MCP client for Willow SOIL store operations.
b17: SOIL1  ΔΣ=42

Standalone. Only imports stdlib + mcp package (installed with willow-seed).
No willow-1.9 Python library required at runtime — talks to willow.sh via stdio.

Usage:
    from sap.clients.soil_client import SoilClient

    client = SoilClient(app_id="story-timeline")
    client.put("user-abc/story-timeline/_graph/edges", {"id": "e1", ...}, record_id="e1")
    records = client.list("user-abc/story-timeline/_graph/edges")
    client.delete("user-abc/story-timeline/_graph/edges", "e1")

Server discovery order:
    1. WILLOW_MCP_CMD env var (full command string)
    2. WILLOW_ROOT env var → {WILLOW_ROOT}/willow.sh
    3. ~/.willow-root symlink → willow.sh  (willow-seed install convention)
    4. ~/github/willow-1.9/willow.sh  (dev fallback)
"""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional


def _find_willow_sh() -> Optional[Path]:
    if cmd := os.environ.get("WILLOW_MCP_CMD"):
        return Path(cmd)
    candidates = [
        os.environ.get("WILLOW_ROOT"),
        Path.home() / ".willow-root",
        Path.home() / "github" / "willow-1.9",
    ]
    for c in candidates:
        if c:
            p = Path(c) / "willow.sh"
            if p.exists():
                return p
    return None


class SoilClient:
    """
    Synchronous wrapper around the Willow MCP SOIL store tools.
    Spawns willow.sh once and keeps the session alive for the lifetime
    of the client. Thread-safe: all async work runs in a background loop.
    """

    def __init__(self, app_id: str, willow_sh: Optional[str] = None):
        self._app_id = app_id
        self._available = False
        self._session = None
        self._exit_stack = None

        sh = Path(willow_sh) if willow_sh else _find_willow_sh()
        if not sh or not sh.exists():
            sys.stderr.write(
                f"[soil_client] willow.sh not found. "
                f"Set WILLOW_ROOT or WILLOW_MCP_CMD.\n"
            )
            return

        self._willow_sh = sh
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="soil-client-loop"
        )
        self._thread.start()

        try:
            future = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
            future.result(timeout=15)
            self._available = True
        except Exception as e:
            sys.stderr.write(f"[soil_client] connect failed: {e}\n")

    async def _connect(self):
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp import ClientSession
        from contextlib import AsyncExitStack

        self._exit_stack = AsyncExitStack()
        params = StdioServerParameters(
            command=str(self._willow_sh),
            args=[],
            env={k: str(v) for k, v in os.environ.items()},
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()

    def _call(self, tool_name: str, **kwargs) -> Any:
        if not self._available or self._session is None:
            return None
        kwargs["app_id"] = self._app_id
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(tool_name, kwargs),
            self._loop,
        )
        try:
            result = future.result(timeout=30)
        except Exception as e:
            sys.stderr.write(f"[soil_client] {tool_name} failed: {e}\n")
            return None
        if result and result.content:
            try:
                return json.loads(result.content[0].text)
            except (json.JSONDecodeError, AttributeError):
                return result.content[0].text if result.content else None
        return None

    def get(self, collection: str, record_id: str) -> Optional[dict]:
        result = self._call("store_get", collection=collection, record_id=record_id)
        if isinstance(result, dict) and "error" not in result:
            return result
        return None

    def put(
        self,
        collection: str,
        record: dict,
        record_id: Optional[str] = None,
    ) -> Optional[str]:
        kwargs: dict = {"collection": collection, "record": record}
        if record_id:
            kwargs["record_id"] = record_id
        result = self._call("store_put", **kwargs)
        if isinstance(result, dict):
            return result.get("id") or record_id
        return record_id

    def list(self, collection: str) -> list:
        result = self._call("store_list", collection=collection)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("records", [])
        return []

    def delete(self, collection: str, record_id: str) -> bool:
        result = self._call("store_delete", collection=collection, record_id=record_id)
        if isinstance(result, dict):
            return bool(result.get("ok", result.get("deleted", False)))
        return False

    def close(self):
        if self._exit_stack and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._exit_stack.aclose(), self._loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                pass
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
