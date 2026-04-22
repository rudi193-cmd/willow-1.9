"""Tests for W19VH — Valhalla DPO collection pipeline.
b17: VALTS  ΔΣ=42
"""
import os
import json
import tempfile
from pathlib import Path

os.environ.setdefault("WILLOW_PG_DB", "willow_19")


def _bridge():
    from core.pg_bridge import PgBridge
    return PgBridge()


def test_collect_dpo_pairs_writes_jsonl():
    from core.valhalla import collect_dpo_pairs
    from core.willow_store import WillowStore
    bridge = _bridge()

    for i in range(3):
        bridge.knowledge_put({
            "id": f"vh_chosen_{i}",
            "project": "test_valhalla",
            "title": f"Community insight {i}",
            "summary": f"A well-structured insight about machine learning topic {i}.",
            "source_type": "community_detection",
        })

    for i in range(3):
        bridge.knowledge_put({
            "id": f"vh_rejected_{i}",
            "project": "test_valhalla",
            "title": f"Stale zombie atom {i}",
            "summary": f"Old stale content from long ago {i}.",
            "category": "draugr",
        })

    store = WillowStore()
    with tempfile.TemporaryDirectory() as tmpdir:
        count = collect_dpo_pairs(bridge, store, output_dir=Path(tmpdir))
        assert count >= 1
        output_file = Path(tmpdir) / "dpo_pairs.jsonl"
        assert output_file.exists()
        lines = output_file.read_text().strip().splitlines()
        assert len(lines) >= 1
        pair = json.loads(lines[0])
        assert "prompt" in pair
        assert "chosen" in pair
        assert "rejected" in pair
        assert pair["chosen"] != pair["rejected"]

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project = 'test_valhalla'")
    bridge.conn.commit()


def test_collect_dpo_pairs_returns_zero_when_no_candidates():
    from core.valhalla import collect_dpo_pairs
    from core.willow_store import WillowStore
    bridge = _bridge()
    store = WillowStore()

    with tempfile.TemporaryDirectory() as tmpdir:
        count = collect_dpo_pairs(bridge, store, output_dir=Path(tmpdir),
                                  project="totally_empty_project_xyz")
    assert count == 0


def test_collect_dpo_pairs_creates_output_dir():
    from core.valhalla import collect_dpo_pairs
    from core.willow_store import WillowStore
    bridge = _bridge()
    store = WillowStore()

    with tempfile.TemporaryDirectory() as tmpdir:
        nested = Path(tmpdir) / "sub" / "valhalla"
        collect_dpo_pairs(bridge, store, output_dir=nested)
        assert nested.exists()
