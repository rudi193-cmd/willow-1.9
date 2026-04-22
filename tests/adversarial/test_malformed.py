# tests/adversarial/test_malformed.py
"""Malformed inputs, oversized payloads, and path traversal.
Tests the system's hardening at its edges: what happens with bad data at the boundary.
"""
import tarfile
import pytest
from core.backup import _safe_tar_members
from core.willow_store import WillowStore


def test_path_traversal_relative_blocked(make_tar, tmp_path):
    """../../ traversal in tar member name must be excluded."""
    tar_path = make_tar([
        ("../../etc/passwd", b"root:x:0:0:root:/root:/bin/bash"),
        ("willow/store.db", b"legitimate backup data"),
    ])
    target_dir = tmp_path / "extract"
    target_dir.mkdir()
    with tarfile.open(tar_path, "r:gz") as tf:
        safe = list(_safe_tar_members(tf, target_dir))
    names = [m.name for m in safe]
    assert "../../etc/passwd" not in names, "Path traversal member was not filtered"
    assert "willow/store.db" in names, "Legitimate member was incorrectly filtered"


def test_path_traversal_absolute_blocked(make_tar, tmp_path):
    """Absolute path in tar member name must be excluded."""
    tar_path = make_tar([
        ("/etc/shadow", b"sensitive system file"),
        ("willow/good.db", b"legitimate data"),
    ])
    target_dir = tmp_path / "extract"
    target_dir.mkdir()
    with tarfile.open(tar_path, "r:gz") as tf:
        safe = list(_safe_tar_members(tf, target_dir))
    names = [m.name for m in safe]
    assert "/etc/shadow" not in names
    assert "willow/good.db" in names


def test_path_traversal_valid_member_passes(make_tar, tmp_path):
    """A well-formed relative path must pass through unchanged."""
    tar_path = make_tar([("willow/store.db", b"backup contents")])
    target_dir = tmp_path / "extract"
    target_dir.mkdir()
    with tarfile.open(tar_path, "r:gz") as tf:
        safe = list(_safe_tar_members(tf, target_dir))
    assert len(safe) == 1
    assert safe[0].name == "willow/store.db"


def test_oversized_content_stored_intact(bridge):
    """1MB content blob must survive a round-trip without truncation."""
    big_content = {"data": "x" * (1024 * 1024)}
    bridge.knowledge_put({
        "id": "adv_oversized",
        "project": "adv_malformed",
        "title": "oversized content atom",
        "summary": "payload is large",
        "content": big_content,
    })
    results = bridge.knowledge_search("oversized content atom", project="adv_malformed")
    assert len(results) == 1
    assert len(results[0]["content"]["data"]) == 1024 * 1024, "Content was truncated"


def test_knowledge_put_missing_id_raises(bridge):
    """knowledge_put with no id field must raise, not silently fail."""
    with pytest.raises((KeyError, ValueError)):
        bridge.knowledge_put({
            "project": "adv_malformed",
            "title": "no id field present",
        })


def test_unicode_roundtrip(bridge):
    """Unicode in all text fields (emoji, CJK, Arabic, Hebrew) must survive round-trip."""
    title = "Hello 🌍 你好 مرحبا שלום"
    summary = "Unicode roundtrip: emoji CJK Arabic Hebrew in one atom"
    bridge.knowledge_put({
        "id": "adv_unicode",
        "project": "adv_malformed",
        "title": title,
        "summary": summary,
    })
    results = bridge.knowledge_search("Unicode roundtrip", project="adv_malformed")
    assert len(results) == 1
    assert results[0]["title"] == title
    assert results[0]["summary"] == summary


def test_empty_search_query_no_crash(bridge):
    """Empty search query must not crash — ILIKE %% matches everything."""
    bridge.knowledge_put({
        "id": "adv_empty_search",
        "project": "adv_malformed",
        "title": "findable via empty search",
        "summary": "present in db",
    })
    results = bridge.knowledge_search("", project="adv_malformed")
    assert isinstance(results, list)
    assert any(r["id"] == "adv_empty_search" for r in results)


def test_huge_search_query_no_crash(bridge):
    """10,000-character search query must not crash the server."""
    huge_query = "willow " * 1000  # 7000 chars
    results = bridge.knowledge_search(huge_query, project="adv_malformed")
    assert isinstance(results, list)


def test_willow_store_missing_id_raises(tmp_path):
    """WillowStore.put with no id/_id/b17 field must raise ValueError."""
    store = WillowStore(root=str(tmp_path / "store"))
    with pytest.raises(ValueError):
        store.put("adv/test", {"title": "no id field here at all"})


def test_willow_store_search_empty_query_returns_all(tmp_path):
    """WillowStore.search with empty string must return all records (not crash)."""
    store = WillowStore(root=str(tmp_path / "store"))
    store.put("adv/test", {"id": "item1", "title": "apple"})
    store.put("adv/test", {"id": "item2", "title": "banana"})
    results = store.search("adv/test", "")
    assert len(results) == 2
