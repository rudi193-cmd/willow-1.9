"""Tests for W19RT — Ratatoskr Protocol: cross-project connect."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _write_manifest(safe_root: Path, app_id: str, connect: list = None) -> Path:
    app_dir = safe_root / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"app_id": app_id, "name": app_id, "connect": connect or []}
    manifest_path = app_dir / "safe-app-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


def test_get_connected_projects_returns_empty_without_connect(tmp_path):
    from core.ratatoskr import get_connected_projects
    _write_manifest(tmp_path, "app_a", connect=[])
    assert get_connected_projects("app_a", tmp_path) == []


def test_get_connected_projects_returns_declared_connections(tmp_path):
    from core.ratatoskr import get_connected_projects
    _write_manifest(tmp_path, "app_a", connect=["proj_b", "proj_c"])
    result = get_connected_projects("app_a", tmp_path)
    assert "proj_b" in result
    assert "proj_c" in result


def test_get_connected_projects_returns_empty_when_no_manifest(tmp_path):
    from core.ratatoskr import get_connected_projects
    assert get_connected_projects("no_such_app", tmp_path) == []


def test_is_connected_true_when_declared(tmp_path):
    from core.ratatoskr import is_connected
    _write_manifest(tmp_path, "app_a", connect=["proj_b"])
    assert is_connected("app_a", "proj_b", tmp_path) is True


def test_is_connected_false_when_not_declared(tmp_path):
    from core.ratatoskr import is_connected
    _write_manifest(tmp_path, "app_a", connect=[])
    assert is_connected("app_a", "proj_b", tmp_path) is False


def test_filter_cross_project_passes_community_nodes_only(tmp_path):
    from core.ratatoskr import filter_for_cross_project
    records = [
        {"id": "a1", "project": "proj_b", "source_type": "community_detection",
         "title": "community node"},
        {"id": "a2", "project": "proj_b", "source_type": "session", "title": "raw atom"},
    ]
    result = filter_for_cross_project(records)
    assert len(result) == 1
    assert result[0]["id"] == "a1"


def test_filter_cross_project_passes_all_when_connected(tmp_path):
    from core.ratatoskr import filter_for_cross_project
    records = [
        {"id": "b1", "source_type": "session", "title": "raw"},
        {"id": "b2", "source_type": "community_detection", "title": "community"},
    ]
    assert len(filter_for_cross_project(records, full_access=True)) == 2
