"""Tests for W19DS — Data Sovereignty: nuke + telemetry."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_telemetry_default_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, seed
    importlib.reload(seed)
    (tmp_path / ".willow").mkdir(parents=True, exist_ok=True)
    seed.step_telemetry_init()
    data = json.loads((tmp_path / ".willow" / "telemetry.json").read_text())
    assert data["enabled"] is False


def test_telemetry_init_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, seed
    importlib.reload(seed)
    (tmp_path / ".willow").mkdir(parents=True, exist_ok=True)
    seed.step_telemetry_init()
    seed.step_telemetry_init()  # must not overwrite
    data = json.loads((tmp_path / ".willow" / "telemetry.json").read_text())
    assert data["enabled"] is False


def test_willow_dir_has_telemetry_after_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    import importlib, seed
    importlib.reload(seed)
    seed.step_1_dirs()
    seed.step_telemetry_init()
    assert (tmp_path / ".willow" / "telemetry.json").exists()


def test_export_produces_json(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    store = ws.WillowStore()
    store.put("test/atoms", {"_id": "exp1", "title": "exportable"})
    export_path = tmp_path / "export.json"
    data = {"store": {}}
    for col in store.collections():
        data["store"][col] = store.list(col)
    export_path.write_text(json.dumps(data, indent=2))
    loaded = json.loads(export_path.read_text())
    assert "store" in loaded
    assert "test/atoms" in loaded["store"]
