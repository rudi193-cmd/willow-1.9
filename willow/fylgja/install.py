"""
install.py — Wire Fylgja into Claude Code settings.json.
Run: python3 -m willow.fylgja.install [--dry-run] [--settings PATH]
"""
import argparse
import json
import sys
from pathlib import Path

_DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"
_PACKAGE_ROOT = Path(__file__).parent.parent.parent  # willow-1.9/


def _event_command(package_root: Path, module: str) -> str:
    python = sys.executable
    return f"PYTHONPATH={package_root} {python} -m willow.fylgja.events.{module}"


def build_hooks_block(package_root: Path) -> dict:
    cmd = lambda m: _event_command(package_root, m)
    return {
        "SessionStart": [
            {"hooks": [{"type": "command", "command": cmd("session_start"),
                        "timeout": 15, "statusMessage": "Building session index..."}]}
        ],
        "PreToolUse": [
            {"matcher": "Bash",
             "hooks": [{"type": "command", "command": cmd("pre_tool"), "timeout": 5}]},
            {"matcher": "Agent",
             "hooks": [{"type": "command", "command": cmd("pre_tool"), "timeout": 5}]},
            {"matcher": "Read",
             "hooks": [{"type": "command", "command": cmd("pre_tool"), "timeout": 5}]},
            {"matcher": "mcp__willow__store_put|mcp__willow__store_update|mcp__willow__willow_knowledge_ingest|mcp__willow__willow_ratify",
             "hooks": [{"type": "command", "command": cmd("pre_tool"), "timeout": 5}]},
        ],
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": cmd("prompt_submit"), "timeout": 10}]}
        ],
        "PostToolUse": [
            {"matcher": "ToolSearch",
             "hooks": [{"type": "command", "command": cmd("post_tool"), "timeout": 5}]}
        ],
        "Stop": [
            {"hooks": [{"type": "command", "command": cmd("stop"), "timeout": 30,
                        "statusMessage": "Composting session..."}]}
        ],
    }


def apply_hooks(settings_path: Path = _DEFAULT_SETTINGS,
                package_root: Path = _PACKAGE_ROOT,
                dry_run: bool = False) -> None:
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    hooks = build_hooks_block(package_root)
    if dry_run:
        print("[install] Dry run — would write hooks block:")
        print(json.dumps(hooks, indent=2))
        return
    settings["hooks"] = hooks
    tmp = settings_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2))
    tmp.replace(settings_path)
    print(f"[install] Hooks written to {settings_path}")


def main():
    parser = argparse.ArgumentParser(description="Wire Fylgja into Claude Code settings.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--settings", type=Path, default=_DEFAULT_SETTINGS)
    parser.add_argument("--package-root", type=Path, default=_PACKAGE_ROOT)
    args = parser.parse_args()
    apply_hooks(settings_path=args.settings, package_root=args.package_root, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
