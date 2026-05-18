#!/usr/bin/env python3
"""
Claude Code hook runner: run a Willow Fylgja event module with env aligned to .mcp.json.

Merges willow MCP server env from the repo's .mcp.json (setdefault — shell env wins),
then ensures WILLOW_AGENT_NAME is set (defaults to hanuman if still missing).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_mcp_env(repo: Path) -> dict[str, str]:
    mcp_path = repo / ".mcp.json"
    if not mcp_path.is_file():
        return {}
    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    willow = data.get("mcpServers", {}).get("willow", {})
    env = willow.get("env") or {}
    out: dict[str, str] = {}
    for k, v in env.items():
        if isinstance(v, str):
            out[k] = v
    return out


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: run_fylgja_hook.py <python.module.to.run>", file=sys.stderr)
        sys.exit(2)
    module = sys.argv[1]
    repo = _repo_root()
    merged = os.environ.copy()
    for k, v in _load_mcp_env(repo).items():
        merged.setdefault(k, v)
    if not (merged.get("WILLOW_AGENT_NAME") or "").strip():
        merged["WILLOW_AGENT_NAME"] = "hanuman"
    merged["PYTHONPATH"] = str(repo)
    venv_python = repo / ".venv-dev" / "bin" / "python3"
    py = str(venv_python) if venv_python.is_file() else sys.executable
    raise SystemExit(subprocess.call([py, "-m", module], env=merged))


if __name__ == "__main__":
    main()
