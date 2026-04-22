"""Platform hard stop tests — each active stop triggers correctly, clean calls pass through."""
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


def test_hs001_allows_training_write_for_adult_with_consent():
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

def test_hs008_blocks_settings_overwrite():
    from pathlib import Path
    settings_path = str(Path.home() / ".claude" / "settings.json")
    result = check_all(
        tool_name="Write",
        tool_input={"file_path": settings_path},
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


def test_block_result_has_required_fields():
    result = check_all(
        tool_name="mcp__willow__opus_feedback_write",
        tool_input={"app_id": "hanuman"},
        user_role="child",
        training_consented=False,
    )
    assert result is not None
    for field in ("decision", "reason", "hard_stop_id"):
        assert field in result, f"Missing field: {field}"
