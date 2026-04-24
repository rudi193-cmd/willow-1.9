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
