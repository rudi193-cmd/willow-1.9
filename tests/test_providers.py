"""Tests for core/providers.py — provider registry. b17: PROV1 ΔΣ=42"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    return ws.WillowStore()


def test_get_providers_returns_defaults_when_store_empty(store):
    from core.providers import get_providers
    providers = get_providers(store)
    assert len(providers) == 4
    names = {p["name"] for p in providers}
    assert names == {"ollama", "anthropic", "openai", "gemini"}


def test_ollama_is_enabled_by_default(store):
    from core.providers import get_providers
    providers = get_providers(store)
    ollama = next(p for p in providers if p["name"] == "ollama")
    assert ollama["enabled"] is True


def test_cloud_providers_are_disabled_by_default(store):
    from core.providers import get_providers
    providers = get_providers(store)
    for p in providers:
        if not p.get("local"):
            assert p["enabled"] is False, f"{p['name']} should be disabled by default"


def test_enable_provider_sets_enabled_true(store):
    from core.providers import enable_provider, get_providers
    enable_provider(store, "anthropic", api_key="sk-test-12345678")
    providers = get_providers(store)
    anthropic = next(p for p in providers if p["name"] == "anthropic")
    assert anthropic["enabled"] is True
    assert anthropic["api_key"] == "sk-test-12345678"


def test_disable_provider_sets_enabled_false(store):
    from core.providers import enable_provider, disable_provider, get_providers
    enable_provider(store, "openai", api_key="sk-openai-test")
    disable_provider(store, "openai")
    providers = get_providers(store)
    openai = next(p for p in providers if p["name"] == "openai")
    assert openai["enabled"] is False


def test_disable_ollama_raises(store):
    from core.providers import disable_provider
    with pytest.raises(ValueError, match="Ollama"):
        disable_provider(store, "ollama")


def test_build_litellm_config_includes_only_enabled_providers(store, monkeypatch):
    import core.providers as prov
    monkeypatch.setattr(prov, "_ollama_reachable", lambda *a, **kw: True)
    from core.providers import build_litellm_config
    config = build_litellm_config(store)
    model_names = [m["model_name"] for m in config["model_list"]]
    # Ollama models should be present
    assert "yggdrasil:v9" in model_names
    assert "qwen2.5:3b" in model_names
    # Cloud models should NOT be present
    assert "claude-sonnet-4-6" not in model_names
    assert "gpt-4o" not in model_names


def test_build_litellm_config_adds_cloud_when_enabled(store):
    from core.providers import build_litellm_config, enable_provider
    enable_provider(store, "anthropic", api_key="sk-ant-test")
    config = build_litellm_config(store)
    model_names = [m["model_name"] for m in config["model_list"]]
    assert "claude-sonnet-4-6" in model_names
    assert "claude-haiku-4-5" in model_names


def test_build_litellm_config_ollama_uses_correct_prefix(store, monkeypatch):
    import core.providers as prov
    monkeypatch.setattr(prov, "_ollama_reachable", lambda *a, **kw: True)
    from core.providers import build_litellm_config
    config = build_litellm_config(store)
    ollama_entries = [m for m in config["model_list"] if "yggdrasil" in m["model_name"]]
    assert len(ollama_entries) == 1
    params = ollama_entries[0]["litellm_params"]
    assert params["model"] == "ollama/yggdrasil:v9"
    assert params["api_base"] == "http://localhost:11434"


def test_get_active_models_returns_only_enabled(store):
    from core.providers import get_active_models, enable_provider
    models = get_active_models(store)
    # Only ollama models by default
    assert "yggdrasil:v9" in models
    assert "claude-sonnet-4-6" not in models
    # Enable anthropic and recheck
    enable_provider(store, "anthropic", api_key="sk-ant-test")
    models2 = get_active_models(store)
    assert "claude-sonnet-4-6" in models2


def test_mask_key_truncates_correctly():
    from core.providers import _mask_key
    assert _mask_key("sk-ant-12345678abcdef") == "sk-ant-1***"
    assert _mask_key(None) is None
    assert _mask_key("short") == "short***"
