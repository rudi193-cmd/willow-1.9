#!/usr/bin/env python3
"""
scripts/willow_watchdog.py
Process watchdog for the Willow MCP server (sap_mcp.py).

Checks every INTERVAL seconds that sap_mcp.py is running.
If the process is missing, restarts it via willow.sh.
Logs all events to ~/.willow/watchdog.log.

Usage (run in background from terminal or as a systemd service):
    python3 scripts/willow_watchdog.py &
    python3 scripts/willow_watchdog.py --interval 30 --dry-run

Systemd one-liner:
    systemd-run --user --unit=willow-watchdog \
        python3 /home/sean-campbell/github/willow-1.9/scripts/willow_watchdog.py
"""
import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WILLOW_SH   = Path.home() / "github" / "willow-1.9" / "willow.sh"
LOG_FILE    = Path.home() / ".willow" / "watchdog.log"
PID_FILE    = Path.home() / ".willow" / "watchdog.pid"
MCP_PATTERN = "sap_mcp.py"
DEFAULT_INTERVAL = 30  # seconds


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _is_running() -> bool:
    try:
        out = subprocess.check_output(["pgrep", "-f", MCP_PATTERN], text=True)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


def _restart(dry_run: bool) -> bool:
    if dry_run:
        _log("DRY RUN — would restart MCP server")
        return True
    if not WILLOW_SH.exists():
        _log(f"ERROR: {WILLOW_SH} not found — cannot restart")
        return False
    try:
        subprocess.Popen(
            ["bash", str(WILLOW_SH), "mcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _log("MCP server restart issued")
        return True
    except Exception as e:
        _log(f"ERROR restarting: {e}")
        return False


def _write_pid() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass


def _cleanup(*_) -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)
    _write_pid()
    _log(f"Watchdog started — interval={args.interval}s pattern='{MCP_PATTERN}'")

    consecutive_fails = 0
    while True:
        if _is_running():
            if consecutive_fails > 0:
                _log("MCP server back online")
            consecutive_fails = 0
        else:
            consecutive_fails += 1
            _log(f"MCP server NOT running (miss #{consecutive_fails}) — restarting")
            _restart(args.dry_run)
            time.sleep(5)  # give it a moment to come up before next check

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
