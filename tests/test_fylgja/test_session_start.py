import json
import sys
from io import StringIO
from unittest.mock import patch
from pathlib import Path
import willow.fylgja.events.session_start as m


def _run_handler(stdin_data: dict) -> str:
    inp = StringIO(json.dumps(stdin_data))
    out = StringIO()
    with patch("sys.stdin", inp), patch("sys.stdout", out):
        try:
            m.main()
        except SystemExit:
            pass
    return out.getvalue()


def test_outputs_additional_context_json():
    output = _run_handler({"session_id": "abc123"})
    data = json.loads(output)
    assert "hookSpecificOutput" in data
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "additionalContext" in data["hookSpecificOutput"]


def test_additional_context_contains_index_line():
    output = _run_handler({"session_id": "abc123"})
    data = json.loads(output)
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert "[INDEX]" in ctx


def test_clears_stale_context_thread(tmp_path):
    thread_file = tmp_path / "context-thread.json"
    thread_file.write_text('{"items": []}')
    with patch.object(m, "THREAD_FILE", thread_file):
        _run_handler({"session_id": "abc123"})
    assert not thread_file.exists()
