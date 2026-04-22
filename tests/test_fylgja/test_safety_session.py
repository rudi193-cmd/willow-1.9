"""SAFE protocol session flow — identity, role, stream authorization, consent record."""
from datetime import date
from unittest.mock import patch
import pytest
from willow.fylgja.safety.session import (
    get_session_user_id,
    get_session_role,
    is_stream_authorized,
    authorize_stream,
    build_consent_record,
)


def test_get_session_user_id_returns_env_var():
    with patch.dict("os.environ", {"WILLOW_USER_ID": "sean"}):
        assert get_session_user_id() == "sean"


def test_get_session_user_id_returns_unidentified_when_absent():
    import os
    env = {k: v for k, v in os.environ.items() if k != "WILLOW_USER_ID"}
    with patch.dict("os.environ", env, clear=True):
        uid = get_session_user_id()
    assert uid == "UNIDENTIFIED"


def test_get_session_role_unidentified_is_child():
    role = get_session_role("UNIDENTIFIED")
    assert role == "child"


def test_get_session_role_known_user():
    with patch("willow.fylgja.safety.session.get_user_role", return_value="adult"):
        role = get_session_role("sean")
    assert role == "adult"


def test_stream_not_authorized_by_default(tmp_path):
    session_file = tmp_path / "session.json"
    with patch("willow.fylgja.safety.session.SESSION_FILE", session_file):
        assert is_stream_authorized("relationships") is False


def test_authorize_stream_then_check(tmp_path):
    session_file = tmp_path / "session.json"
    with patch("willow.fylgja.safety.session.SESSION_FILE", session_file):
        authorize_stream("images")
        assert is_stream_authorized("images") is True
        assert is_stream_authorized("relationships") is False


def test_authorize_invalid_stream_is_no_op(tmp_path):
    session_file = tmp_path / "session.json"
    with patch("willow.fylgja.safety.session.SESSION_FILE", session_file):
        authorize_stream("hackers_stream")
        assert is_stream_authorized("hackers_stream") is False


def test_build_consent_record_has_required_fields():
    record = build_consent_record(
        user_id="sean",
        role="adult",
        streams=["relationships", "bookmarks"],
        training_consent=False,
        session_id="abc123",
    )
    for field in ("id", "user_id", "role", "streams_authorized", "training_consent", "date", "expires"):
        assert field in record, f"Missing field: {field}"
    assert record["user_id"] == "sean"
    assert record["expires"] == "session"
    assert record["training_consent"] is False


def test_build_consent_record_id_includes_date():
    record = build_consent_record("sean", "adult", [], False, "abc123")
    today = date.today().strftime("%Y%m%d")
    assert today in record["id"]
