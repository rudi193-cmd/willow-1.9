# tests/test_embedder.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_embed_returns_768_floats():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embedding": [0.1] * 768}
    with patch("core.embedder.requests.post", return_value=mock_resp):
        from core.embedder import embed
        result = embed("test text")
    assert isinstance(result, list)
    assert len(result) == 768
    assert all(isinstance(x, float) for x in result)


def test_embed_returns_none_on_connection_failure():
    with patch("core.embedder.requests.post", side_effect=ConnectionError("refused")):
        from core.embedder import embed
        result = embed("test text")
    assert result is None


def test_embed_returns_none_on_bad_status():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("500 Server Error")
    with patch("core.embedder.requests.post", return_value=mock_resp):
        from core.embedder import embed
        result = embed("test text")
    assert result is None
