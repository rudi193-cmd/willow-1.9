"""tests/test_model_adapter.py — model adapter interface tests."""
import pytest
from core.model_adapter import (
    ModelAdapter, OllamaAdapter, AnthropicAdapter, GroqAdapter,
    XaiAdapter, OpenAICompatibleAdapter, get_adapter,
)


def test_ollama_implements_interface():
    a = OllamaAdapter()
    assert hasattr(a, "chat") and hasattr(a, "available_models") and hasattr(a, "health")
    assert a.provider_name == "ollama"


def test_ollama_health_false_when_unreachable():
    assert OllamaAdapter(base_url="http://localhost:19999").health() is False


def test_anthropic_provider_name():
    assert AnthropicAdapter(api_key="sk-ant-test").provider_name == "anthropic"


def test_groq_provider_name():
    assert GroqAdapter(api_key="gsk_test").provider_name == "groq"


def test_xai_provider_name():
    assert XaiAdapter(api_key="xai-test").provider_name == "xai"


def test_openai_compat_provider_name():
    a = OpenAICompatibleAdapter(api_key="test", base_url="http://localhost:8080")
    assert a.provider_name == "openai_compatible"


def test_get_adapter_ollama():
    assert isinstance(get_adapter("ollama"), OllamaAdapter)


def test_get_adapter_anthropic():
    assert isinstance(get_adapter("anthropic", api_key="sk-ant-test"), AnthropicAdapter)


def test_get_adapter_groq():
    assert isinstance(get_adapter("groq", api_key="gsk_test"), GroqAdapter)


def test_get_adapter_xai():
    assert isinstance(get_adapter("xai", api_key="xai-test"), XaiAdapter)


def test_get_adapter_openai_compatible():
    a = get_adapter("openai_compatible", api_key="test", base_url="http://localhost:8080")
    assert isinstance(a, OpenAICompatibleAdapter)


def test_get_adapter_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_adapter("nonexistent")
