"""
safety/session.py — SAFE protocol session flow.
Identity declaration → role resolution → stream authorization → consent record.
"""
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from willow.fylgja._mcp import call
from willow.fylgja.safety.deployment import get_user_role

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")
SESSION_FILE = Path(f"/tmp/willow-session-{AGENT}.json")
VALID_STREAMS = frozenset({"relationships", "images", "bookmarks", "dating"})


def get_session_user_id() -> str:
    return os.environ.get("WILLOW_USER_ID", "UNIDENTIFIED")


def get_session_role(user_id: str) -> str:
    if user_id == "UNIDENTIFIED":
        return "child"
    return get_user_role(user_id)


def _read_session() -> dict:
    try:
        if SESSION_FILE.exists():
            return json.loads(SESSION_FILE.read_text())
    except Exception:
        pass
    return {}


def _write_session(data: dict) -> None:
    try:
        existing = _read_session()
        existing.update(data)
        SESSION_FILE.write_text(json.dumps(existing))
    except Exception:
        pass


def is_stream_authorized(stream: str) -> bool:
    return stream in _read_session().get("authorized_streams", [])


def authorize_stream(stream: str) -> None:
    if stream not in VALID_STREAMS:
        return
    authorized = set(_read_session().get("authorized_streams", []))
    authorized.add(stream)
    _write_session({"authorized_streams": list(authorized)})


def get_training_consent() -> bool:
    return bool(_read_session().get("training_consent", False))


def build_consent_record(
    user_id: str,
    role: str,
    streams: list,
    training_consent: bool,
    session_id: str,
) -> dict:
    today = date.today().strftime("%Y%m%d")
    return {
        "id": f"consent-{user_id}-{today}-{session_id[:8]}",
        "user_id": user_id,
        "role": role,
        "streams_authorized": streams,
        "training_consent": training_consent,
        "date": today,
        "session_id": session_id,
        "expires": "session",
        "written_at": datetime.now(timezone.utc).isoformat(),
    }


def close_session(session_id: str) -> None:
    """Called from stop.py — write consent record to ledger and expire authorizations."""
    user_id = get_session_user_id()
    role = get_session_role(user_id)
    state = _read_session()
    streams = state.get("authorized_streams", [])
    training_consent = state.get("training_consent", False)
    record = build_consent_record(user_id, role, streams, training_consent, session_id)
    try:
        call("store_put", {
            "app_id": AGENT,
            "collection": "willow/consent_records",
            "record": record,
        }, timeout=5)
    except Exception:
        pass
    _write_session({"authorized_streams": [], "training_consent": False})
