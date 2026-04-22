import json
import subprocess
from unittest.mock import patch, MagicMock
from willow.fylgja._mcp import call


def _mock_run(want_tool, response):
    def fake_run(cmd, input, capture_output, text, timeout):
        data = json.loads(input)
        assert data["params"]["name"] == want_tool
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps({"result": response})
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
    captured = {}
    def fake_run(cmd, input, capture_output, text, timeout):
        captured["payload"] = json.loads(input)
        m = MagicMock()
        m.returncode = 0
        m.stdout = json.dumps({"result": {}})
        m.stderr = ""
        return m
    with patch("subprocess.run", side_effect=fake_run):
        call("store_put", {"collection": "test", "record": {"id": "x"}})
    assert captured["payload"]["jsonrpc"] == "2.0"
    assert captured["payload"]["method"] == "tools/call"
    assert captured["payload"]["params"]["name"] == "store_put"
