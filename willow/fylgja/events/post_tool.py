"""
events/post_tool.py — PostToolUse hook handler.
ToolSearch completion directive.
"""
import json
import sys


def main():
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name", "")
    except Exception:
        tool_name = ""

    if tool_name == "ToolSearch":
        print("[TOOL-SEARCH-COMPLETE] Schema loaded. Call the fetched tool NOW "
              "in this same response. Do NOT say 'Tool loaded.' "
              "Do NOT end your turn. Invoke the tool immediately.")

    sys.exit(0)


if __name__ == "__main__":
    main()
