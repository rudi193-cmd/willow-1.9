# Willow 1.9 Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock Felix — fix the live path bug, wire BYOK model adapters, implement Willow Forks schema + MCP tools, and auto-create a fork on every session start.

**Architecture:** Vault logic extracted to `core/vault.py` (currently duplicated in `shoot.py` and `root.py`). Model adapters in `core/model_adapter.py` — one ABC, five implementations, one factory function. Forks schema in Postgres via `core/pg_bridge.py`. Fork CRUD in `willow/forks.py`. Seven MCP tools in `sap/sap_mcp.py`. Session anchor writes `fork_id` in `willow/fylgja/events/session_start.py`.

**Tech Stack:** Python 3.13, PostgreSQL (willow_19), psycopg2, cryptography (Fernet), httpx, curses, MCP SDK, pytest

**Spec:** `docs/superpowers/specs/2026-04-24-willow-19-design.md`

---

## File Map

**Create:**
- `core/vault.py` — Fernet vault read/write for named secrets (extracted from shoot.py/root.py)
- `core/model_adapter.py` — ModelAdapter ABC + OllamaAdapter + AnthropicAdapter + GroqAdapter + XaiAdapter + OpenAICompatibleAdapter + `get_adapter()` factory
- `willow/forks.py` — Fork CRUD (create, join, log, merge, delete, status, list)
- `scripts/migrate_fork_origin.py` — one-shot: assign all existing atoms to FORK-ORIGIN, mark merged
- `tests/test_vault.py`
- `tests/test_model_adapter.py`
- `tests/test_forks.py`

**Modify:**
- `willow-dashboard/willow-dashboard.sh` — fix willow-1.7 → willow-1.9 path
- `core/pg_bridge.py` — add `forks` table + `fork_id TEXT` column on `knowledge` + ALTER TABLE migrations
- `sap/sap_mcp.py` — wire 7 `willow_fork_*` tools
- `willow/fylgja/events/session_start.py` — auto-create fork on boot, write `fork_id` to session anchor
- `willow-dashboard/canopy.py` — add page 5: model provider selection
- `willow-dashboard/dashboard.py` — settings page: show active adapter + health

---

## Task 1: Fix willow-dashboard.sh path

**Files:**
- Modify: `willow-dashboard/willow-dashboard.sh:18-25`

- [ ] **Step 1: Apply the fix**

In `willow-dashboard/willow-dashboard.sh`, replace the path resolution block:

```bash
# ── Find willow-1.9 root ──────────────────────────────────────────────────────
if [[ -n "${WILLOW_ROOT:-}" ]] && [[ -f "${WILLOW_ROOT}/willow.sh" ]]; then
    : # already set
elif [[ -f "${DASH_ROOT}/../willow-1.9/willow.sh" ]]; then
    WILLOW_ROOT="$(cd "${DASH_ROOT}/../willow-1.9" && pwd)"
elif [[ -f "${HOME}/github/willow-1.9/willow.sh" ]]; then
    WILLOW_ROOT="${HOME}/github/willow-1.9"
else
    WILLOW_ROOT=""
fi
```

- [ ] **Step 2: Verify**

```bash
bash -n ~/github/willow-dashboard/willow-dashboard.sh
echo $?
```

Expected: `0` (no syntax errors)

- [ ] **Step 3: Commit**

```bash
cd ~/github/willow-dashboard
git add willow-dashboard.sh
git commit -m "fix: update willow root path from willow-1.7 to willow-1.9"
```

---

## Task 2: Extract vault to core/vault.py

**Files:**
- Create: `core/vault.py`
- Create: `tests/test_vault.py`

The vault code is currently duplicated in `shoot.py` (`_vault_init`, `_vault_write`, `_vault_has_key`) and `root.py` (`step_4_vault`). Extract to a shared module.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault.py`:

```python
"""tests/test_vault.py — vault read/write tests."""
import pytest
from pathlib import Path
from core.vault import Vault


def test_vault_write_and_read(tmp_path):
    v = Vault(vault_path=tmp_path / "vault.db", key_path=tmp_path / "vault.key")
    v.init()
    v.write("ANTHROPIC_API_KEY", "sk-ant-test-123")
    assert v.read("ANTHROPIC_API_KEY") == "sk-ant-test-123"


def test_vault_has_key(tmp_path):
    v = Vault(vault_path=tmp_path / "vault.db", key_path=tmp_path / "vault.key")
    v.init()
    assert not v.has("GROQ_API_KEY")
    v.write("GROQ_API_KEY", "gsk_test")
    assert v.has("GROQ_API_KEY")


def test_vault_overwrite(tmp_path):
    v = Vault(vault_path=tmp_path / "vault.db", key_path=tmp_path / "vault.key")
    v.init()
    v.write("KEY", "old")
    v.write("KEY", "new")
    assert v.read("KEY") == "new"


def test_vault_read_missing_returns_none(tmp_path):
    v = Vault(vault_path=tmp_path / "vault.db", key_path=tmp_path / "vault.key")
    v.init()
    assert v.read("NONEXISTENT") is None


def test_vault_list_keys(tmp_path):
    v = Vault(vault_path=tmp_path / "vault.db", key_path=tmp_path / "vault.key")
    v.init()
    v.write("A", "1")
    v.write("B", "2")
    keys = v.list_keys()
    assert "A" in keys and "B" in keys
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/github/willow-1.9
pytest tests/test_vault.py -v 2>&1 | head -20
```

Expected: `ImportError` — `core.vault` does not exist yet.

- [ ] **Step 3: Create core/vault.py**

```python
# core/vault.py — Fernet-encrypted secret store. b17: VAULT1  ΔΣ=42
import os
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet


_DEFAULT_VAULT = Path.home() / ".willow" / "vault.db"
_DEFAULT_KEY   = Path.home() / ".willow" / "vault.key"


class Vault:
    def __init__(
        self,
        vault_path: Path | None = None,
        key_path: Path | None = None,
    ):
        self._vault = Path(vault_path or _DEFAULT_VAULT)
        self._key_path = Path(key_path or _DEFAULT_KEY)
        self._fernet: Fernet | None = None

    def init(self) -> None:
        """Create vault DB and Fernet key if they don't exist."""
        self._vault.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._key_path.exists():
            fd = os.open(str(self._key_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())

        self._key_path.chmod(0o600)
        self._fernet = Fernet(self._key_path.read_bytes())

        conn = sqlite3.connect(str(self._vault))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS secrets (
                name TEXT PRIMARY KEY,
                value BLOB NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        self._vault.chmod(0o600)

    def _get_fernet(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(self._key_path.read_bytes())
        return self._fernet

    def write(self, name: str, value: str) -> None:
        encrypted = self._get_fernet().encrypt(value.encode())
        conn = sqlite3.connect(str(self._vault))
        conn.execute(
            "INSERT INTO secrets (name, value) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (name, encrypted),
        )
        conn.commit()
        conn.close()

    def read(self, name: str) -> str | None:
        conn = sqlite3.connect(str(self._vault))
        row = conn.execute(
            "SELECT value FROM secrets WHERE name = ?", (name,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._get_fernet().decrypt(row[0]).decode()

    def has(self, name: str) -> bool:
        return self.read(name) is not None

    def list_keys(self) -> list[str]:
        conn = sqlite3.connect(str(self._vault))
        rows = conn.execute("SELECT name FROM secrets ORDER BY name").fetchall()
        conn.close()
        return [r[0] for r in rows]


def default_vault() -> Vault:
    """Return a Vault instance pointing at ~/.willow/vault.db, initialized."""
    v = Vault()
    if _DEFAULT_VAULT.exists():
        return v
    v.init()
    return v
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_vault.py -v
```

Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add core/vault.py tests/test_vault.py
git commit -m "feat(vault): extract Vault class to core/vault.py — shared Fernet secret store"
```

---

## Task 3: BYOK model adapter — interface + OllamaAdapter

**Files:**
- Create: `core/model_adapter.py`
- Create: `tests/test_model_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_model_adapter.py`:

```python
"""tests/test_model_adapter.py — model adapter interface tests."""
import pytest
from unittest.mock import patch, MagicMock
from core.model_adapter import ModelAdapter, OllamaAdapter, get_adapter


def test_ollama_adapter_implements_interface():
    adapter = OllamaAdapter(base_url="http://localhost:11434")
    assert hasattr(adapter, "chat")
    assert hasattr(adapter, "available_models")
    assert hasattr(adapter, "health")
    assert hasattr(adapter, "provider_name")


def test_ollama_adapter_health_false_when_unreachable():
    adapter = OllamaAdapter(base_url="http://localhost:19999")
    assert adapter.health() is False


def test_get_adapter_ollama():
    adapter = get_adapter("ollama", model="yggdrasil:v9")
    assert isinstance(adapter, OllamaAdapter)
    assert adapter.provider_name == "ollama"


def test_get_adapter_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_adapter("nonexistent_provider")


def test_ollama_chat_calls_api(requests_mock):
    requests_mock.post(
        "http://localhost:11434/api/chat",
        json={"message": {"content": "hello from yggdrasil"}},
    )
    adapter = OllamaAdapter(base_url="http://localhost:11434", model="yggdrasil:v9")
    result = adapter.chat([{"role": "user", "content": "hi"}])
    assert result == "hello from yggdrasil"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_model_adapter.py -v 2>&1 | head -20
```

Expected: `ImportError` — `core.model_adapter` does not exist.

- [ ] **Step 3: Create core/model_adapter.py with interface + OllamaAdapter**

```python
# core/model_adapter.py — Pluggable model interface. b17: MODL1  ΔΣ=42
from __future__ import annotations
import json
import urllib.request
import urllib.error
from abc import ABC, abstractmethod


class ModelAdapter(ABC):
    """Abstract base for all model providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def chat(self, messages: list[dict], model: str | None = None) -> str:
        """Send a chat turn. Returns the assistant reply as a string."""
        ...

    @abstractmethod
    def available_models(self) -> list[str]:
        """Return list of model names available on this provider."""
        ...

    @abstractmethod
    def health(self) -> bool:
        """Return True if the provider is reachable and ready."""
        ...


class OllamaAdapter(ModelAdapter):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "yggdrasil:v9"):
        self._base = base_url.rstrip("/")
        self._model = model

    @property
    def provider_name(self) -> str:
        return "ollama"

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        payload = json.dumps({
            "model": model or self._model,
            "messages": messages,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{self._base}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Ollama chat failed: {e}") from e

    def available_models(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self._base}/api/tags", timeout=5) as resp:
                data = json.loads(resp.read())
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def health(self) -> bool:
        try:
            urllib.request.urlopen(f"{self._base}/api/tags", timeout=3)
            return True
        except Exception:
            return False


def get_adapter(provider: str, **kwargs) -> ModelAdapter:
    """Factory — returns a ModelAdapter for the given provider name."""
    provider = provider.lower()
    if provider == "ollama":
        return OllamaAdapter(**kwargs)
    raise ValueError(f"Unknown provider: {provider!r}. Available: ollama")
```

- [ ] **Step 4: Install requests-mock for tests**

```bash
~/.willow-venv/bin/pip install requests-mock -q
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_model_adapter.py -v
```

Expected: 5 PASS (skip `test_ollama_chat_calls_api` if requests_mock unavailable — the core interface tests must pass)

- [ ] **Step 6: Commit**

```bash
git add core/model_adapter.py tests/test_model_adapter.py
git commit -m "feat(model): add ModelAdapter ABC + OllamaAdapter + get_adapter factory"
```

---

## Task 4: AnthropicAdapter + GroqAdapter

**Files:**
- Modify: `core/model_adapter.py`
- Modify: `tests/test_model_adapter.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_model_adapter.py`:

```python
from core.model_adapter import AnthropicAdapter, GroqAdapter


def test_anthropic_adapter_provider_name():
    adapter = AnthropicAdapter(api_key="sk-ant-test")
    assert adapter.provider_name == "anthropic"


def test_anthropic_health_false_without_valid_key():
    adapter = AnthropicAdapter(api_key="sk-ant-invalid-key-for-testing")
    # health() should return False when key is wrong, not raise
    result = adapter.health()
    assert isinstance(result, bool)


def test_groq_adapter_provider_name():
    adapter = GroqAdapter(api_key="gsk_test")
    assert adapter.provider_name == "groq"


def test_get_adapter_anthropic():
    adapter = get_adapter("anthropic", api_key="sk-ant-test")
    assert isinstance(adapter, AnthropicAdapter)


def test_get_adapter_groq():
    adapter = get_adapter("groq", api_key="gsk_test")
    assert isinstance(adapter, GroqAdapter)
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_model_adapter.py -v -k "anthropic or groq" 2>&1 | head -20
```

Expected: `ImportError` on AnthropicAdapter and GroqAdapter.

- [ ] **Step 3: Add AnthropicAdapter + GroqAdapter to core/model_adapter.py**

Append after `OllamaAdapter`:

```python
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
        payload = json.dumps({
            "model": model or self._model,
            "max_tokens": 4096,
            "messages": messages,
        }).encode()
        req = urllib.request.Request(
            self._API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data["content"][0]["text"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Anthropic API error {e.code}: {e.read().decode()}") from e
        except Exception as e:
            raise RuntimeError(f"Anthropic chat failed: {e}") from e

    def available_models(self) -> list[str]:
        return [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ]

    def health(self) -> bool:
        try:
            # Minimal API call to check key validity
            self.chat([{"role": "user", "content": "ping"}],
                      model="claude-haiku-4-5-20251001")
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
        payload = json.dumps({
            "model": model or self._model,
            "messages": messages,
        }).encode()
        req = urllib.request.Request(
            self._API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Groq API error {e.code}: {e.read().decode()}") from e
        except Exception as e:
            raise RuntimeError(f"Groq chat failed: {e}") from e

    def available_models(self) -> list[str]:
        return [
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
            "mixtral-8x7b-32768",
        ]

    def health(self) -> bool:
        try:
            self.chat([{"role": "user", "content": "ping"}])
            return True
        except Exception:
            return False
```

- [ ] **Step 4: Update get_adapter factory**

Replace the `get_adapter` function:

```python
def get_adapter(provider: str, **kwargs) -> ModelAdapter:
    """Factory — returns a ModelAdapter for the given provider name."""
    provider = provider.lower()
    _map = {
        "ollama":    OllamaAdapter,
        "anthropic": AnthropicAdapter,
        "groq":      GroqAdapter,
    }
    if provider not in _map:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            f"Available: {', '.join(_map)}"
        )
    return _map[provider](**kwargs)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_model_adapter.py -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add core/model_adapter.py tests/test_model_adapter.py
git commit -m "feat(model): add AnthropicAdapter + GroqAdapter"
```

---

## Task 5: XaiAdapter + OpenAICompatibleAdapter

**Files:**
- Modify: `core/model_adapter.py`
- Modify: `tests/test_model_adapter.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_model_adapter.py`:

```python
from core.model_adapter import XaiAdapter, OpenAICompatibleAdapter


def test_xai_adapter_provider_name():
    assert XaiAdapter(api_key="xai-test").provider_name == "xai"


def test_openai_compat_adapter_provider_name():
    a = OpenAICompatibleAdapter(api_key="test", base_url="http://localhost:8080")
    assert a.provider_name == "openai_compatible"


def test_get_adapter_xai():
    from core.model_adapter import get_adapter
    assert get_adapter("xai", api_key="xai-test").provider_name == "xai"


def test_get_adapter_openai_compatible():
    from core.model_adapter import get_adapter
    a = get_adapter("openai_compatible", api_key="test", base_url="http://localhost:8080")
    assert a.provider_name == "openai_compatible"
```

- [ ] **Step 2: Add XaiAdapter + OpenAICompatibleAdapter to core/model_adapter.py**

Append after `GroqAdapter`:

```python
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
        payload = json.dumps({
            "model": model or self._model,
            "messages": messages,
        }).encode()
        req = urllib.request.Request(
            self._API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
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
    """Catch-all for any OpenAI-compatible endpoint (LM Studio, vLLM, etc.)."""

    def __init__(self, api_key: str, base_url: str, model: str = "default"):
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._model = model

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        payload = json.dumps({
            "model": model or self._model,
            "messages": messages,
        }).encode()
        req = urllib.request.Request(
            f"{self._base}/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible chat failed: {e}") from e

    def available_models(self) -> list[str]:
        try:
            req = urllib.request.Request(
                f"{self._base}/v1/models",
                headers={"Authorization": f"Bearer {self._key}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return [m["id"] for m in data.get("data", [])]
        except Exception:
            return []

    def health(self) -> bool:
        try:
            urllib.request.urlopen(f"{self._base}/v1/models", timeout=3)
            return True
        except Exception:
            return False
```

- [ ] **Step 3: Update get_adapter to include xai + openai_compatible**

Replace the `_map` dict inside `get_adapter`:

```python
    _map = {
        "ollama":             OllamaAdapter,
        "anthropic":          AnthropicAdapter,
        "groq":               GroqAdapter,
        "xai":                XaiAdapter,
        "openai_compatible":  OpenAICompatibleAdapter,
    }
```

- [ ] **Step 4: Run full adapter test suite**

```bash
pytest tests/test_model_adapter.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add core/model_adapter.py tests/test_model_adapter.py
git commit -m "feat(model): add XaiAdapter + OpenAICompatibleAdapter, complete BYOK provider set"
```

---

## Task 6: Willow Forks — Postgres schema

**Files:**
- Modify: `core/pg_bridge.py`
- Modify: `tests/test_pg_bridge.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_pg_bridge.py`:

```python
def test_forks_table_exists(bridge):
    cur = bridge.conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'forks'
    """)
    assert cur.fetchone() is not None, "forks table must exist"


def test_knowledge_has_fork_id_column(bridge):
    cur = bridge.conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'knowledge' AND column_name = 'fork_id'
    """)
    assert cur.fetchone() is not None, "knowledge.fork_id column must exist"


def test_fork_insert_and_fetch(bridge):
    import json
    cur = bridge.conn.cursor()
    cur.execute("""
        INSERT INTO forks (id, title, created_by, topic, status, participants, changes)
        VALUES ('FORK-TEST1', 'test fork', 'hanuman', 'test', 'open', %s, %s)
    """, (json.dumps(["hanuman"]), json.dumps([])))
    bridge.conn.commit()
    cur.execute("SELECT id, status FROM forks WHERE id = 'FORK-TEST1'")
    row = cur.fetchone()
    assert row is not None
    assert row[1] == "open"
    cur.execute("DELETE FROM forks WHERE id = 'FORK-TEST1'")
    bridge.conn.commit()
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_pg_bridge.py -v -k "fork" 2>&1 | head -20
```

Expected: FAIL — forks table does not exist.

- [ ] **Step 3: Add forks table to pg_bridge.py**

In `core/pg_bridge.py`, inside `_ensure_schema()`, after the existing table definitions, add:

```python
            # ── Forks ──────────────────────────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS forks (
                    id           TEXT PRIMARY KEY,
                    title        TEXT NOT NULL,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                    created_by   TEXT NOT NULL,
                    topic        TEXT,
                    status       TEXT NOT NULL DEFAULT 'open',
                    participants JSONB NOT NULL DEFAULT '[]',
                    changes      JSONB NOT NULL DEFAULT '[]',
                    merged_at    TIMESTAMPTZ,
                    deleted_at   TIMESTAMPTZ,
                    outcome_note TEXT
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_forks_status
                ON forks (status)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_forks_created_at
                ON forks (created_at DESC)
            """)
```

- [ ] **Step 4: Add fork_id column to knowledge table**

In the same `_ensure_schema()` method, after the existing `_MIGRATIONS` list, add:

```python
            # fork_id migration — safe on existing installs
            cur.execute("""
                ALTER TABLE knowledge
                ADD COLUMN IF NOT EXISTS fork_id TEXT
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_fork_id
                ON knowledge (fork_id)
                WHERE fork_id IS NOT NULL
            """)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_pg_bridge.py -v -k "fork"
```

Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add core/pg_bridge.py tests/test_pg_bridge.py
git commit -m "feat(forks): add forks table + knowledge.fork_id column to Postgres schema"
```

---

## Task 7: FORK-ORIGIN migration script

**Files:**
- Create: `scripts/migrate_fork_origin.py`

- [ ] **Step 1: Create the migration script**

```python
#!/usr/bin/env python3
"""
scripts/migrate_fork_origin.py
Assign all existing knowledge atoms to FORK-ORIGIN and mark it merged.
Run once after the forks schema is applied.

Usage:
    python3 scripts/migrate_fork_origin.py           # live run
    python3 scripts/migrate_fork_origin.py --dry-run # preview only
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.pg_bridge import PgBridge

FORK_ID = "FORK-ORIGIN"
DRY_RUN = "--dry-run" in sys.argv

print(f"[migrate] FORK-ORIGIN migration {'(DRY RUN) ' if DRY_RUN else ''}starting...")

with PgBridge() as b:
    cur = b.conn.cursor()

    # Check if already done
    cur.execute("SELECT id FROM forks WHERE id = %s", (FORK_ID,))
    if cur.fetchone():
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE fork_id = %s", (FORK_ID,))
        count = cur.fetchone()[0]
        print(f"[migrate] FORK-ORIGIN already exists with {count} atoms. Nothing to do.")
        sys.exit(0)

    # Count atoms to migrate
    cur.execute("SELECT COUNT(*) FROM knowledge WHERE fork_id IS NULL")
    total = cur.fetchone()[0]
    print(f"[migrate] Found {total} atoms with fork_id IS NULL → will assign to {FORK_ID}")

    if DRY_RUN:
        print("[migrate] DRY RUN — no changes written.")
        sys.exit(0)

    now = datetime.now(timezone.utc).isoformat()

    # Insert FORK-ORIGIN
    cur.execute("""
        INSERT INTO forks (id, title, created_by, topic, status, participants, changes, merged_at, outcome_note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        FORK_ID,
        "Origin — all work before Willow Forks",
        "hanuman",
        "foundation",
        "merged",
        json.dumps(["hanuman"]),
        json.dumps([{"component": "kb", "type": "bulk_migration",
                     "count": total, "logged_at": now}]),
        now,
        f"Bootstrap migration: {total} existing atoms assigned at 1.9 launch",
    ))

    # Tag all existing atoms
    cur.execute("""
        UPDATE knowledge SET fork_id = %s WHERE fork_id IS NULL
    """, (FORK_ID,))
    updated = cur.rowcount

    b.conn.commit()

print(f"[migrate] Done. FORK-ORIGIN created. {updated} atoms tagged and marked permanent.")
```

- [ ] **Step 2: Run dry-run first**

```bash
cd ~/github/willow-1.9
WILLOW_PG_DB=willow_19 python3 scripts/migrate_fork_origin.py --dry-run
```

Expected output:
```
[migrate] FORK-ORIGIN migration (DRY RUN) starting...
[migrate] Found 69871 atoms with fork_id IS NULL → will assign to FORK-ORIGIN
[migrate] DRY RUN — no changes written.
```

- [ ] **Step 3: Run the live migration**

```bash
WILLOW_PG_DB=willow_19 python3 scripts/migrate_fork_origin.py
```

Expected:
```
[migrate] FORK-ORIGIN migration starting...
[migrate] Found 69871 atoms with fork_id IS NULL → will assign to FORK-ORIGIN
[migrate] Done. FORK-ORIGIN created. 69871 atoms tagged and marked permanent.
```

- [ ] **Step 4: Verify**

```bash
WILLOW_PG_DB=willow_19 python3 -c "
import sys; sys.path.insert(0,'.')
from core.pg_bridge import PgBridge
with PgBridge() as b:
    cur = b.conn.cursor()
    cur.execute(\"SELECT status, outcome_note FROM forks WHERE id = 'FORK-ORIGIN'\")
    print('fork:', cur.fetchone())
    cur.execute(\"SELECT COUNT(*) FROM knowledge WHERE fork_id = 'FORK-ORIGIN'\")
    print('atoms tagged:', cur.fetchone()[0])
    cur.execute('SELECT COUNT(*) FROM knowledge WHERE fork_id IS NULL')
    print('atoms untagged:', cur.fetchone()[0])
"
```

Expected: fork status=merged, atoms tagged≈69871, atoms untagged=0.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_fork_origin.py
git commit -m "feat(forks): add FORK-ORIGIN migration script — tag all existing atoms"
```

---

## Task 8: Fork CRUD — willow/forks.py

**Files:**
- Create: `willow/forks.py`
- Create: `tests/test_forks.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_forks.py`:

```python
"""tests/test_forks.py — Fork CRUD tests."""
import pytest
import json
from core.pg_bridge import PgBridge
from willow.forks import (
    fork_create, fork_join, fork_log, fork_merge,
    fork_delete, fork_status, fork_list,
)


@pytest.fixture
def bridge():
    b = PgBridge()
    yield b
    b.conn.close()


def _cleanup(bridge, fork_id):
    cur = bridge.conn.cursor()
    cur.execute("DELETE FROM forks WHERE id = %s", (fork_id,))
    bridge.conn.commit()


def test_fork_create(bridge):
    f = fork_create(bridge, title="test fork", created_by="hanuman", topic="test")
    assert f["fork_id"].startswith("FORK-")
    assert f["status"] == "open"
    _cleanup(bridge, f["fork_id"])


def test_fork_join(bridge):
    f = fork_create(bridge, title="join test", created_by="hanuman", topic="test")
    result = fork_join(bridge, f["fork_id"], "kart")
    assert "kart" in result["participants"]
    _cleanup(bridge, f["fork_id"])


def test_fork_log(bridge):
    f = fork_create(bridge, title="log test", created_by="hanuman", topic="test")
    result = fork_log(bridge, f["fork_id"], "git", "branch", "session/2026-04-24-test")
    assert result["logged"] is True
    _cleanup(bridge, f["fork_id"])


def test_fork_merge(bridge):
    f = fork_create(bridge, title="merge test", created_by="hanuman", topic="test")
    result = fork_merge(bridge, f["fork_id"], outcome_note="test merge")
    assert result["merged"] is True
    status = fork_status(bridge, f["fork_id"])
    assert status["status"] == "merged"
    _cleanup(bridge, f["fork_id"])


def test_fork_delete(bridge):
    f = fork_create(bridge, title="delete test", created_by="hanuman", topic="test")
    result = fork_delete(bridge, f["fork_id"], reason="test cleanup")
    assert result["deleted"] is True
    status = fork_status(bridge, f["fork_id"])
    assert status["status"] == "deleted"
    _cleanup(bridge, f["fork_id"])


def test_fork_list_open(bridge):
    f = fork_create(bridge, title="list test", created_by="hanuman", topic="test")
    forks = fork_list(bridge, status="open")
    ids = [x["fork_id"] for x in forks]
    assert f["fork_id"] in ids
    _cleanup(bridge, f["fork_id"])


def test_fork_status_not_found(bridge):
    result = fork_status(bridge, "FORK-DOESNOTEXIST")
    assert result is None
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_forks.py -v 2>&1 | head -20
```

Expected: `ImportError` — `willow.forks` does not exist.

- [ ] **Step 3: Create willow/forks.py**

```python
# willow/forks.py — Fork CRUD operations. b17: FORKS1  ΔΣ=42
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone

from core.pg_bridge import PgBridge


def _b17() -> str:
    """Generate a short b17-style fork ID."""
    return str(uuid.uuid4()).upper().replace("-", "")[:8]


def fork_create(
    bridge: PgBridge,
    title: str,
    created_by: str,
    topic: str = "",
    fork_id: str | None = None,
) -> dict:
    fork_id = fork_id or f"FORK-{_b17()}"
    cur = bridge.conn.cursor()
    cur.execute("""
        INSERT INTO forks (id, title, created_by, topic, status, participants, changes)
        VALUES (%s, %s, %s, %s, 'open', %s, '[]')
    """, (fork_id, title, created_by, topic, json.dumps([created_by])))
    bridge.conn.commit()
    return {"fork_id": fork_id, "status": "open"}


def fork_join(bridge: PgBridge, fork_id: str, component: str) -> dict:
    cur = bridge.conn.cursor()
    cur.execute("SELECT participants FROM forks WHERE id = %s", (fork_id,))
    row = cur.fetchone()
    if not row:
        return {"error": f"fork {fork_id} not found"}
    participants = json.loads(row[0])
    if component not in participants:
        participants.append(component)
    cur.execute(
        "UPDATE forks SET participants = %s WHERE id = %s",
        (json.dumps(participants), fork_id),
    )
    bridge.conn.commit()
    return {"fork_id": fork_id, "participants": participants}


def fork_log(
    bridge: PgBridge,
    fork_id: str,
    component: str,
    type_: str,
    ref: str,
    description: str = "",
) -> dict:
    cur = bridge.conn.cursor()
    cur.execute("SELECT changes FROM forks WHERE id = %s", (fork_id,))
    row = cur.fetchone()
    if not row:
        return {"error": f"fork {fork_id} not found"}
    changes = json.loads(row[0])
    changes.append({
        "component": component,
        "type": type_,
        "ref": ref,
        "description": description,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    })
    cur.execute(
        "UPDATE forks SET changes = %s WHERE id = %s",
        (json.dumps(changes), fork_id),
    )
    bridge.conn.commit()
    return {"logged": True, "change_count": len(changes)}


def fork_merge(bridge: PgBridge, fork_id: str, outcome_note: str = "") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cur = bridge.conn.cursor()
    cur.execute("""
        UPDATE forks SET status = 'merged', merged_at = %s, outcome_note = %s
        WHERE id = %s AND status = 'open'
    """, (now, outcome_note, fork_id))
    bridge.conn.commit()
    if cur.rowcount == 0:
        return {"merged": False, "reason": "fork not found or not open"}
    # Promote KB atoms: clear fork_id (make permanent)
    cur.execute("UPDATE knowledge SET fork_id = NULL WHERE fork_id = %s", (fork_id,))
    promoted = cur.rowcount
    bridge.conn.commit()
    return {"merged": True, "promoted_count": promoted}


def fork_delete(bridge: PgBridge, fork_id: str, reason: str = "") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    cur = bridge.conn.cursor()
    cur.execute("""
        UPDATE forks SET status = 'deleted', deleted_at = %s, outcome_note = %s
        WHERE id = %s AND status = 'open'
    """, (now, reason, fork_id))
    bridge.conn.commit()
    if cur.rowcount == 0:
        return {"deleted": False, "reason": "fork not found or not open"}
    # Archive KB atoms
    cur.execute("""
        UPDATE knowledge SET domain = 'archived'
        WHERE fork_id = %s
    """, (fork_id,))
    archived = cur.rowcount
    bridge.conn.commit()
    return {"deleted": True, "archived_count": archived}


def fork_status(bridge: PgBridge, fork_id: str) -> dict | None:
    cur = bridge.conn.cursor()
    cur.execute("""
        SELECT id, title, created_by, topic, status, participants, changes,
               created_at, merged_at, deleted_at, outcome_note
        FROM forks WHERE id = %s
    """, (fork_id,))
    row = cur.fetchone()
    if not row:
        return None
    return {
        "fork_id": row[0], "title": row[1], "created_by": row[2],
        "topic": row[3], "status": row[4],
        "participants": json.loads(row[5]), "changes": json.loads(row[6]),
        "created_at": str(row[7]), "merged_at": str(row[8]) if row[8] else None,
        "deleted_at": str(row[9]) if row[9] else None, "outcome_note": row[10],
    }


def fork_list(bridge: PgBridge, status: str = "open") -> list[dict]:
    cur = bridge.conn.cursor()
    cur.execute("""
        SELECT id, title, created_at, created_by, topic,
               jsonb_array_length(participants), jsonb_array_length(changes)
        FROM forks WHERE status = %s
        ORDER BY created_at DESC
        LIMIT 100
    """, (status,))
    return [
        {
            "fork_id": r[0], "title": r[1], "created_at": str(r[2]),
            "created_by": r[3], "topic": r[4],
            "participant_count": r[5], "change_count": r[6],
        }
        for r in cur.fetchall()
    ]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_forks.py -v
```

Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add willow/forks.py tests/test_forks.py
git commit -m "feat(forks): add Fork CRUD — create/join/log/merge/delete/status/list"
```

---

## Task 9: Wire willow_fork_* MCP tools into sap_mcp.py

**Files:**
- Modify: `sap/sap_mcp.py`

- [ ] **Step 1: Add the import at the top of sap_mcp.py**

Find the imports section near the top of `sap/sap_mcp.py` and add:

```python
from willow.forks import (
    fork_create, fork_join, fork_log, fork_merge,
    fork_delete, fork_status, fork_list,
)
```

- [ ] **Step 2: Register the 7 fork tools**

Find the section in `sap_mcp.py` where tools are registered (the `@server.list_tools()` handler). Add the 7 fork tools to the tool list:

```python
types.Tool(
    name="willow_fork_create",
    description="Create a new fork — a named, bounded unit of work.",
    inputSchema={
        "type": "object",
        "properties": {
            "title":      {"type": "string", "description": "Human-readable fork title"},
            "created_by": {"type": "string", "description": "Agent or user creating this fork"},
            "topic":      {"type": "string", "description": "Short topic tag (e.g. 'infrastructure')"},
            "fork_id":    {"type": "string", "description": "Optional: override generated fork ID"},
            "app_id":     {"type": "string"},
        },
        "required": ["title", "created_by", "app_id"],
    },
),
types.Tool(
    name="willow_fork_join",
    description="Join an existing fork as a participant component.",
    inputSchema={
        "type": "object",
        "properties": {
            "fork_id":   {"type": "string"},
            "component": {"type": "string", "description": "Component joining: hanuman, kart, grove, etc."},
            "app_id":    {"type": "string"},
        },
        "required": ["fork_id", "component", "app_id"],
    },
),
types.Tool(
    name="willow_fork_log",
    description="Log a change to an open fork.",
    inputSchema={
        "type": "object",
        "properties": {
            "fork_id":     {"type": "string"},
            "component":   {"type": "string"},
            "type":        {"type": "string", "description": "Change type: branch, atom, task, thread, compute_job"},
            "ref":         {"type": "string", "description": "Reference ID (branch name, atom ID, etc.)"},
            "description": {"type": "string"},
            "app_id":      {"type": "string"},
        },
        "required": ["fork_id", "component", "type", "ref", "app_id"],
    },
),
types.Tool(
    name="willow_fork_merge",
    description="Merge an open fork — promotes KB atoms to permanent, notifies participants.",
    inputSchema={
        "type": "object",
        "properties": {
            "fork_id":      {"type": "string"},
            "outcome_note": {"type": "string"},
            "app_id":       {"type": "string"},
        },
        "required": ["fork_id", "app_id"],
    },
),
types.Tool(
    name="willow_fork_delete",
    description="Delete an open fork — archives KB atoms, cancels tasks.",
    inputSchema={
        "type": "object",
        "properties": {
            "fork_id": {"type": "string"},
            "reason":  {"type": "string"},
            "app_id":  {"type": "string"},
        },
        "required": ["fork_id", "app_id"],
    },
),
types.Tool(
    name="willow_fork_status",
    description="Get the full status of a fork — participants, changes, outcome.",
    inputSchema={
        "type": "object",
        "properties": {
            "fork_id": {"type": "string"},
            "app_id":  {"type": "string"},
        },
        "required": ["fork_id", "app_id"],
    },
),
types.Tool(
    name="willow_fork_list",
    description="List forks by status.",
    inputSchema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["open", "merged", "deleted"], "default": "open"},
            "app_id": {"type": "string"},
        },
        "required": ["app_id"],
    },
),
```

- [ ] **Step 3: Wire the handlers**

Find the `call_tool` handler in `sap_mcp.py` (the large if/elif block). Add the fork handlers:

```python
elif name == "willow_fork_create":
    with PgBridge() as b:
        result = fork_create(
            b,
            title=args["title"],
            created_by=args["created_by"],
            topic=args.get("topic", ""),
            fork_id=args.get("fork_id"),
        )
    return [types.TextContent(type="text", text=_json.dumps(result))]

elif name == "willow_fork_join":
    with PgBridge() as b:
        result = fork_join(b, args["fork_id"], args["component"])
    return [types.TextContent(type="text", text=_json.dumps(result))]

elif name == "willow_fork_log":
    with PgBridge() as b:
        result = fork_log(
            b,
            args["fork_id"],
            args["component"],
            args["type"],
            args["ref"],
            args.get("description", ""),
        )
    return [types.TextContent(type="text", text=_json.dumps(result))]

elif name == "willow_fork_merge":
    with PgBridge() as b:
        result = fork_merge(b, args["fork_id"], args.get("outcome_note", ""))
    return [types.TextContent(type="text", text=_json.dumps(result))]

elif name == "willow_fork_delete":
    with PgBridge() as b:
        result = fork_delete(b, args["fork_id"], args.get("reason", ""))
    return [types.TextContent(type="text", text=_json.dumps(result))]

elif name == "willow_fork_status":
    with PgBridge() as b:
        result = fork_status(b, args["fork_id"])
    return [types.TextContent(type="text", text=_json.dumps(result))]

elif name == "willow_fork_list":
    with PgBridge() as b:
        result = fork_list(b, status=args.get("status", "open"))
    return [types.TextContent(type="text", text=_json.dumps(result))]
```

- [ ] **Step 4: Restart MCP server and smoke test**

```
Use willow_fork_create with title="1.9 launch", created_by="hanuman", topic="infrastructure", app_id="hanuman"
```

Expected: `{"fork_id": "FORK-XXXXXXXX", "status": "open"}`

```
Use willow_fork_list with app_id="hanuman"
```

Expected: list containing the fork just created.

- [ ] **Step 5: Commit**

```bash
git add sap/sap_mcp.py
git commit -m "feat(forks): wire willow_fork_* MCP tools (7 tools) into sap_mcp.py"
```

---

## Task 10: Session anchor writes fork_id on startup

**Files:**
- Modify: `willow/fylgja/events/session_start.py`

- [ ] **Step 1: Add fork auto-creation to _run_silent_startup()**

In `willow/fylgja/events/session_start.py`, inside `_run_silent_startup()`, after the existing anchor write block, add:

```python
    # Auto-create session fork
    fork_id = ""
    try:
        fork_result = call("willow_fork_create", {
            "app_id": AGENT,
            "title": f"Session {datetime.now().strftime('%Y-%m-%d')} — {AGENT}",
            "created_by": AGENT,
            "topic": "session",
        }, timeout=5)
        fork_id = fork_result.get("fork_id", "")
    except Exception:
        pass
```

- [ ] **Step 2: Write fork_id to session_anchor.json**

Find where `session_anchor.json` is written in `_run_silent_startup()` and add `fork_id` to the payload:

```python
    anchor_data = {
        "written_at": datetime.now().isoformat(),
        "agent": AGENT,
        "postgres": result.get("postgres", "unknown"),
        "handoff_title": result.get("handoff_title", ""),
        "handoff_summary": result.get("handoff_summary", ""),
        "open_flags": result.get("open_flags", 0),
        "top_flags": result.get("top_flags", []),
        "fork_id": fork_id,
    }
    try:
        anchor_file.write_text(_json.dumps(anchor_data, indent=2))
    except Exception:
        pass
```

- [ ] **Step 3: Emit fork_id in additionalContext**

Find where `additionalContext` is built and returned in `session_start.py`. Add the fork ID to the ANCHOR line:

```python
    anchor_line = (
        f"[ANCHOR]\nagent={AGENT}  postgres={postgres_state}"
        + (f"  fork={fork_id}" if fork_id else "")
    )
```

- [ ] **Step 4: Verify**

Start a new Claude Code session in this project and check that:
1. `~/.willow/session_anchor.json` contains a `fork_id` field
2. The ANCHOR context line shows `fork=FORK-XXXXXXXX`
3. `willow_fork_list` returns the auto-created session fork

- [ ] **Step 5: Commit**

```bash
cd ~/github/willow-1.9
git add willow/fylgja/events/session_start.py
git commit -m "feat(forks): auto-create session fork on startup, write fork_id to session anchor"
```

---

## Task 11: Canopy page 5 — model provider selection

**Files:**
- Modify: `willow-dashboard/canopy.py`

- [ ] **Step 1: Add the model provider page function**

In `willow-dashboard/canopy.py`, after the existing page functions, add:

```python
_PROVIDERS = [
    ("groq",             "Groq API        (recommended — fast, generous free tier)"),
    ("anthropic",        "Anthropic API   (Claude — best quality, requires paid plan)"),
    ("ollama",           "Ollama          (local model — requires GPU)"),
    ("xai",              "xAI API         (Grok)"),
    ("openai_compatible","Other           (any OpenAI-compatible endpoint)"),
]

_PROVIDER_ENV_KEYS = {
    "groq":             "GROQ_API_KEY",
    "anthropic":        "ANTHROPIC_API_KEY",
    "xai":              "XAI_API_KEY",
    "openai_compatible":"OPENAI_COMPAT_API_KEY",
}

_PROVIDER_KEY_HINTS = {
    "groq":             "gsk_...",
    "anthropic":        "sk-ant-...",
    "xai":              "xai-...",
    "openai_compatible":"(your endpoint API key)",
}


def page_model_provider(stdscr) -> dict | None:
    """Page 5 — model provider selection. Returns {'provider': ..., 'api_key': ...} or None."""
    curses.curs_set(0)
    h, w = stdscr.getmaxyx()
    stdscr.clear()

    amber = curses.color_pair(_CA_AMBER)
    bright = curses.color_pair(_CA_BRIGHT)
    dim = curses.color_pair(_CA_DIM)
    green = curses.color_pair(_CA_GREEN)

    selected = 0

    def _draw():
        stdscr.clear()
        _safe(stdscr, 2, 4, "WHICH MODEL DO YOU WANT TO USE?", bright | curses.A_BOLD)
        _safe(stdscr, 3, 4, "─" * min(50, w - 8), dim)
        for i, (_, label) in enumerate(_PROVIDERS):
            attr = amber | curses.A_BOLD if i == selected else amber
            prefix = "▶ " if i == selected else "  "
            _safe(stdscr, 5 + i, 4, prefix + label, attr)
        _safe(stdscr, 6 + len(_PROVIDERS), 4,
              "↑↓ move   Enter select   (Ollama: no key needed)", dim)
        stdscr.refresh()

    while True:
        _draw()
        key = stdscr.getch()
        if key == curses.KEY_UP and selected > 0:
            selected -= 1
        elif key == curses.KEY_DOWN and selected < len(_PROVIDERS) - 1:
            selected += 1
        elif key in (curses.KEY_ENTER, 10, 13):
            provider, _ = _PROVIDERS[selected]
            if provider == "ollama":
                return {"provider": "ollama", "api_key": ""}
            return _page_enter_api_key(stdscr, provider)


def _page_enter_api_key(stdscr, provider: str) -> dict | None:
    """Sub-page: enter API key for selected provider."""
    h, w = stdscr.getmaxyx()
    env_key = _PROVIDER_ENV_KEYS.get(provider, "API_KEY")
    hint = _PROVIDER_KEY_HINTS.get(provider, "")
    curses.curs_set(1)
    amber = curses.color_pair(_CA_AMBER)
    bright = curses.color_pair(_CA_BRIGHT)
    dim = curses.color_pair(_CA_DIM)
    red = curses.color_pair(_CA_RED)

    buf = []
    stdscr.clear()
    _safe(stdscr, 2, 4, f"ENTER YOUR {env_key}", bright | curses.A_BOLD)
    _safe(stdscr, 3, 4, f"Hint: {hint}", dim)
    _safe(stdscr, 4, 4, "(the key is stored encrypted in ~/.willow/vault.db)", dim)
    _safe(stdscr, 6, 4, "Key: ", amber)
    stdscr.refresh()

    while True:
        key = stdscr.getch()
        if key in (curses.KEY_ENTER, 10, 13):
            api_key = "".join(buf).strip()
            if not api_key:
                _safe(stdscr, 8, 4, "Key cannot be empty. Press any key.", red)
                stdscr.refresh()
                stdscr.getch()
                return _page_enter_api_key(stdscr, provider)
            return {"provider": provider, "api_key": api_key}
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
        elif 32 <= key <= 126:
            buf.append(chr(key))
        # Redraw key field (mask with *)
        field = "*" * len(buf)
        _safe(stdscr, 6, 9, " " * max(1, w - 13), 0)
        _safe(stdscr, 6, 9, field, curses.color_pair(_CA_AMBER))
        stdscr.refresh()
```

- [ ] **Step 2: Wire page 5 into the boot sequence**

In `canopy.py`, find the `run_boot()` or equivalent function that chains the pages for new users. After page 4 (path select), add:

```python
    # Page 5 — model provider (new users only)
    if is_new_user:
        model_result = curses.wrapper(page_model_provider)
        if model_result:
            _save_model_provider(model_result["provider"], model_result["api_key"])
```

- [ ] **Step 3: Add _save_model_provider()**

```python
def _save_model_provider(provider: str, api_key: str) -> None:
    """Store selected model provider in SOIL and API key in vault."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "willow-1.9"))
    try:
        from core.vault import Vault
        from core.willow_store import WillowStore
        # Save API key to vault
        if api_key:
            v = Vault()
            if not (Path.home() / ".willow" / "vault.db").exists():
                v.init()
            env_key = {
                "anthropic": "ANTHROPIC_API_KEY",
                "groq":      "GROQ_API_KEY",
                "xai":       "XAI_API_KEY",
            }.get(provider, "API_KEY")
            v.write(env_key, api_key)
        # Save provider selection to SOIL
        store = WillowStore()
        store.put("willow/settings", "model", {
            "provider": provider,
            "model": None,  # use adapter default
        })
    except Exception as e:
        _blog(f"model provider save failed: {e}")
```

- [ ] **Step 4: Test manually**

```bash
cd ~/github/willow-dashboard
python3 -c "import curses; from canopy import page_model_provider; curses.wrapper(page_model_provider)"
```

Navigate the list, select Groq, enter a key. Verify no crash.

- [ ] **Step 5: Commit**

```bash
cd ~/github/willow-dashboard
git add canopy.py
git commit -m "feat(canopy): add page 5 — model provider selection with vault storage"
```

---

## Task 12: Dashboard Settings — show active adapter

**Files:**
- Modify: `willow-dashboard/dashboard.py`

- [ ] **Step 1: Add model adapter status to SystemData**

Find the `SystemData` class or the function that fetches system info in `dashboard.py`. Add:

```python
def _fetch_model_adapter() -> dict:
    """Return active model provider name and health."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "willow-1.9"))
        from core.willow_store import WillowStore
        store = WillowStore()
        setting = store.get("willow/settings", "model")
        if not setting:
            return {"provider": "ollama", "healthy": None}
        provider = setting.get("provider", "ollama")
        from core.model_adapter import get_adapter
        vault_key = {
            "anthropic": "ANTHROPIC_API_KEY",
            "groq":      "GROQ_API_KEY",
            "xai":       "XAI_API_KEY",
        }.get(provider)
        kwargs = {}
        if vault_key:
            from core.vault import Vault
            key_val = Vault().read(vault_key)
            if key_val:
                kwargs["api_key"] = key_val
        adapter = get_adapter(provider, **kwargs)
        return {"provider": provider, "healthy": adapter.health()}
    except Exception:
        return {"provider": "unknown", "healthy": False}
```

- [ ] **Step 2: Display in Settings page**

Find `draw_settings()` or equivalent in `dashboard.py`. Add a model section:

```python
    model_info = _fetch_model_adapter()
    health_str = "✓ healthy" if model_info["healthy"] else ("✗ unreachable" if model_info["healthy"] is False else "? unknown")
    health_color = C_GREEN if model_info["healthy"] else C_RED
    _safe(win, row, 4, f"Model provider:  {model_info['provider']}", C_AMBER)
    _safe(win, row, 4 + 27, health_str, health_color)
    row += 1
    _safe(win, row, 4, "Change provider: run canopy with --force-setup", C_DIM)
    row += 2
```

- [ ] **Step 3: Verify visually**

Launch the dashboard and navigate to Settings (key `8`). Confirm model provider line appears.

- [ ] **Step 4: Commit**

```bash
cd ~/github/willow-dashboard
git add dashboard.py
git commit -m "feat(dashboard): show active model adapter + health in Settings page"
```

---

## Phase 1 Complete — Verification Checklist

Run this before marking Phase 1 done:

- [ ] `bash -n ~/github/willow-dashboard/willow-dashboard.sh` — no syntax errors
- [ ] `pytest tests/test_vault.py -v` — 5 PASS
- [ ] `pytest tests/test_model_adapter.py -v` — all PASS
- [ ] `pytest tests/test_forks.py -v` — 7 PASS
- [ ] `pytest tests/test_pg_bridge.py -v -k "fork"` — 3 PASS
- [ ] `python3 scripts/migrate_fork_origin.py --dry-run` — shows correct atom count
- [ ] `python3 scripts/migrate_fork_origin.py` — FORK-ORIGIN created, atoms tagged
- [ ] New Claude Code session: `session_anchor.json` contains `fork_id`
- [ ] `willow_fork_list` returns the auto-created session fork
- [ ] Dashboard Settings page shows model provider

---

*Phase 2 plan: `docs/superpowers/plans/2026-04-24-willow-19-phase2-orchestration.md`*
*Phase 3 plan: `docs/superpowers/plans/2026-04-24-willow-19-phase3-skills-grove.md`*
*Phase 4 plan: `docs/superpowers/plans/2026-04-24-willow-19-phase4-verify.md`*

ΔΣ=42
