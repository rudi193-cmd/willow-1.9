"""
safety/platform.py — Nine platform hard stops.
Architecture, not policy. No deployment can override.
Called from events/pre_tool.py before every tool dispatch.
b17: SAFE1
"""
import re
from pathlib import Path
from typing import Optional

# Training pipeline tools — gated by HS-001 (child) and HS-003 (consent)
_TRAINING_TOOLS = frozenset({
    "mcp__willow__opus_feedback_write",
    "mcp__willow__opus_ingest",
    "mcp__willow__opus_feedback",
})

# Mass harm content patterns — HS-002
_HARM_PATTERNS = [
    r"\b(synthesize|manufacture|produce)\s+(sarin|vx|novichok|mustard.?gas|nerve.?agent)",
    r"\b(bioweapon|biological.?weapon|weaponize\s+pathogen)",
    r"\b(csam|child\s+sexual\s+abuse\s+material)",
    r"\b(mass.?casualty|mass.?shooting|bomb.?making)\s+(instruction|guide|step|how.?to)",
]
_HARM_RE = re.compile("|".join(_HARM_PATTERNS), re.IGNORECASE)

# Surveillance collections — HS-006
_SURVEILLANCE_COLLECTIONS = frozenset({
    "willow/behavioral_profiles",
    "willow/tracking",
    "willow/surveillance",
})

# Protected config paths — HS-008 (computed at import time, not hardcoded)
_PROTECTED_PATHS = frozenset({
    str(Path.home() / ".claude" / "settings.json"),
    str(Path.home() / ".claude" / "settings.local.json"),
})


def _block(hard_stop_id: str, reason: str) -> dict:
    return {"decision": "block", "hard_stop_id": hard_stop_id, "reason": reason}


def _check_hs001(tool_name: str, user_role: str) -> Optional[dict]:
    if user_role == "child" and tool_name in _TRAINING_TOOLS:
        return _block(
            "HS-001",
            "Training pipeline access is prohibited for CHILD-tier users. "
            "This is a platform hard stop — no guardian authorization can override it.",
        )
    return None


def _check_hs002(tool_input: dict) -> Optional[dict]:
    text = " ".join(str(v) for v in tool_input.values() if isinstance(v, (str, int, float)))
    if _HARM_RE.search(text):
        return _block(
            "HS-002",
            "This request matches a mass harm enablement pattern and cannot be processed. "
            "If this is a false positive in a security research context, contact Sean directly.",
        )
    return None


def _check_hs003(tool_name: str, training_consented: bool) -> Optional[dict]:
    if tool_name in _TRAINING_TOOLS and not training_consented:
        return _block(
            "HS-003",
            "Training pipeline write blocked — no training consent granted this session. "
            "Sean must explicitly authorize training data collection at session start.",
        )
    return None


def _check_hs006(tool_name: str, tool_input: dict) -> Optional[dict]:
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


def check_all(
    tool_name: str,
    tool_input: dict,
    user_role: str = "adult",
    training_consented: bool = False,
) -> Optional[dict]:
    """Run all active hard stops. Returns a block dict if any fires, else None. HS-001 first."""
    for check in (
        lambda: _check_hs001(tool_name, user_role),
        lambda: _check_hs002(tool_input),
        lambda: _check_hs003(tool_name, training_consented),
        lambda: _check_hs006(tool_name, tool_input),
        lambda: _check_hs008(tool_name, tool_input),
    ):
        result = check()
        if result:
            return result
    return None


class HardStop:
    CHILD_PRIMACY = "HS-001"
    NO_MASS_HARM = "HS-002"
    TRAINING_CONSENT = "HS-003"
    REAL_CONSENT = "HS-004"
    DATA_SOVEREIGNTY = "HS-005"
    NO_SURVEILLANCE = "HS-006"
    HUMAN_FINAL_AUTHORITY = "HS-007"
    NO_CAPTURE = "HS-008"
    TRANSPARENCY = "HS-009"
