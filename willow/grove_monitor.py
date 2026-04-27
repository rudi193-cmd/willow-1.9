#!/usr/bin/env python3
"""
grove_monitor.py — Persistent Grove channel monitor.
Polls grove_watch_all via MCP, emits one stdout line per new message.
Cursors are persisted to SOIL so restarts resume from last position.

Usage:
  python3 willow/grove_monitor.py [--agent hanuman] [--cursors general:148,...]
"""
import json
import sys
import time
import argparse
import subprocess
from pathlib import Path

WILLOW_MCP = Path.home() / ".local" / "bin" / "willow-mcp"
GROVE_MCP_CMD = ["python3", "-m", "grove.mcp_local"]
GROVE_MCP_CWD = str(Path.home() / "github" / "safe-app-grove")
GROVE_ENV = {
    **__import__("os").environ,
    "WILLOW_PG_DB": "willow_19",
    "WILLOW_PG_USER": __import__("os").environ.get("USER", ""),
    "PYTHONPATH": str(Path.home() / "github" / "safe-app-grove"),
}
POLL_TIMEOUT = 25
CHANNELS = ["general", "architecture", "handoffs", "WillowLearning", "HumanLearning",
            "learnings", "dispatch", "readme"]
CURSOR_SAVE_EVERY = 5  # save cursors every N successful polls


def mcp_call(tool: str, arguments: dict, timeout: int = None, grove: bool = False) -> dict:
    """Call a tool via MCP subprocess. grove=True routes to the Grove stdio server."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    })
    try:
        if grove:
            result = subprocess.run(
                GROVE_MCP_CMD, input=payload, capture_output=True,
                text=True, timeout=timeout or (POLL_TIMEOUT + 10),
                cwd=GROVE_MCP_CWD, env=GROVE_ENV,
            )
        else:
            result = subprocess.run(
                [str(WILLOW_MCP)], input=payload, capture_output=True,
                text=True, timeout=timeout or (POLL_TIMEOUT + 10),
            )
        data = json.loads(result.stdout)
        return data.get("result", {})
    except Exception as e:
        print(f"[grove_monitor] mcp error ({tool}): {e}", file=sys.stderr, flush=True)
        return {}


def load_cursors_from_soil(agent: str) -> dict:
    """Load persisted cursors from SOIL store."""
    result = mcp_call("store_get", {
        "app_id": agent,
        "collection": "grove/cursors",
        "record_id": agent,
    }, timeout=5)
    if isinstance(result, dict) and result.get("cursors"):
        return result["cursors"]
    return {}


def save_cursors_to_soil(agent: str, cursors: dict) -> None:
    """Persist cursors to SOIL so restarts resume from last position."""
    mcp_call("store_put", {
        "app_id": agent,
        "collection": "grove/cursors",
        "record": {"id": agent, "cursors": cursors},
    }, timeout=5)


def parse_cursors(s: str) -> dict:
    cursors = {}
    for part in s.split(","):
        if ":" in part:
            ch, val = part.split(":", 1)
            cursors[ch.strip()] = int(val.strip())
    return cursors


def extract_messages(result) -> dict:
    raw = result
    if isinstance(raw, list):
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                try:
                    raw = json.loads(block["text"])
                except Exception:
                    pass
                break
    return raw if isinstance(raw, dict) else {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="hanuman")
    parser.add_argument("--cursors", default="")
    args = parser.parse_args()

    agent = args.agent

    # Priority: CLI args > SOIL > zero
    if args.cursors:
        cursors = parse_cursors(args.cursors)
    else:
        cursors = load_cursors_from_soil(agent)
        if cursors:
            print(f"[grove] resumed cursors from SOIL: {cursors}", flush=True)

    for ch in CHANNELS:
        cursors.setdefault(ch, 0)

    print(f"[grove] watching {list(cursors.keys())} as {agent}", flush=True)

    # Announce on bus that we're online
    mcp_call("grove_heartbeat", {"sender": agent}, timeout=5, grove=True)

    poll_count = 0
    while True:
        try:
            result = mcp_call("grove_watch_all", {"cursors": cursors}, grove=True)
            messages_by_channel = extract_messages(result)

            updated = False
            for channel, messages in messages_by_channel.items():
                if not isinstance(messages, list):
                    continue
                for msg in messages:
                    msg_id = msg.get("id", 0)
                    sender = msg.get("sender", "?")
                    bus_type = msg.get("bus_type", "")
                    to_agent = msg.get("to_agent", "__all__")
                    content = msg.get("content", "").replace("\n", " ")[:120]

                    tag = f"[{bus_type}→{to_agent}]" if bus_type else ""
                    print(f"[grove:{channel}]{tag} {sender}: {content}", flush=True)

                    if msg_id > cursors.get(channel, 0):
                        cursors[channel] = msg_id
                        updated = True

            if updated:
                poll_count += 1
                if poll_count % CURSOR_SAVE_EVERY == 0:
                    save_cursors_to_soil(agent, cursors)
            else:
                # Brief sleep when nothing new — grove stdio server has no blocking wait
                time.sleep(5)

        except KeyboardInterrupt:
            save_cursors_to_soil(agent, cursors)
            print(f"[grove] cursors saved on exit", flush=True)
            break
        except Exception as e:
            print(f"[grove_monitor] loop error: {e}", file=sys.stderr, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
