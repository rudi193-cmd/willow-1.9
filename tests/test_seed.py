"""Tests for seed.py — Sleipnir 8 steps."""
import sqlite3
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_step_1_creates_willow_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, root as seed
    importlib.reload(seed)
    seed.step_1_dirs()
    assert (tmp_path / ".willow").exists()
    assert (tmp_path / ".willow" / "store").exists()
    assert (tmp_path / ".willow" / "secrets").exists()
    assert (tmp_path / ".willow" / "logs").exists()
    assert (tmp_path / "SAFE" / "Applications").exists()


def test_step_1_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, root as seed
    importlib.reload(seed)
    seed.step_1_dirs()
    seed.step_1_dirs()  # second call must not raise
    assert (tmp_path / ".willow").exists()


def test_step_4_vault_creates_db(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, root as seed
    importlib.reload(seed)
    (tmp_path / ".willow").mkdir(parents=True, exist_ok=True)
    seed.step_4_vault()
    vault = tmp_path / ".willow" / "vault.db"
    assert vault.exists()
    conn = sqlite3.connect(str(vault))
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert "credentials" in tables


def test_step_4_vault_key_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, root as seed
    importlib.reload(seed)
    (tmp_path / ".willow").mkdir(parents=True, exist_ok=True)
    seed.step_4_vault()
    key_path = tmp_path / ".willow" / ".master.key"
    assert key_path.exists()
    assert oct(key_path.stat().st_mode)[-3:] == "600"


def test_step_4_vault_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, root as seed
    importlib.reload(seed)
    (tmp_path / ".willow").mkdir(parents=True, exist_ok=True)
    seed.step_4_vault()
    key1 = (tmp_path / ".willow" / ".master.key").read_bytes()
    seed.step_4_vault()
    key2 = (tmp_path / ".willow" / ".master.key").read_bytes()
    assert key1 == key2


def test_step_8_version_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, root as seed
    importlib.reload(seed)
    (tmp_path / ".willow").mkdir(parents=True, exist_ok=True)
    seed.step_8_version_pin()
    version = (tmp_path / ".willow" / "version").read_text().strip()
    assert version == "1.9.0"


def test_sleipnir_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, root as seed
    importlib.reload(seed)
    seed.sleipnir(skip_pg=True, skip_socket=True, skip_gpg=True)
    seed.sleipnir(skip_pg=True, skip_socket=True, skip_gpg=True)
    assert (tmp_path / ".willow" / "version").exists()
