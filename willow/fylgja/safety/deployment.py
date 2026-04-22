"""
safety/deployment.py — Deployment config loader and user role helpers.
Config is loaded from SOIL store once per session and cached in _cache.
"""
import os
from typing import Optional

from willow.fylgja._mcp import call

AGENT = os.environ.get("WILLOW_AGENT_NAME", "hanuman")

DEFAULT_CONFIG: dict = {
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
            "collection": "willow/users",
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
    return profile.get("name", "") in config.get("psr_names", [])


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
