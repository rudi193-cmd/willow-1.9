#!/usr/bin/env python3
"""
nest_watcher.py — Polls Nest drop zones and fires Grove messages when new items arrive.
Runs as a systemd user service alongside grove_monitor_heimdallr.py.
"""
import os
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
GROVE_ROOT = os.environ.get("WILLOW_GROVE_ROOT", str(Path.home() / "github" / "safe-app-willow-grove"))
sys.path.insert(0, GROVE_ROOT)

from sap.core.nest_intake import scan_nest, NEST_DIRS
from sap.core.deliver import grove_send

POLL_INTERVAL = 30
GROVE_CHANNEL = "heimdallr"
PID_FILE      = Path("/tmp/nest-watcher.pid")


def _cleanup(_sig=None, _frame=None):
    PID_FILE.unlink(missing_ok=True)
    sys.exit(0)


signal.signal(signal.SIGTERM, _cleanup)
signal.signal(signal.SIGINT, _cleanup)


def run():
    PID_FILE.write_text(str(os.getpid()))
    dirs = ", ".join(str(d) for d in NEST_DIRS)
    print(f"[nest-watcher] started — polling: {dirs}", flush=True)

    while True:
        try:
            newly_staged = scan_nest()
            if newly_staged:
                lines = [f"  {item['filename']} → {item['track']}" for item in newly_staged]
                msg = f"[nest] {len(newly_staged)} new item(s) staged:\n" + "\n".join(lines)
                grove_send(GROVE_CHANNEL, msg, sender="nest-watcher")
                print(f"[nest-watcher] notified Grove — {len(newly_staged)} item(s)", flush=True)
        except Exception as e:
            print(f"[nest-watcher] error: {e}", flush=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
