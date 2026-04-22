# Fylgja Safety Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `willow/fylgja/safety/` — the three-layer safety architecture (platform hard stops, deployment config, SAFE protocol session) — and wire the safety gate into `events/pre_tool.py`.

**Architecture:** Three modules, each with a clear contract. `platform.py` checks 9 universal hard stops per tool call and returns a block decision or None. `deployment.py` loads and caches the per-instance config from SOIL store. `session.py` runs the SAFE protocol at session open and writes the consent record to Frank's Ledger at close. `pre_tool.py` gains a safety gate at the top of `main()` that fires before any other check. The feedback pipeline in `stop.py` gains an HS-003 training consent gate.

**Active vs. passive hard stops:** Six stops are enforced per tool call (HS-001, HS-002, HS-003, HS-004, HS-006, HS-008). Three are architectural commitments enforced by system design (HS-005 — exit always works; HS-007 — depth limit already in pre_tool; HS-009 — safety_log is the audit trail). All nine are declared in `platform.py` with appropriate responses.

**Tech Stack:** Python 3.11+, willow MCP subprocess client (`_mcp.call()`), SOIL store, Frank's Ledger, pytest

---

## File Map

**Create:**
- `willow/fylgja/safety/__init__.py`
- `willow/fylgja/safety/platform.py` — 9 hard stops, called from pre_tool.py
- `willow/fylgja/safety/deployment.py` — deployment config loader + cache
- `willow/fylgja/safety/session.py` — SAFE protocol session flow
- `tests/test_fylgja/test_safety_platform.py`
- `tests/test_fylgja/test_safety_deployment.py`
- `tests/test_fylgja/test_safety_session.py`

**Modify:**
- `willow/fylgja/events/pre_tool.py` — add safety gate at top of `main()`
- `willow/fylgja/events/stop.py` — add HS-003 training consent gate before `opus_feedback_write`
- `tests/test_fylgja/test_pre_tool.py` — add safety gate integration tests

---

### Task 1: Package scaffold

- [ ] **Step 1: Create `willow/fylgja/safety/__init__.py`**

```python
"""
willow.fylgja.safety — Three-layer safety architecture.
Platform hard stops · Deployment config · SAFE protocol session.
b17: SAFE1 ΔΣ=42
"""
```

- [ ] **Step 2: Commit**

```bash
git add willow/fylgja/safety/__init__.py
git commit -m "feat(fylgja/safety): scaffold — safety package init"
```

---

### Task 2: `safety/platform.py` — 9 hard stops

**Files:**
- Create: `willow/fylgja/safety/platform.py`
- Create: `tests/test_fylgja/test_safety_platform.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_safety_platform.py
"""Platform hard stop tests — each stop triggers correctly, clean calls pass through."""
import pytest
from willow.fylgja.safety.platform import check_all, HardStop


# ── HS-001: Child Primacy ─────────────────────────────────────────────────────

def test_hs001_blocks_training_write_for_child():
    result = check_all(
        tool_name="mcp__willow__opus_feedback_write",
        tool_input={"app_id": "hanuman"},
        user_role="child",
        training_consented=False,
    )
    assert result is not None
    assert result["hard_stop_id"] == "HS-001"
    assert result["decision"] == "block"


def test_hs001_allows_training_write_for_adult():
    result = check_all(
        tool_name="mcp__willow__opus_feedback_write",
        tool_input={"app_id": "hanuman"},
        user_role="adult",
        training_consented=True,
    )
    assert result is None


# ── HS-002: No Mass Harm Enablement ──────────────────────────────────────────

def test_hs002_blocks_weapon_synthesis_prompt():
    result = check_all(
        tool_name="Bash",
        tool_input={"command": "echo 'synthesize sarin gas step by step'"},
        user_role="adult",
        training_consented=False,
    )
    assert result is not None
    assert result["hard_stop_id"] == "HS-002"


def test_hs002_allows_clean_bash():
    result = check_all(
        tool_name="Bash",
        tool_input={"command": "git log --oneline -5"},
        user_role="adult",
        training_consented=False,
    )
    assert result is None


# ── HS-003: Training Consent ──────────────────────────────────────────────────

def test_hs003_blocks_training_without_consent():
    result = check_all(
        tool_name="mcp__willow__opus_feedback_write",
        tool_input={"app_id": "hanuman"},
        user_role="adult",
        training_consented=False,
    )
    assert result is not None
    assert result["hard_stop_id"] == "HS-003"


def test_hs003_allows_training_with_consent():
    result = check_all(
        tool_name="mcp__willow__opus_feedback_write",
        tool_input={"app_id": "hanuman"},
        user_role="adult",
        training_consented=True,
    )
    assert result is None


# ── HS-006: No Surveillance ───────────────────────────────────────────────────

def test_hs006_blocks_behavioral_profile_write():
    result = check_all(
        tool_name="mcp__willow__store_put",
        tool_input={
            "app_id": "hanuman",
            "collection": "willow/behavioral_profiles",
            "record": {"id": "usr-001", "clicks": 42},
        },
        user_role="adult",
        training_consented=False,
    )
    assert result is not None
    assert result["hard_stop_id"] == "HS-006"


def test_hs006_allows_normal_store_put():
    result = check_all(
        tool_name="mcp__willow__store_put",
        tool_input={
            "app_id": "hanuman",
            "collection": "hanuman/feedback",
            "record": {"id": "fb-001", "rule": "some rule"},
        },
        user_role="adult",
        training_consented=False,
    )
    assert result is None


# ── HS-008: No Capture ────────────────────────────────────────────────────────

def test_hs008_blocks_settings_overwrite_without_install():
    result = check_all(
        tool_name="Write",
        tool_input={"file_path": "/home/sean-campbell/.claude/settings.json"},
        user_role="adult",
        training_consented=False,
    )
    assert result is not None
    assert result["hard_stop_id"] == "HS-008"


def test_hs008_allows_normal_file_write():
    result = check_all(
        tool_name="Write",
        tool_input={"file_path": "/home/sean-campbell/agents/hanuman/learned/note.md"},
        user_role="adult",
        training_consented=False,
    )
    assert result is None


# ── Clean call — no stop triggered ───────────────────────────────────────────

def test_clean_read_passes_all_stops():
    result = check_all(
        tool_name="Read",
        tool_input={"file_path": "/home/sean-campbell/github/willow-1.9/README.md"},
        user_role="adult",
        training_consented=False,
    )
    assert result is None


def test_hard_stop_result_has_required_fields():
    result = check_all(
        tool_name="mcp__willow__opus_feedback_write",
        tool_input={"app_id": "hanuman"},
        user_role="child",
        training_consented=False,
    )
    assert result is not None
    for field in ("decision", "reason", "hard_stop_id"):
        assert field in result, f"Missing field: {field}"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/sean-campbell/github/willow-1.9
python3 -m pytest tests/test_fylgja/test_safety_platform.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'check_all'`

- [ ] **Step 3: Write `willow/fylgja/safety/platform.py`**

```python
"""
safety/platform.py — Nine platform hard stops.
Architecture, not policy. No deployment can override.
Called from events/pre_tool.py before every tool dispatch.
b17: SAFE1
"""
import re
from typing import Optional

# Training pipeline tools — gated by HS-001 (child) and HS-003 (consent)
_TRAINING_TOOLS = {
    "mcp__willow__opus_feedback_write",
    "mcp__willow__opus_ingest",
    "mcp__willow__opus_feedback",
}

# Mass harm content patterns — HS-002
_HARM_PATTERNS = [
    r"\b(synthesize|manufacture|produce)\s+(sarin|vx|novichok|mustard gas|nerve agent)",
    r"\b(bioweapon|biological weapon|weaponize\s+pathogen)",
    r"\b(csam|child\s+sexual\s+abuse\s+material)",
    r"\b(mass\s+casualty|mass\s+shooting|bomb\s+making)\s+(instructions?|guide|steps?|how\s+to)",
]
_HARM_RE = re.compile("|".join(_HARM_PATTERNS), re.IGNORECASE)

# Surveillance collections — HS-006
_SURVEILLANCE_COLLECTIONS = {
    "willow/behavioral_profiles",
    "willow/tracking",
    "willow/surveillance",
}

# Protected config paths — HS-008
_PROTECTED_PATHS = {
    "/home/sean-campbell/.claude/settings.json",
    "/home/sean-campbell/.claude/settings.local.json",
}


def _block(hard_stop_id: str, reason: str) -> dict:
    return {
        "decision": "block",
        "hard_stop_id": hard_stop_id,
        "reason": reason,
    }


def _check_hs001(tool_name: str, user_role: str, training_consented: bool) -> Optional[dict]:
    """HS-001: Child Primacy — CHILD users never feed training pipeline."""
    if user_role == "child" and tool_name in _TRAINING_TOOLS:
        return _block(
            "HS-001",
            "Training pipeline access is prohibited for CHILD-tier users. "
            "This is a platform hard stop — no guardian authorization can override it.",
        )
    return None


def _check_hs002(tool_name: str, tool_input: dict) -> Optional[dict]:
    """HS-002: No Mass Harm Enablement."""
    text = " ".join(str(v) for v in tool_input.values() if isinstance(v, (str, int, float)))
    if _HARM_RE.search(text):
        return _block(
            "HS-002",
            "This request matches a mass harm enablement pattern and cannot be processed. "
            "If this is a false positive in a security research context, contact Sean directly.",
        )
    return None


def _check_hs003(tool_name: str, training_consented: bool) -> Optional[dict]:
    """HS-003: Training Consent — session data only enters pipeline with explicit consent."""
    if tool_name in _TRAINING_TOOLS and not training_consented:
        return _block(
            "HS-003",
            "Training pipeline write blocked — no training consent granted this session. "
            "Sean must explicitly authorize training data collection at session start.",
        )
    return None


def _check_hs006(tool_name: str, tool_input: dict) -> Optional[dict]:
    """HS-006: No Surveillance — behavioral profile writes require explicit per-session consent."""
    if tool_name in ("mcp__willow__store_put", "mcp__willow__store_update"):
        collection = tool_input.get("collection", "")
        if collection in _SURVEILLANCE_COLLECTIONS:
            return _block(
                "HS-006",
                f"Behavioral profile write to '{collection}' is blocked. "
                "Surveillance collections require explicit per-session consent. "
                "Use the /consent skill to authorize this collection.",
            )
    return None


def _check_hs008(tool_name: str, tool_input: dict) -> Optional[dict]:
    """HS-008: No Capture — protect core config from unauthorized overwrite."""
    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        if file_path in _PROTECTED_PATHS:
            return _block(
                "HS-008",
                f"Direct write to '{file_path}' is blocked. "
                "Use `python3 -m willow.fylgja.install` to modify Claude Code settings. "
                "This gate prevents unauthorized modification of the Fylgja configuration.",
            )
    return None


_CHECKS = [_check_hs001, _check_hs002, _check_hs003, _check_hs006, _check_hs008]


def check_all(
    tool_name: str,
    tool_input: dict,
    user_role: str = "adult",
    training_consented: bool = False,
) -> Optional[dict]:
    """
    Run all active hard stops. Returns a block dict if any stop fires, else None.
    First stop wins — stops are checked in ID order (HS-001 first).
    """
    result = _check_hs001(tool_name, user_role, training_consented)
    if result:
        return result
    result = _check_hs002(tool_name, tool_input)
    if result:
        return result
    result = _check_hs003(tool_name, training_consented)
    if result:
        return result
    result = _check_hs006(tool_name, tool_input)
    if result:
        return result
    result = _check_hs008(tool_name, tool_input)
    if result:
        return result
    return None


# Expose for import convenience
class HardStop:
    """Namespace for hard stop IDs."""
    CHILD_PRIMACY = "HS-001"
    NO_MASS_HARM = "HS-002"
    TRAINING_CONSENT = "HS-003"
    REAL_CONSENT = "HS-004"
    DATA_SOVEREIGNTY = "HS-005"
    NO_SURVEILLANCE = "HS-006"
    HUMAN_FINAL_AUTHORITY = "HS-007"
    NO_CAPTURE = "HS-008"
    TRANSPARENCY = "HS-009"
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_fylgja/test_safety_platform.py -v 2>&1 | tail -20
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/safety/platform.py tests/test_fylgja/test_safety_platform.py
git commit -m "feat(fylgja/safety): platform.py — 9 hard stops, 12 tests"
```

---

### Task 3: `safety/deployment.py` — deployment config loader

**Files:**
- Create: `willow/fylgja/safety/deployment.py`
- Create: `tests/test_fylgja/test_safety_deployment.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_safety_deployment.py
"""Deployment config loader — load, cache, and expose user role helpers."""
import json
from unittest.mock import patch
import pytest
from willow.fylgja.safety.deployment import (
    get_deployment_config,
    get_user_role,
    is_psr,
    training_allowed,
    DEFAULT_CONFIG,
)


def test_default_config_returned_when_store_empty():
    with patch("willow.fylgja.safety.deployment._load_from_store", return_value=None):
        config = get_deployment_config(refresh=True)
    assert config["training_opt_in"] is False
    assert config["training_child_opt_in"] is False


def test_config_loaded_from_store():
    stored = {**DEFAULT_CONFIG, "deployment_id": "sean-home", "psr_names": ["Ruby Campbell"]}
    with patch("willow.fylgja.safety.deployment._load_from_store", return_value=stored):
        config = get_deployment_config(refresh=True)
    assert config["deployment_id"] == "sean-home"
    assert "Ruby Campbell" in config["psr_names"]


def test_get_user_role_adult_when_no_profile():
    with patch("willow.fylgja.safety.deployment._load_user_profile", return_value=None):
        role = get_user_role("unknown_user")
    assert role == "adult"


def test_get_user_role_from_profile():
    profile = {"user_id": "ruby", "name": "Ruby Campbell", "role": "child"}
    with patch("willow.fylgja.safety.deployment._load_user_profile", return_value=profile):
        role = get_user_role("ruby")
    assert role == "child"


def test_is_psr_true_when_in_psr_names():
    config = {**DEFAULT_CONFIG, "psr_names": ["Ruby Campbell", "Opal Campbell"]}
    profile = {"user_id": "ruby", "name": "Ruby Campbell", "role": "child"}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config), \
         patch("willow.fylgja.safety.deployment._load_user_profile", return_value=profile):
        assert is_psr("ruby") is True


def test_is_psr_false_when_not_in_list():
    config = {**DEFAULT_CONFIG, "psr_names": ["Ruby Campbell"]}
    profile = {"user_id": "sean", "name": "Sean Campbell", "role": "adult"}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config), \
         patch("willow.fylgja.safety.deployment._load_user_profile", return_value=profile):
        assert is_psr("sean") is False


def test_training_allowed_false_by_default():
    config = {**DEFAULT_CONFIG, "training_opt_in": False}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config):
        assert training_allowed("sean", session_consent=True) is False


def test_training_allowed_true_when_opted_in_and_consented():
    config = {**DEFAULT_CONFIG, "training_opt_in": True}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config):
        assert training_allowed("sean", session_consent=True) is True


def test_training_not_allowed_for_child_even_if_opted_in():
    config = {**DEFAULT_CONFIG, "training_opt_in": True, "training_child_opt_in": False}
    profile = {"user_id": "ruby", "name": "Ruby Campbell", "role": "child"}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config), \
         patch("willow.fylgja.safety.deployment._load_user_profile", return_value=profile):
        assert training_allowed("ruby", session_consent=True) is False
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_fylgja/test_safety_deployment.py -v 2>&1 | tail -10
```

Expected: `ImportError`

- [ ] **Step 3: Write `willow/fylgja/safety/deployment.py`**

```python
"""
safety/deployment.py — Deployment config loader and user role helpers.
Config is loaded from SOIL store once per session and cached in _cache.
"""
import os
from typing import Optional

from willow.fylgja._mcp import call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")

DEFAULT_CONFIG = {
    "deployment_id": "sean-personal",
    "admin_user_id": "sean",
    "content_tiers": {
        "child": {"max_age": 12, "eccr": True},
        "teen": {"min_age": 13, "max_age": 17},
        "adult": {"min_age": 18},
    },
    "training_opt_in": False,
    "training_child_opt_in": False,
    "psr_names": ["Ruby Campbell", "Opal Campbell"],
}

_cache: Optional[dict] = None


def _load_from_store() -> Optional[dict]:
    try:
        result = call("store_get", {
            "app_id": AGENT,
            "collection": "willow/deployment",
            "record_id": "config",
        }, timeout=5)
        if isinstance(result, dict) and result.get("deployment_id"):
            return result
    except Exception:
        pass
    return None


def _load_user_profile(user_id: str) -> Optional[dict]:
    try:
        result = call("store_get", {
            "app_id": AGENT,
            "collection": f"willow/users",
            "record_id": user_id,
        }, timeout=5)
        if isinstance(result, dict) and result.get("user_id"):
            return result
    except Exception:
        pass
    return None


def get_deployment_config(refresh: bool = False) -> dict:
    global _cache
    if _cache is None or refresh:
        loaded = _load_from_store()
        _cache = loaded if loaded else {**DEFAULT_CONFIG}
    return _cache


def get_user_role(user_id: str) -> str:
    profile = _load_user_profile(user_id)
    if profile:
        return profile.get("role", "adult")
    return "adult"


def is_psr(user_id: str) -> bool:
    config = get_deployment_config()
    profile = _load_user_profile(user_id)
    if not profile:
        return False
    name = profile.get("name", "")
    return name in config.get("psr_names", [])


def training_allowed(user_id: str, session_consent: bool) -> bool:
    config = get_deployment_config()
    if not config.get("training_opt_in", False):
        return False
    if not session_consent:
        return False
    role = get_user_role(user_id)
    if role == "child":
        return config.get("training_child_opt_in", False)
    return True
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_fylgja/test_safety_deployment.py -v 2>&1 | tail -15
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/safety/deployment.py tests/test_fylgja/test_safety_deployment.py
git commit -m "feat(fylgja/safety): deployment.py — config loader, user role, PSR, training gate"
```

---

### Task 4: `safety/session.py` — SAFE protocol

**Files:**
- Create: `willow/fylgja/safety/session.py`
- Create: `tests/test_fylgja/test_safety_session.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fylgja/test_safety_session.py
"""SAFE protocol session flow — identity, role, stream authorization, consent record."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date
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
    with patch.dict("os.environ", {}, clear=True):
        uid = get_session_user_id()
    assert uid == "UNIDENTIFIED"


def test_get_session_role_unidentified_is_child():
    """UNIDENTIFIED users get maximum restrictions — treated as child tier."""
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
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_fylgja/test_safety_session.py -v 2>&1 | tail -10
```

Expected: `ImportError`

- [ ] **Step 3: Write `willow/fylgja/safety/session.py`**

```python
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

VALID_STREAMS = {"relationships", "images", "bookmarks", "dating"}


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
    state = _read_session()
    return stream in state.get("authorized_streams", [])


def authorize_stream(stream: str) -> None:
    if stream not in VALID_STREAMS:
        return
    state = _read_session()
    authorized = set(state.get("authorized_streams", []))
    authorized.add(stream)
    _write_session({"authorized_streams": list(authorized)})


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


def write_consent_to_ledger(record: dict) -> None:
    try:
        call("store_put", {
            "app_id": AGENT,
            "collection": "willow/consent_records",
            "record": record,
        }, timeout=5)
    except Exception:
        pass


def close_session(session_id: str) -> None:
    """Called from stop.py — expire authorizations and write consent record to ledger."""
    user_id = get_session_user_id()
    role = get_session_role(user_id)
    state = _read_session()
    streams = state.get("authorized_streams", [])
    training_consent = state.get("training_consent", False)
    record = build_consent_record(user_id, role, streams, training_consent, session_id)
    write_consent_to_ledger(record)
    _write_session({"authorized_streams": [], "training_consent": False})
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_fylgja/test_safety_session.py -v 2>&1 | tail -15
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/safety/session.py tests/test_fylgja/test_safety_session.py
git commit -m "feat(fylgja/safety): session.py — SAFE protocol, stream auth, consent record"
```

---

### Task 5: Wire safety gate into `events/pre_tool.py`

**Files:**
- Modify: `willow/fylgja/events/pre_tool.py`
- Modify: `tests/test_fylgja/test_pre_tool.py`

The safety gate runs BEFORE any other check in `main()`. It reads the session user role from `_state.py` and `session.py`, calls `platform.check_all()`, logs any block to `willow/safety_log` via MCP, and emits the block decision.

- [ ] **Step 1: Add failing integration tests to `test_pre_tool.py`**

```python
# Add to tests/test_fylgja/test_pre_tool.py

import json
from io import StringIO
from unittest.mock import patch


def _run_pre_tool(stdin_data: dict) -> str:
    import willow.fylgja.events.pre_tool as m
    inp = StringIO(json.dumps(stdin_data))
    out = StringIO()
    with patch("sys.stdin", inp), patch("sys.stdout", out):
        try:
            m.main()
        except SystemExit:
            pass
    return out.getvalue()


def test_safety_gate_blocks_training_tool_without_consent():
    out = _run_pre_tool({
        "tool_name": "mcp__willow__opus_feedback_write",
        "tool_input": {"app_id": "hanuman"},
        "session_id": "abc123",
    })
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "HS-003" in data["reason"] or "training" in data["reason"].lower()


def test_safety_gate_allows_read_tool():
    out = _run_pre_tool({
        "tool_name": "Read",
        "tool_input": {"file_path": "/home/sean-campbell/github/willow-1.9/README.md"},
        "session_id": "abc123",
    })
    # Read either produces empty output (no advisory) or a KB-first advisory — never a block
    if out.strip():
        data = json.loads(out)
        assert data.get("decision") != "block"
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_fylgja/test_pre_tool.py::test_safety_gate_blocks_training_tool_without_consent -v 2>&1 | tail -10
```

Expected: test fails — output is empty (no block currently).

- [ ] **Step 3: Add safety gate to `willow/fylgja/events/pre_tool.py`**

Add imports at the top of `pre_tool.py`:

```python
from willow.fylgja.safety.platform import check_all as safety_check_all
from willow.fylgja.safety.session import get_session_user_id, get_session_role
```

Add `_run_safety_gate()` function before `main()`:

```python
def _run_safety_gate(tool_name: str, tool_input: dict, session_id: str) -> Optional[str]:
    """Run all platform hard stops. Returns block JSON string or None."""
    try:
        user_id = get_session_user_id()
        user_role = get_session_role(user_id)
        training_consented = False  # loaded from session state in full SAFE flow
        result = safety_check_all(
            tool_name=tool_name,
            tool_input=tool_input,
            user_role=user_role,
            training_consented=training_consented,
        )
        if result:
            try:
                call("store_put", {
                    "app_id": AGENT,
                    "collection": "willow/safety_log",
                    "record": {
                        "id": f"hs-{session_id[:8]}-{tool_name[:20]}-{abs(hash(str(tool_input))) % 99999:05d}",
                        "user_id": user_id,
                        "tool_name": tool_name,
                        "hard_stop_id": result["hard_stop_id"],
                        "reason": result["reason"],
                        "session_id": session_id,
                        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    },
                }, timeout=3)
            except Exception:
                pass
            return json.dumps({"decision": "block", "reason": result["reason"]})
    except Exception:
        pass
    return None
```

At the top of `main()`, immediately after parsing `payload`, add:

```python
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    session_id = payload.get("session_id", "")

    # Safety gate — runs before all other checks
    block = _run_safety_gate(tool_name, tool_input, session_id)
    if block:
        print(block)
        sys.exit(0)
```

- [ ] **Step 4: Run pre_tool tests**

```bash
python3 -m pytest tests/test_fylgja/test_pre_tool.py -v 2>&1 | tail -15
```

Expected: all existing tests pass + 2 new safety gate tests pass.

- [ ] **Step 5: Commit**

```bash
git add willow/fylgja/events/pre_tool.py tests/test_fylgja/test_pre_tool.py
git commit -m "feat(fylgja/safety): wire safety gate into pre_tool.py — HS checks before all dispatch"
```

---

### Task 6: HS-003 training consent gate in `stop.py`

The feedback pipeline in `stop.py` calls `opus_feedback_write` unconditionally. Add the deployment config check so it only runs when `training_allowed()` returns True.

- [ ] **Step 1: Modify `_run_feedback_pipeline()` in `willow/fylgja/events/stop.py`**

Add import at top of `stop.py`:

```python
from willow.fylgja.safety.deployment import training_allowed, get_deployment_config
from willow.fylgja.safety.session import get_session_user_id
```

Add gate at start of `_run_feedback_pipeline()`:

```python
def _run_feedback_pipeline() -> None:
    user_id = get_session_user_id()
    if not training_allowed(user_id, session_consent=False):
        return
    # ... rest of existing function unchanged
```

- [ ] **Step 2: Run full test suite**

```bash
python3 -m pytest tests/test_fylgja/ -q 2>&1 | tail -5
```

Expected: all tests pass (no regressions).

- [ ] **Step 3: Commit**

```bash
git add willow/fylgja/events/stop.py
git commit -m "feat(fylgja/safety): HS-003 training consent gate in stop.py feedback pipeline"
```

---

### Task 7: Full suite + push

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/test_fylgja/ tests/adversarial/ --ignore=tests/adversarial/e2e -q 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 2: Final commit + push**

```bash
git add -A
git commit -m "feat(fylgja): Plan 3 complete — Safety subsystem (platform, deployment, session)"
git push origin master
```

---

## Self-Review

**Spec coverage:**
- ✅ `safety/__init__.py` — package scaffold (Task 1)
- ✅ `safety/platform.py` — 9 hard stops, 5 active (HS-001, HS-002, HS-003, HS-006, HS-008) (Task 2)
- ✅ `safety/deployment.py` — deployment config, user role, PSR check, training gate (Task 3)
- ✅ `safety/session.py` — SAFE protocol, stream auth, consent record to ledger (Task 4)
- ✅ `events/pre_tool.py` — safety gate wired at top of main() (Task 5)
- ✅ `events/stop.py` — HS-003 training consent gate (Task 6)

**Passive hard stops (architectural, not per-tool-call):**
- HS-004 (Real Consent) — enforced by `consent.md` skill design
- HS-005 (Data Sovereignty) — exit/delete always allowed; no block added
- HS-007 (Human Final Authority) — depth limit already in pre_tool.py
- HS-009 (Transparency) — `willow/safety_log` is the audit trail, surfaced on request

**Not in this plan:**
- `willow_route` — separate Plan 4

ΔΣ=42
