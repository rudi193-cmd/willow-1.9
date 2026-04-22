import json
from pathlib import Path
from unittest.mock import patch
from willow.fylgja import _state as s


def test_get_turn_count_returns_zero_when_no_file(tmp_path):
    with patch.object(s, "SESSION_FILE", tmp_path / "session.json"):
        assert s.get_turn_count() == 0


def test_get_turn_count_returns_value_from_file(tmp_path):
    f = tmp_path / "session.json"
    f.write_text(json.dumps({"turn_count": 7}))
    with patch.object(s, "SESSION_FILE", f):
        assert s.get_turn_count() == 7


def test_is_first_turn_true_at_zero(tmp_path):
    with patch.object(s, "SESSION_FILE", tmp_path / "missing.json"):
        assert s.is_first_turn() is True


def test_save_and_load_trust_state(tmp_path):
    trust_file = tmp_path / "trust-state.json"
    state = {"current_level": 3, "clean_session_count": 5}
    with patch.object(s, "TRUST_STATE", trust_file):
        s.save_trust_state(state)
        loaded = s.get_trust_state()
    assert loaded["current_level"] == 3
    assert loaded["clean_session_count"] == 5


def test_get_trust_state_returns_empty_when_missing(tmp_path):
    with patch.object(s, "TRUST_STATE", tmp_path / "missing.json"):
        assert s.get_trust_state() == {}


def test_get_set_session_value(tmp_path):
    f = tmp_path / "session.json"
    with patch.object(s, "SESSION_FILE", f):
        s.set_session_value("foo", "bar")
        assert s.get_session_value("foo") == "bar"


def test_consent_level_defaults_to_unidentified(tmp_path):
    with patch.object(s, "SESSION_FILE", tmp_path / "missing.json"):
        assert s.get_consent_level() == "unidentified"
