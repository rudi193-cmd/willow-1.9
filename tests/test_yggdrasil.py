from unittest.mock import patch, MagicMock
import json
import core.yggdrasil as ygg


def _mock_response(content: str):
    resp = MagicMock()
    resp.read.return_value = json.dumps({
        "message": {"content": content}
    }).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_ask_returns_content():
    mock_resp = _mock_response("hello world")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = ygg.ask("test prompt")
    assert result == "hello world"


def test_ask_returns_none_on_failure():
    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = ygg.ask("test prompt")
    assert result is None


def test_ask_structured_parses_format():
    mock_resp = _mock_response("SUMMARY: Don't use Bash. | IMPORTANCE: 8")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = ygg.ask_structured("test")
    assert result["summary"] == "Don't use Bash."
    assert result["importance"] == 8


def test_ask_structured_fallback_on_bad_format():
    mock_resp = _mock_response("Just some free text without format")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = ygg.ask_structured("test")
    assert result["summary"] is not None
    assert 1 <= result["importance"] <= 10
