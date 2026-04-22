import json
import sys
from io import StringIO
from unittest.mock import patch


def _run(stdin_data: dict) -> str:
    import willow.fylgja.events.post_tool as m
    inp = StringIO(json.dumps(stdin_data))
    out = StringIO()
    with patch("sys.stdin", inp), patch("sys.stdout", out):
        try:
            m.main()
        except SystemExit:
            pass
    return out.getvalue()


def test_toolsearch_emits_directive():
    out = _run({"tool_name": "ToolSearch", "tool_input": {}})
    assert "TOOL-SEARCH-COMPLETE" in out
    assert "NOW" in out


def test_other_tool_emits_nothing():
    out = _run({"tool_name": "Read", "tool_input": {}})
    assert out.strip() == ""
