"""
willow/corpus/sandbox.py — Phase 0 Corpus Collapse stub.
b17: CRPS0  ΔΣ=42

Captures the three things that matter most before intelligence passes exist:
  - Why the user is here (seed)
  - What they prefer (preferences)
  - What they corrected (corrections)

Atom format matches the full spec taxonomy. sandbox=True is the only difference.
When Phase 1 ships: remove sandbox=True, wire in intelligence passes. Done.

Collections (all in SOIL):
  corpus/seed         — one record per user, record_id="seed"
  corpus/preferences  — preference atoms, record_id="pref-<8hex>"
  corpus/corrections  — correction atoms, record_id="corr-<8hex>"
  corpus/sessions     — session summary atoms, record_id="session-YYYYMMDD"
"""
import uuid
from datetime import datetime, timezone

try:
    from willow.fylgja._mcp import call
except Exception:
    call = None  # type: ignore[assignment]

_B17 = "CRPS0"
_SEED_COLLECTION = "corpus/seed"
_PREF_COLLECTION = "corpus/preferences"
_CORR_COLLECTION = "corpus/corrections"
_SESS_COLLECTION = "corpus/sessions"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _store_get(app_id: str, collection: str, record_id: str) -> dict:
    if call is None:
        return {}
    result = call("store_get", {"app_id": app_id, "collection": collection, "record_id": record_id}, timeout=3)
    return result if isinstance(result, dict) and not result.get("error") else {}


def _store_put(app_id: str, collection: str, record: dict) -> bool:
    if call is None:
        return False
    result = call("store_put", {"app_id": app_id, "collection": collection, "record": record}, timeout=4)
    return not (isinstance(result, dict) and result.get("error"))


def _store_list(app_id: str, collection: str) -> list:
    if call is None:
        return []
    result = call("store_list", {"app_id": app_id, "collection": collection}, timeout=5)
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "records" in result:
        return result["records"]
    return []


def needs_intake(app_id: str) -> bool:
    """Return True if no seed atom exists — user has never answered 'Why are you here?'"""
    seed = _store_get(app_id, _SEED_COLLECTION, "seed")
    return not bool(seed.get("content"))


def save_seed(app_id: str, why_here: str, session_id: str = "") -> str:
    """Save the user's answer to 'Why are you here?' as the corpus seed atom."""
    record = {
        "id": "seed",
        "type": "seed",
        "source": "user_statement",
        "content": why_here.strip(),
        "session_id": session_id,
        "created_at": _now(),
        "sandbox": True,
        "b17": _B17,
    }
    _store_put(app_id, _SEED_COLLECTION, record)
    return "seed"


def save_preference(app_id: str, content: str, session_id: str = "") -> str:
    """Save a user preference atom (explicit statement about how they like to work)."""
    record_id = _short_id("pref")
    record = {
        "id": record_id,
        "type": "preference",
        "source": "user_statement",
        "content": content.strip(),
        "session_id": session_id,
        "created_at": _now(),
        "sandbox": True,
        "b17": _B17,
    }
    _store_put(app_id, _PREF_COLLECTION, record)
    return record_id


def save_correction(app_id: str, content: str, session_id: str = "") -> str:
    """Save a correction atom (the user corrected the agent's behavior)."""
    record_id = _short_id("corr")
    record = {
        "id": record_id,
        "type": "correction",
        "source": "observation",
        "content": content.strip(),
        "session_id": session_id,
        "created_at": _now(),
        "sandbox": True,
        "b17": _B17,
    }
    _store_put(app_id, _CORR_COLLECTION, record)
    return record_id


def save_session(app_id: str, session_id: str, summary: str = "") -> str:
    """Save a session summary atom. Uses date-based ID — idempotent per day."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    record_id = f"session-{today}"
    existing = _store_get(app_id, _SESS_COLLECTION, record_id)
    if existing.get("id"):
        return record_id  # already written today
    record = {
        "id": record_id,
        "type": "session",
        "source": "observation",
        "content": summary.strip() if summary else "",
        "session_id": session_id,
        "created_at": _now(),
        "sandbox": True,
        "b17": _B17,
    }
    _store_put(app_id, _SESS_COLLECTION, record)
    return record_id


def load_context(app_id: str) -> dict:
    """
    Load corpus context for session startup injection.
    Returns {"seed": str, "preferences": list[str], "corrections": list[str]}
    Empty strings/lists mean no data yet — caller decides what to show.
    """
    seed_record = _store_get(app_id, _SEED_COLLECTION, "seed")
    seed = seed_record.get("content", "")

    prefs_raw = _store_list(app_id, _PREF_COLLECTION)
    prefs = [r.get("content", "") for r in prefs_raw if r.get("content")]

    corrs_raw = _store_list(app_id, _CORR_COLLECTION)
    corrs = [r.get("content", "") for r in corrs_raw if r.get("content")]

    return {
        "seed": seed,
        "preferences": prefs[-10:],   # most recent 10
        "corrections": corrs[-10:],   # most recent 10
    }
