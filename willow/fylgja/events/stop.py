"""
events/stop.py — Stop hook: per-turn cleanup only.
Depth stack and thread file. Heavy pipeline lives in events/shutdown.py — run via /shutdown skill.
"""
import sys
from pathlib import Path

DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")
THREAD_FILE = Path("/tmp/willow-context-thread.json")


def main():
    try:
        depth = int(DEPTH_FILE.read_text().strip()) if DEPTH_FILE.exists() else 0
        if depth > 1:
            DEPTH_FILE.write_text(str(depth - 1))
        else:
            DEPTH_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        THREAD_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
