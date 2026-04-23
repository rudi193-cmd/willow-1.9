"""
events/stop.py — Stop hook: per-turn cleanup only.
Depth stack and thread file. Heavy pipeline lives in events/shutdown.py — run via /shutdown skill.
"""
import sys
from pathlib import Path

from willow.fylgja._state import get_trust_state, save_trust_state

DEPTH_FILE = Path("/tmp/willow-agent-depth-stack.txt")
THREAD_FILE = Path("/tmp/willow-context-thread.json")


def read_turns_since(cursor: str, turns_file: Path) -> list[str]:
    """Return lines from turns_file whose timestamp is after cursor. Empty list if file absent."""
    if not turns_file.exists():
        return []
    lines = []
    try:
        for line in turns_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("[") and "]" in line:
                ts = line[1:line.index("]")]
                if ts > cursor:
                    lines.append(line)
    except Exception:
        pass
    return lines


def mark_session_clean(turn_count: int = 0) -> None:
    """Increment clean_session_count in trust state. No-op if turn_count is 0."""
    if turn_count == 0:
        return
    state = get_trust_state()
    if not state:
        return
    state["clean_session_count"] = state.get("clean_session_count", 0) + 1
    save_trust_state(state)


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
