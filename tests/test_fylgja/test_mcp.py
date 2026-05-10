import json
import subprocess
from unittest.mock import patch, MagicMock
from willow.fylgja._mcp import call

# Subprocess fallback is used for non-store, non-grove tools (e.g. willow_status).
# It sends two JSON lines: initialize + tools/call. stdout has two JSON responses.

def _mock_run(want_tool, response):
    def fake_run(cmd, input, capture_output, text, timeout, **kwargs):
        lines = [l.strip() for l in input.splitlines() if l.strip()]
        tool_line = json.loads(lines[-1])
        assert tool_line["params"]["name"] == want_tool
        init_resp = json.dumps({"jsonrpc": "2.0", "id": 0, "result": {"protocolVersion": "2024-11-05"}})
        tool_resp = json.dumps({"jsonrpc": "2.0", "id": 1, "result": response})
        result = MagicMock()
        result.returncode = 0
        result.stdout = init_resp + "\n" + tool_resp
        result.stderr = ""
        return result
    return fake_run


def test_call_returns_result_dict():
    with patch("subprocess.run", side_effect=_mock_run("willow_status", {"postgres": "up"})):
        result = call("willow_status", {"app_id": "hanuman"})
    assert result == {"postgres": "up"}


def test_call_timeout_returns_error():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
        result = call("willow_status", {"app_id": "hanuman"}, timeout=10)
    assert result["error"] == "timeout"
    assert result["tool"] == "willow_status"


def test_call_nonzero_exit_returns_error():
    mock = MagicMock()
    mock.returncode = 1
    mock.stdout = ""
    mock.stderr = "connection refused"
    with patch("subprocess.run", return_value=mock):
        result = call("willow_status", {"app_id": "hanuman"})
    assert result["error"] == "subprocess_error"


def test_call_sends_correct_jsonrpc_envelope():
    """Subprocess fallback sends proper MCP init + tool call envelope."""
    captured = {}
    def fake_run(cmd, input, capture_output, text, timeout, **kwargs):
        lines = [l.strip() for l in input.splitlines() if l.strip()]
        captured["tool_payload"] = json.loads(lines[-1])
        captured["init_payload"] = json.loads(lines[0])
        m = MagicMock()
        m.returncode = 0
        init_resp = json.dumps({"jsonrpc": "2.0", "id": 0, "result": {}})
        tool_resp = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        m.stdout = init_resp + "\n" + tool_resp
        m.stderr = ""
        return m
    with patch("subprocess.run", side_effect=fake_run):
        call("willow_status", {"app_id": "hanuman"})
    assert captured["init_payload"]["method"] == "initialize"
    assert captured["tool_payload"]["jsonrpc"] == "2.0"
    assert captured["tool_payload"]["method"] == "tools/call"
    assert captured["tool_payload"]["params"]["name"] == "willow_status"


def test_store_list_uses_direct_dispatch():
    """store_* tools bypass subprocess and go direct — no subprocess.run call."""
    with patch("subprocess.run", side_effect=AssertionError("should not call subprocess for store_*")):
        # Will error if store isn't reachable, but will NOT call subprocess
        try:
            call("store_list", {"collection": "corpus/corrections"})
        except AssertionError:
            raise
        except Exception:
            pass  # DB not available in CI — that's fine, just no subprocess
