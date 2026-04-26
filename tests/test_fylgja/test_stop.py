import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from willow.fylgja.events.stop import (
    read_turns_since,
    mark_session_clean,
)
import willow.fylgja.events.stop as s


def test_read_turns_since_returns_empty_when_no_file(tmp_path):
    turns_file = tmp_path / "turns.txt"
    result = read_turns_since("1970-01-01T00:00:00+00:00", turns_file)
    assert result == []


def test_read_turns_since_returns_turns_after_cursor(tmp_path):
    turns_file = tmp_path / "turns.txt"
    turns_file.write_text(
        "[2026-04-22T10:00:00+00:00] [abc] HUMAN\n"
        "[2026-04-22T09:00:00+00:00] [abc] HUMAN\n"
    )
    result = read_turns_since("2026-04-22T09:30:00+00:00", turns_file)
    assert len(result) == 1
    assert "2026-04-22T10:00:00+00:00" in result[0]


def test_mark_session_clean_increments_count(tmp_path):
    trust_file = tmp_path / "trust.json"
    trust_file.write_text(json.dumps({"clean_session_count": 3}))
    with patch("willow.fylgja._state.TRUST_STATE", trust_file):
        with patch("willow.fylgja.events.stop.get_trust_state") as mock_get:
            with patch("willow.fylgja.events.stop.save_trust_state") as mock_save:
                mock_get.return_value = {"clean_session_count": 3}
                mark_session_clean(turn_count=5)
                assert mock_save.called
                saved_state = mock_save.call_args[0][0]
                assert saved_state["clean_session_count"] == 4


def test_mark_session_clean_skips_on_zero_turns(tmp_path):
    with patch("willow.fylgja.events.stop.get_trust_state") as mock_get:
        with patch("willow.fylgja.events.stop.save_trust_state") as mock_save:
            mock_get.return_value = {"clean_session_count": 3}
            mark_session_clean(turn_count=0)
            assert not mock_save.called


def _run_stop(stdin_data: dict) -> None:
    import willow.fylgja.events.stop as s
    inp = StringIO(json.dumps(stdin_data))
    with patch("sys.stdin", inp):
        try:
            s.main()
        except SystemExit:
            pass


def test_stop_writes_session_composite():
    """Stop hook should store_put a session composite atom."""
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {}
    with patch("willow.fylgja.events.stop.call", fake_call):
        _run_stop({"session_id": "abcdef1234567890"})
    store_calls = [c for c in calls if c[0] == "store_put"]
    assert len(store_calls) == 1
    record = store_calls[0][1]["record"]
    assert record["type"] == "session"
    assert record["session_id"] == "abcdef1234567890"
    assert record["id"].startswith("session-abcdef12")


def test_stop_session_composite_has_required_fields():
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {}
    with patch("willow.fylgja.events.stop.call", fake_call):
        _run_stop({"session_id": "abcdef1234567890"})
    record = [c for c in calls if c[0] == "store_put"][0][1]["record"]
    for field in ("id", "session_id", "date", "type"):
        assert field in record, f"Missing field: {field}"


def test_stop_mcp_failure_does_not_crash():
    """Stop hook must complete even if MCP is down."""
    def fake_call(tool, args, timeout=5):
        raise RuntimeError("MCP down")
    with patch("willow.fylgja.events.stop.call", fake_call):
        _run_stop({"session_id": "abc123"})  # must not raise
