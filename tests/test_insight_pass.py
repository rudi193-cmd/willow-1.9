from unittest.mock import patch
import core.intelligence as intel


REFLECTIONS = [
    {"id": "r1", "type": "reflection", "session_id": "s1",
     "target": "core/pg_bridge.py", "summary": "Check locks before connecting.",
     "importance": 7, "insight_skip": False, "invalid_at": None},
    {"id": "r2", "type": "reflection", "session_id": "s2",
     "target": "core/pg_bridge.py", "summary": "Clean stale connections at startup.",
     "importance": 8, "insight_skip": False, "invalid_at": None},
    {"id": "r3", "type": "reflection", "session_id": "s3",
     "target": "core/pg_bridge.py", "summary": "Use idle_in_transaction_timeout.",
     "importance": 6, "insight_skip": False, "invalid_at": None},
    {"id": "r4", "type": "reflection", "session_id": "s4",
     "target": "willow/corpus/sandbox.py", "summary": "Different domain.",
     "importance": 5, "insight_skip": False, "invalid_at": None},
]


def test_cluster_reflections_by_domain():
    clusters = intel._cluster_reflections(REFLECTIONS)
    pg_cluster = clusters.get("pg_bridge", [])
    assert len(pg_cluster) == 3


def test_insight_pass_calls_ygg_when_n_ge_3():
    calls_ygg = []
    calls_store = []

    def fake_store(tool, args, timeout=5):
        calls_store.append((tool, args))
        if tool == "store_list":
            return REFLECTIONS
        return {"ok": True}

    def fake_ygg(prompt, timeout=30):
        calls_ygg.append(prompt)
        return {"summary": "Always manage Postgres connections explicitly.", "importance": 9}

    with patch("core.intelligence._ygg_structured", fake_ygg):
        result = intel.insight_pass(fake_store)

    assert len(calls_ygg) >= 1
    assert result["insights_written"] >= 1


def test_insight_pass_skips_small_clusters():
    solo = [REFLECTIONS[3]]
    calls_ygg = []

    def fake_store(tool, args, timeout=5):
        if tool == "store_list":
            return solo
        return {"ok": True}

    def fake_ygg(prompt, timeout=30):
        calls_ygg.append(prompt)
        return {"summary": "x", "importance": 5}

    with patch("core.intelligence._ygg_structured", fake_ygg):
        result = intel.insight_pass(fake_store)

    assert len(calls_ygg) == 0
    assert result["insights_written"] == 0


def test_chunk_pass_clusters_insights():
    insights = [
        {"id": "i1", "type": "insight", "domain": "pg_bridge",
         "summary": "Always clean stale connections.", "importance": 9, "invalid_at": None},
        {"id": "i2", "type": "insight", "domain": "pg_bridge",
         "summary": "Use idle_in_transaction_timeout.", "importance": 8, "invalid_at": None},
    ]
    calls_store = []
    calls_ygg = []

    def fake_store(tool, args, timeout=5):
        calls_store.append((tool, args))
        if tool == "store_list" and "atoms" in args.get("collection", ""):
            return insights
        if tool == "store_list" and "skills" in args.get("collection", ""):
            return []
        return {"ok": True}

    def fake_ygg(prompt, timeout=30):
        calls_ygg.append(prompt)
        return {"summary": "Postgres connection pattern", "importance": 8}

    with patch("core.intelligence._ygg_structured", fake_ygg):
        result = intel.chunk_pass(fake_store)

    assert len(calls_ygg) >= 1
    chunk_puts = [
        a for t, a in calls_store
        if t == "store_put" and "skills" in a.get("collection", "")
    ]
    assert len(chunk_puts) >= 1
    chunk = chunk_puts[0]["record"]
    assert chunk["type"] == "chunk"
    assert chunk["success_count"] == 0


def test_insight_pass_marks_low_score_as_skip():
    calls_store = []

    def fake_store(tool, args, timeout=5):
        calls_store.append((tool, args))
        if tool == "store_list":
            return REFLECTIONS
        return {"ok": True}

    def fake_ygg(prompt, timeout=30):
        return {"summary": "Coincidental.", "importance": 3}

    with patch("core.intelligence._ygg_structured", fake_ygg):
        intel.insight_pass(fake_store)

    updates = [(t, a) for t, a in calls_store if t == "store_update"]
    assert any(
        a.get("record", {}).get("insight_skip") is True
        for _, a in updates
    )
