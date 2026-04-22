# tests/adversarial/test_cross_project.py
"""Ratatoskr cross-project access control — bypass attempts.
Without a connect declaration, private atoms must be filtered out.
Only community_detection atoms may cross project boundaries unauthenticated.
"""
import json
import pytest
from core.ratatoskr import (
    get_connected_projects,
    is_connected,
    filter_for_cross_project,
    cross_project_search,
)


def test_no_manifest_returns_empty(tmp_safe_root):
    result = get_connected_projects("nonexistent_app", safe_root=tmp_safe_root)
    assert result == []


def test_manifest_no_connect_key(tmp_safe_root):
    app_dir = tmp_safe_root / "myapp"
    app_dir.mkdir(parents=True)
    (app_dir / "safe-app-manifest.json").write_text(json.dumps({"name": "myapp"}))
    result = get_connected_projects("myapp", safe_root=tmp_safe_root)
    assert result == []


def test_manifest_connect_declared(tmp_safe_root):
    app_dir = tmp_safe_root / "connectedapp"
    app_dir.mkdir(parents=True)
    (app_dir / "safe-app-manifest.json").write_text(
        json.dumps({"name": "connectedapp", "connect": ["proj_b", "proj_c"]})
    )
    assert is_connected("connectedapp", "proj_b", safe_root=tmp_safe_root) is True
    assert is_connected("connectedapp", "proj_c", safe_root=tmp_safe_root) is True
    assert is_connected("connectedapp", "proj_d", safe_root=tmp_safe_root) is False


def test_malformed_manifest_json(tmp_safe_root):
    """Malformed manifest must not crash — returns empty list."""
    app_dir = tmp_safe_root / "badapp"
    app_dir.mkdir(parents=True)
    (app_dir / "safe-app-manifest.json").write_text("{ not valid json !!!")
    result = get_connected_projects("badapp", safe_root=tmp_safe_root)
    assert result == []


def test_filter_blocks_private_without_connect():
    """Private atom (no source_type) is blocked when full_access=False."""
    private = {"id": "adv_secret", "project": "proj_b", "title": "private data", "source_type": None}
    result = filter_for_cross_project([private], full_access=False)
    assert result == []


def test_filter_passes_community_without_connect():
    """community_detection atoms pass through even without full_access."""
    community = {
        "id": "adv_community",
        "project": "proj_b",
        "title": "community node",
        "source_type": "community_detection",
    }
    result = filter_for_cross_project([community], full_access=False)
    assert len(result) == 1
    assert result[0]["id"] == "adv_community"


def test_cross_project_search_without_connect_filters(bridge, tmp_safe_root):
    """End-to-end: private atoms do not leak across projects without connect declaration."""
    bridge.knowledge_put({
        "id": "adv_xp_private",
        "project": "adv_target_proj",
        "title": "private sensitive knowledge",
        "summary": "secret information must not cross",
        "source_type": None,
    })
    bridge.knowledge_put({
        "id": "adv_xp_community",
        "project": "adv_target_proj",
        "title": "community sensitive knowledge",
        "summary": "shared community insight may cross",
        "source_type": "community_detection",
    })
    results = cross_project_search(
        bridge,
        query="sensitive knowledge",
        source_project="adv_source_proj",
        target_project="adv_target_proj",
        app_id="adv_no_connect_app",
        safe_root=tmp_safe_root,
    )
    ids = [r["id"] for r in results]
    assert "adv_xp_private" not in ids, "Private atom leaked without connect declaration"
    assert "adv_xp_community" in ids, "Community atom should pass through"
