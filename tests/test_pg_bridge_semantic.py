# tests/test_pg_bridge_semantic.py
import os
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent))


def _conn():
    return psycopg2.connect(
        dbname=os.environ.get("WILLOW_PG_DB", "willow_19_test"),
        user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
    )


# ── Schema tests ──────────────────────────────────────────────────────────────

def test_knowledge_has_embedding_column():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'knowledge' AND column_name = 'embedding'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "knowledge.embedding column missing"


def test_opus_atoms_has_embedding_column():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'opus_atoms' AND column_name = 'embedding'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "opus_atoms.embedding column missing"


def test_jeles_atoms_has_embedding_column():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'jeles_atoms' AND column_name = 'embedding'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "jeles_atoms.embedding column missing"


def test_knowledge_hnsw_index_exists():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'knowledge' AND indexname = 'knowledge_embedding_hnsw'
    """)
    row = cur.fetchone()
    conn.close()
    assert row is not None, "HNSW index on knowledge.embedding missing"


# ── Write-path tests ──────────────────────────────────────────────────────────

def test_knowledge_put_embeds_on_write():
    from core.pg_bridge import PgBridge
    pg = PgBridge()
    fake_vec = [0.1] * 768
    with patch("core.pg_bridge.embed", return_value=fake_vec):
        atom_id = pg.gen_id(8)
        pg.knowledge_put({
            "id": atom_id, "project": "test", "title": "embed test",
            "summary": "this should get embedded", "source_type": "test",
        })
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT embedding FROM knowledge WHERE id = %s", (atom_id,))
    row = cur.fetchone()
    conn.close()
    with pg.conn.cursor() as c:
        c.execute("DELETE FROM knowledge WHERE id = %s", (atom_id,))
    pg.conn.commit()
    assert row is not None
    assert row[0] is not None, "embedding should be stored"


def test_knowledge_put_succeeds_when_embed_returns_none():
    from core.pg_bridge import PgBridge
    pg = PgBridge()
    with patch("core.pg_bridge.embed", return_value=None):
        atom_id = pg.gen_id(8)
        pg.knowledge_put({
            "id": atom_id, "project": "test", "title": "no embed",
            "summary": "ollama is down", "source_type": "test",
        })
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT id, embedding FROM knowledge WHERE id = %s", (atom_id,))
    row = cur.fetchone()
    conn.close()
    with pg.conn.cursor() as c:
        c.execute("DELETE FROM knowledge WHERE id = %s", (atom_id,))
    pg.conn.commit()
    assert row is not None, "row must be written even without embedding"
    assert row[1] is None, "embedding should be NULL when embed() returns None"


def test_ingest_opus_atom_embeds_on_write():
    from core.pg_bridge import PgBridge
    pg = PgBridge()
    fake_vec = [0.2] * 768
    with patch("core.pg_bridge.embed", return_value=fake_vec):
        atom_id = pg.ingest_opus_atom("opus content for embedding", domain="test")
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT embedding FROM opus_atoms WHERE id = %s", (atom_id,))
    row = cur.fetchone()
    conn.close()
    with pg.conn.cursor() as c:
        c.execute("DELETE FROM opus_atoms WHERE id = %s", (atom_id,))
    pg.conn.commit()
    assert row is not None
    assert row[0] is not None


def test_jeles_extract_atom_embeds_on_write():
    from core.pg_bridge import PgBridge
    pg = PgBridge()
    fake_vec = [0.3] * 768
    fake_jsonl_id = pg.gen_id(8)
    with patch("core.pg_bridge.embed", return_value=fake_vec):
        result = pg.jeles_extract_atom(
            agent="test", jsonl_id=fake_jsonl_id,
            content="jeles content", title="jeles title",
        )
    atom_id = result["id"]
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT embedding FROM jeles_atoms WHERE id = %s", (atom_id,))
    row = cur.fetchone()
    conn.close()
    with pg.conn.cursor() as c:
        c.execute("DELETE FROM jeles_atoms WHERE id = %s", (atom_id,))
    pg.conn.commit()
    assert row is not None
    assert row[0] is not None


# ── Search tests ──────────────────────────────────────────────────────────────

def test_rrf_merge_combines_ann_and_ilike():
    from core.pg_bridge import _rrf_merge
    ann = [{"id": "A", "title": "ann-only"}, {"id": "B", "title": "both"}]
    ilike = [{"id": "B", "title": "both"}, {"id": "C", "title": "ilike-only"}]
    merged = _rrf_merge(ann, ilike)
    ids = [r["id"] for r in merged]
    assert "A" in ids
    assert "B" in ids
    assert "C" in ids


def test_rrf_merge_shared_result_scores_higher():
    from core.pg_bridge import _rrf_merge
    ann = [{"id": "SHARED"}, {"id": "ANN_ONLY"}]
    ilike = [{"id": "SHARED"}, {"id": "ILIKE_ONLY"}]
    merged = _rrf_merge(ann, ilike)
    ids = [r["id"] for r in merged]
    assert ids[0] == "SHARED", "Shared result should rank first"


def test_knowledge_search_semantic_falls_back_when_embed_none():
    from core.pg_bridge import PgBridge
    pg = PgBridge()
    with patch("core.pg_bridge.embed", return_value=None):
        results = pg.knowledge_search_semantic("test fallback query")
    assert isinstance(results, list)


def test_search_jeles_semantic_days_ago_filter():
    from core.pg_bridge import PgBridge
    pg = PgBridge()
    fake_vec = [0.1] * 768
    with patch("core.pg_bridge.embed", return_value=fake_vec):
        results = pg.search_jeles_semantic("test", days_ago=30)
    assert isinstance(results, list)
