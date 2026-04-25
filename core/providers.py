#!/usr/bin/env python3
"""
providers.py — Willow provider registry. b17: PROV1 ΔΣ=42

Local-first: Ollama is the default provider when available. Cloud keys are
user-controlled addons. Provider state persists in the SOIL store.
Ollama being enabled means the user *wants* it — not that it's installed.
"""
import urllib.request
from typing import Optional


def _ollama_reachable(base_url: str = "http://localhost:11434") -> bool:
    try:
        urllib.request.urlopen(f"{base_url}/api/tags", timeout=2)
        return True
    except Exception:
        return False

_COLLECTION = "willow/providers"

DEFAULTS = [
    {
        "id": "ollama",
        "name": "ollama",
        "enabled": True,
        "base_url": "http://localhost:11434",
        "models": ["yggdrasil:v9", "qwen2.5:3b"],
        "local": True,
    },
    {
        "id": "anthropic",
        "name": "anthropic",
        "enabled": False,
        "api_key": None,
        "models": ["claude-sonnet-4-6", "claude-haiku-4-5"],
        "local": False,
    },
    {
        "id": "openai",
        "name": "openai",
        "enabled": False,
        "api_key": None,
        "models": ["gpt-4o", "gpt-4o-mini"],
        "local": False,
    },
    {
        "id": "gemini",
        "name": "gemini",
        "enabled": False,
        "api_key": None,
        "models": ["gemini-2.0-flash", "gemini-2.5-pro"],
        "local": False,
    },
]


def _ensure_defaults(store) -> None:
    """Write defaults if the collection is empty."""
    existing = store.list(_COLLECTION)
    if not existing:
        for p in DEFAULTS:
            store.put(_COLLECTION, p)


def get_providers(store) -> list:
    """Return all providers with their enabled state."""
    _ensure_defaults(store)
    return store.list(_COLLECTION)


def enable_provider(store, name: str, api_key: Optional[str] = None) -> None:
    """Turn on a cloud provider. Ollama is always on — this is a no-op for it."""
    _ensure_defaults(store)
    provider = store.get(_COLLECTION, name)
    if provider is None:
        raise ValueError(f"Unknown provider: {name!r}")
    provider["enabled"] = True
    if api_key:
        provider["api_key"] = api_key
    store.put(_COLLECTION, provider)


def disable_provider(store, name: str) -> None:
    """Turn off a provider. Ollama cannot be disabled — it is always on."""
    if name == "ollama":
        raise ValueError("Ollama is the default local provider and cannot be disabled.")
    _ensure_defaults(store)
    provider = store.get(_COLLECTION, name)
    if provider is None:
        raise ValueError(f"Unknown provider: {name!r}")
    provider["enabled"] = False
    store.put(_COLLECTION, provider)


def get_active_models(store) -> list:
    """Return list of currently active model identifiers."""
    providers = get_providers(store)
    models = []
    for p in providers:
        if p.get("enabled"):
            models.extend(p.get("models", []))
    return models


def _mask_key(key: Optional[str]) -> Optional[str]:
    """Show first 8 chars + *** for display. Returns None if key is None."""
    if not key:
        return None
    if len(key) <= 8:
        return key + "***"
    return key[:8] + "***"


def build_litellm_config(store) -> dict:
    """Generate LiteLLM config dict from active providers.

    Returns a dict suitable for yaml.dump() that LiteLLM can consume.
    """
    providers = get_providers(store)
    model_list = []

    for p in providers:
        if not p.get("enabled"):
            continue

        name = p["name"]
        models = p.get("models", [])
        api_key = p.get("api_key")

        if name == "ollama":
            base_url = p.get("base_url", "http://localhost:11434")
            if not _ollama_reachable(base_url):
                continue  # Ollama enabled but not running — skip, don't error
            for model in models:
                model_list.append({
                    "model_name": model,
                    "litellm_params": {
                        "model": f"ollama/{model}",
                        "api_base": base_url,
                    },
                })
        elif name == "anthropic":
            for model in models:
                entry: dict = {
                    "model_name": model,
                    "litellm_params": {
                        "model": f"anthropic/{model}",
                    },
                }
                if api_key:
                    entry["litellm_params"]["api_key"] = api_key
                model_list.append(entry)
        elif name == "openai":
            for model in models:
                entry = {
                    "model_name": model,
                    "litellm_params": {
                        "model": model,
                    },
                }
                if api_key:
                    entry["litellm_params"]["api_key"] = api_key
                model_list.append(entry)
        elif name == "gemini":
            for model in models:
                entry = {
                    "model_name": model,
                    "litellm_params": {
                        "model": f"gemini/{model}",
                    },
                }
                if api_key:
                    entry["litellm_params"]["api_key"] = api_key
                model_list.append(entry)

    return {"model_list": model_list}
