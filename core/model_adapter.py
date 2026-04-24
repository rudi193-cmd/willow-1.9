# core/model_adapter.py — Pluggable model interface. b17: MODL1  ΔΣ=42
from __future__ import annotations
import json
import urllib.request
import urllib.error
from abc import ABC, abstractmethod


class ModelAdapter(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def chat(self, messages: list[dict], model: str | None = None) -> str: ...

    @abstractmethod
    def available_models(self) -> list[str]: ...

    @abstractmethod
    def health(self) -> bool: ...


class OllamaAdapter(ModelAdapter):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "yggdrasil:v9"):
        self._base = base_url.rstrip("/")
        self._model = model

    @property
    def provider_name(self) -> str:
        return "ollama"

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        payload = json.dumps({"model": model or self._model, "messages": messages, "stream": False}).encode()
        req = urllib.request.Request(f"{self._base}/api/chat", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Ollama chat failed: {e}") from e

    def available_models(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self._base}/api/tags", timeout=5) as resp:
                return [m["name"] for m in json.loads(resp.read()).get("models", [])]
        except Exception:
            return []

    def health(self) -> bool:
        try:
            urllib.request.urlopen(f"{self._base}/api/tags", timeout=3)
            return True
        except Exception:
            return False


class AnthropicAdapter(ModelAdapter):
    _API_URL = "https://api.anthropic.com/v1/messages"
    _DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL):
        self._key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        payload = json.dumps({"model": model or self._model, "max_tokens": 4096, "messages": messages}).encode()
        req = urllib.request.Request(self._API_URL, data=payload,
            headers={"Content-Type": "application/json", "x-api-key": self._key,
                     "anthropic-version": "2023-06-01"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())["content"][0]["text"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Anthropic API error {e.code}: {e.read().decode()}") from e
        except Exception as e:
            raise RuntimeError(f"Anthropic chat failed: {e}") from e

    def available_models(self) -> list[str]:
        return ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]

    def health(self) -> bool:
        try:
            self.chat([{"role": "user", "content": "ping"}], model="claude-haiku-4-5-20251001")
            return True
        except Exception:
            return False


class GroqAdapter(ModelAdapter):
    _API_URL = "https://api.groq.com/openai/v1/chat/completions"
    _DEFAULT_MODEL = "llama-3.1-8b-instant"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL):
        self._key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return "groq"

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        payload = json.dumps({"model": model or self._model, "messages": messages}).encode()
        req = urllib.request.Request(self._API_URL, data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Groq API error {e.code}: {e.read().decode()}") from e
        except Exception as e:
            raise RuntimeError(f"Groq chat failed: {e}") from e

    def available_models(self) -> list[str]:
        return ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "mixtral-8x7b-32768"]

    def health(self) -> bool:
        try:
            self.chat([{"role": "user", "content": "ping"}])
            return True
        except Exception:
            return False


class XaiAdapter(ModelAdapter):
    _API_URL = "https://api.x.ai/v1/chat/completions"
    _DEFAULT_MODEL = "grok-beta"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL):
        self._key = api_key
        self._model = model

    @property
    def provider_name(self) -> str:
        return "xai"

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        payload = json.dumps({"model": model or self._model, "messages": messages}).encode()
        req = urllib.request.Request(self._API_URL, data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"xAI chat failed: {e}") from e

    def available_models(self) -> list[str]:
        return ["grok-beta", "grok-2"]

    def health(self) -> bool:
        try:
            self.chat([{"role": "user", "content": "ping"}])
            return True
        except Exception:
            return False


class OpenAICompatibleAdapter(ModelAdapter):
    def __init__(self, api_key: str, base_url: str, model: str = "default"):
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._model = model

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        payload = json.dumps({"model": model or self._model, "messages": messages}).encode()
        req = urllib.request.Request(f"{self._base}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible chat failed: {e}") from e

    def available_models(self) -> list[str]:
        try:
            req = urllib.request.Request(f"{self._base}/v1/models",
                headers={"Authorization": f"Bearer {self._key}"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return [m["id"] for m in json.loads(resp.read()).get("data", [])]
        except Exception:
            return []

    def health(self) -> bool:
        try:
            urllib.request.urlopen(f"{self._base}/v1/models", timeout=3)
            return True
        except Exception:
            return False


def get_adapter(provider: str, **kwargs) -> ModelAdapter:
    """Factory — returns a ModelAdapter for the given provider name."""
    _map = {
        "ollama":            OllamaAdapter,
        "anthropic":         AnthropicAdapter,
        "groq":              GroqAdapter,
        "xai":               XaiAdapter,
        "openai_compatible": OpenAICompatibleAdapter,
    }
    provider = provider.lower()
    if provider not in _map:
        raise ValueError(f"Unknown provider: {provider!r}. Available: {', '.join(_map)}")
    return _map[provider](**kwargs)
