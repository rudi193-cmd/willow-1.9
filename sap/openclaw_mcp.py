# sap/openclaw_mcp.py — OpenClaw MCP bridge for Hanuman
# b17: OCMCP  ΔΣ=42
"""
Thin MCP wrapper around the openclaw CLI.
Exposes send, status, and sessions as MCP tools.

.mcp.json entry:
  "openclaw": {
    "command": "/home/sean-campbell/.willow-venv/bin/python3",
    "args": ["-m", "sap.openclaw_mcp"],
    "cwd": "/home/sean-campbell/github/willow-1.9"
  }
"""
import json
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

OPENCLAW = str(Path.home() / ".local" / "bin" / "openclaw")

mcp = FastMCP(
    "openclaw",
    instructions=(
        "OpenClaw multi-channel AI gateway. "
        "Send messages across Telegram, Discord, Slack, WhatsApp, Signal, iMessage, and more. "
        "Check channel health and list active sessions."
    ),
)


def _run(args: list[str], timeout: int = 15) -> dict:
    result = subprocess.run(
        [OPENCLAW] + args + ["--json"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip() or f"exit {result.returncode}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw": result.stdout.strip()}


@mcp.tool()
def openclaw_status(deep: bool = False) -> dict:
    """
    Show OpenClaw channel health and recent session recipients.

    Args:
        deep: Probe live channels (WhatsApp, Telegram, Discord, Slack, Signal).
    """
    args = ["status"]
    if deep:
        args.append("--deep")
    return _run(args, timeout=30 if deep else 10)


@mcp.tool()
def openclaw_send(
    message: str,
    target: str,
    channel: str = "",
    account: str = "",
    reply_to: str = "",
) -> dict:
    """
    Send a message via OpenClaw to any connected channel.

    Args:
        message: Message body.
        target: Recipient — phone number, @handle, channel ID, etc.
        channel: Channel name: telegram|whatsapp|discord|slack|signal|irc|imessage|line|googlechat
        account: Optional account id when multiple accounts are configured.
        reply_to: Optional message id to reply to.
    """
    args = ["message", "send", "--message", message, "--target", target]
    if channel:
        args += ["--channel", channel]
    if account:
        args += ["--account", account]
    if reply_to:
        args += ["--reply-to", reply_to]
    return _run(args)


@mcp.tool()
def openclaw_sessions(active_minutes: int = 0, all_agents: bool = False) -> dict:
    """
    List stored OpenClaw conversation sessions.

    Args:
        active_minutes: Only show sessions updated within the past N minutes (0 = all).
        all_agents: Aggregate sessions across all configured agents.
    """
    args = ["sessions"]
    if active_minutes > 0:
        args += ["--active", str(active_minutes)]
    if all_agents:
        args.append("--all-agents")
    return _run(args)


@mcp.tool()
def openclaw_gateway_start(port: int = 18789, force: bool = False) -> dict:
    """
    Start the OpenClaw WebSocket gateway as a background process.

    Args:
        port: Gateway port (default 18789).
        force: Kill anything already bound to the port before starting.
    """
    import os
    import signal as _signal

    args = [OPENCLAW, "gateway", "--port", str(port)]
    if force:
        args.append("--force")

    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"started": True, "pid": proc.pid, "port": port}
    except Exception as e:
        return {"started": False, "error": str(e)}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
