# Semantic Search (SEM01) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire nomic-embed-text (Ollama) into Willow's search paths via pgvector and sqlite-vec, adding hybrid RRF semantic search to knowledge, opus_atoms, jeles_atoms (Postgres) and all SOIL collections (SQLite).

**Architecture:** New `core/embedder.py` provides `embed(text) -> list[float] | None`. Postgres tables get `embedding VECTOR(768)` columns and HNSW indexes via `_MIGRATIONS`/`_INDEXES`. SOIL gets a `records_vec` virtual table per collection via sqlite-vec. `semantic=True` on MCP tools triggers hybrid RRF (ANN + ILIKE merged). Default is `False` — no regressions.

**Tech Stack:** pgvector (`apt install postgresql-16-pgvector`), sqlite-vec (`pip install sqlite-vec`), nomic-embed-text (already in Ollama), psycopg2, requests.

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `core/embedder.py` | **Create** | `embed(text) -> list[float] \| None` — Ollama call, 5s timeout, None-safe |
| `core/pg_bridge.py` | **Modify** | Migrations, write-path embedding, RRF helpers, semantic search methods |
| `core/willow_store.py` | **Modify** | sqlite-vec setup, write/update embedding, `search_semantic()` |
| `sap/sap_mcp.py` | **Modify** | `semantic` flag on 3 tools, dispatch routing, startup backfill check |
| `scripts/willow_embed_backfill.py` | **Create** | Kart-runnable backfill for Postgres + SOIL NULL embeddings |
| `tests/test_embedder.py` | **Create** | embed() unit tests (mock Ollama) |
| `tests/test_pg_bridge_semantic.py` | **Create** | RRF, ANN, fallback, days_ago tests |
| `tests/test_willow_store_semantic.py` | **Create** | SOIL semantic write/update/search tests |
| `tests/test_opus_jeles_semantic.py` | **Create** | opus_atoms and jeles_atoms embed + search tests |

---

## Task 1: core/embedder.py

**Files:**
- Create: `core/embedder.py`
- Create: `tests/test_embedder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embedder.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_embed_returns_768_floats():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"embedding": [0.1] * 768}
    with patch("core.embedder.requests.post", return_value=mock_resp):
        from core.embedder import embed
        result = embed("test text")
    assert isinstance(result, list)
    assert len(result) == 768
    assert all(isinstance(x, float) for x in result)


def test_embed_returns_none_on_connection_failure():
    with patch("core.embedder.requests.post", side_effect=ConnectionError("refused")):
        from core import embedder
        import importlib; importlib.reload(embedder)
        result = embedder.embed("test text")
    assert result is None


def test_embed_returns_none_on_bad_status():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("500 Server Error")
    with patch("core.embedder.requests.post", return_value=mock_resp):
        from core import embedder
        import importlib; importlib.reload(embedder)
        result = embedder.embed("test text")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sean-campbell/github/willow-1.9
python -m pytest tests/test_embedder.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.embedder'`

- [ ] **Step 3: Create core/embedder.py**

```python
# core/embedder.py
import requests

OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "nomic-embed-text"
TIMEOUT_S = 5


def embed(text: str) -> list[float] | None:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": text},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_embedder.py -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add core/embedder.py tests/test_embedder.py
git commit -m "feat(sem): add core/embedder.py — embed() with Ollama nomic-embed-text"
```

---

## Task 2: Postgres migrations — pgvector extension + embedding columns + HNSW indexes

**Files:**
- Modify: `core/pg_bridge.py:206-241` (`_MIGRATIONS` and `_INDEXES`)
- Create: `tests/test_pg_bridge_semantic.py` (schema assertions only in this task)

**Context:** `init_schema()` at line 402 runs `_MIGRATIONS` (ALTER TABLE statements) then `_INDEXES` (CREATE INDEX statements) on every startup. Both are idempotent — `IF NOT EXISTS` / `IF NOT EXISTS`. `CREATE EXTENSION IF NOT EXISTS vector` must come first in `_MIGRATIONS` so the `VECTOR(768)` column type is available when the ALTER TABLE runs.

- [ ] **Step 1: Write the failing schema tests**

```python
# tests/test_pg_bridge_semantic.py
import os
import sys
from pathlib import Path
import pytest
import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent))


def _conn():
    return psycopg2.connect(
        dbname=os.environ.get("WILLOW_PG_DB", "willow_19_test"),
        user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
    )


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pg_bridge_semantic.py::test_knowledge_has_embedding_column -v
```

Expected: FAIL — `AssertionError: knowledge.embedding column missing`

- [ ] **Step 3: Add pgvector extension + embedding columns to _MIGRATIONS**

Open `core/pg_bridge.py`. Find `_MIGRATIONS` at line 206. Add four entries at the start of the list:

```python
_MIGRATIONS = [
    # pgvector — must come before embedding column additions
    "CREATE EXTENSION IF NOT EXISTS vector",
    # embedding columns
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS embedding VECTOR(768)",
    "ALTER TABLE opus_atoms ADD COLUMN IF NOT EXISTS embedding VECTOR(768)",
    "ALTER TABLE jeles_atoms ADD COLUMN IF NOT EXISTS embedding VECTOR(768)",
    # existing migrations below — do not reorder
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS project TEXT NOT NULL DEFAULT 'global'",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS valid_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS invalid_at TIMESTAMPTZ",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS category TEXT",
    "ALTER TABLE frank_ledger ADD COLUMN IF NOT EXISTS project TEXT NOT NULL DEFAULT 'global'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS trust TEXT DEFAULT 'WORKER'",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS folder_root TEXT",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS visit_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS weight FLOAT NOT NULL DEFAULT 1.0",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS last_visited TIMESTAMPTZ",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS fork_id TEXT",
]
```

- [ ] **Step 4: Add HNSW indexes to _INDEXES**

Find `_INDEXES` at line 220. Append three HNSW index statements before the closing `"""`:

```python
_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_knowledge_project ON knowledge (project);
CREATE INDEX IF NOT EXISTS idx_knowledge_valid_at ON knowledge (valid_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_invalid_at ON knowledge (invalid_at)
    WHERE invalid_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_agent_status ON tasks (agent, status);
CREATE INDEX IF NOT EXISTS idx_dispatch_to ON dispatch_tasks (to_agent, status);
CREATE INDEX IF NOT EXISTS idx_dispatch_from ON dispatch_tasks (from_agent);
CREATE INDEX IF NOT EXISTS idx_compact_agent ON compact_contexts (agent);
CREATE INDEX IF NOT EXISTS idx_compact_expires ON compact_contexts (expires_at);
CREATE INDEX IF NOT EXISTS idx_opus_atoms_domain ON opus_atoms (domain);
CREATE INDEX IF NOT EXISTS idx_feedback_domain ON feedback (domain);
CREATE INDEX IF NOT EXISTS idx_jeles_sessions_agent ON jeles_sessions (agent);
CREATE INDEX IF NOT EXISTS idx_jeles_atoms_jsonl ON jeles_atoms (jsonl_id);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_session ON routing_decisions (session_id);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_created ON routing_decisions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_weight ON knowledge (weight DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_visit ON knowledge (visit_count DESC);
CREATE INDEX IF NOT EXISTS idx_forks_status ON forks (status);
CREATE INDEX IF NOT EXISTS idx_forks_created_at ON forks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_fork_id ON knowledge (fork_id) WHERE fork_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS knowledge_embedding_hnsw
    ON knowledge USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS opus_atoms_embedding_hnsw
    ON opus_atoms USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS jeles_atoms_embedding_hnsw
    ON jeles_atoms USING hnsw (embedding vector_cosine_ops);
"""
```

- [ ] **Step 5: Run schema tests**

```bash
python -m pytest tests/test_pg_bridge_semantic.py::test_knowledge_has_embedding_column tests/test_pg_bridge_semantic.py::test_opus_atoms_has_embedding_column tests/test_pg_bridge_semantic.py::test_jeles_atoms_has_embedding_column tests/test_pg_bridge_semantic.py::test_knowledge_hnsw_index_exists -v
```

Expected: 4 PASSED

- [ ] **Step 6: Verify existing pg_bridge tests still pass**

```bash
python -m pytest tests/test_pg_bridge.py -v
```

Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add core/pg_bridge.py tests/test_pg_bridge_semantic.py
git commit -m "feat(sem): add pgvector extension, embedding columns, and HNSW indexes to pg_bridge migrations"
```

---

## Task 3: pg_bridge.py — write-path embedding

**Files:**
- Modify: `core/pg_bridge.py` — `knowledge_put()` (line 546), `ingest_opus_atom()` (line 709), `jeles_extract_atom()` (line 809)
- Modify: `tests/test_pg_bridge_semantic.py` — add write-path tests

**Context:** All three methods write to Postgres. After this task, each write will call `embed()` and include the result in the INSERT. `knowledge_put()` is an upsert (`ON CONFLICT ... DO UPDATE`); the embedding must be refreshed on the update path too. `embed()` returns `None` when Ollama is down — the write must still succeed, with `embedding = NULL`.

- [ ] **Step 1: Add write-path tests to test_pg_bridge_semantic.py**

Append these tests to `tests/test_pg_bridge_semantic.py`:

```python
from unittest.mock import patch


def test_knowledge_put_embeds_on_write():
    """knowledge_put() stores embedding when embed() succeeds."""
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
    pg.conn.cursor().execute("DELETE FROM knowledge WHERE id = %s", (atom_id,))
    pg.conn.commit()
    assert row is not None
    assert row[0] is not None, "embedding should be stored"


def test_knowledge_put_succeeds_when_embed_returns_none():
    """knowledge_put() writes row with NULL embedding when Ollama is down."""
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
    pg.conn.cursor().execute("DELETE FROM knowledge WHERE id = %s", (atom_id,))
    pg.conn.commit()
    assert row is not None, "row must be written even without embedding"
    assert row[1] is None, "embedding should be NULL when embed() returns None"


def test_ingest_opus_atom_embeds_on_write():
    """ingest_opus_atom() stores embedding when embed() succeeds."""
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
    pg.conn.cursor().execute("DELETE FROM opus_atoms WHERE id = %s", (atom_id,))
    pg.conn.commit()
    assert row is not None
    assert row[0] is not None


def test_jeles_extract_atom_embeds_on_write():
    """jeles_extract_atom() stores embedding of title+content."""
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
    pg.conn.cursor().execute("DELETE FROM jeles_atoms WHERE id = %s", (atom_id,))
    pg.conn.commit()
    assert row is not None
    assert row[0] is not None
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python -m pytest tests/test_pg_bridge_semantic.py::test_knowledge_put_embeds_on_write -v
```

Expected: FAIL — `AssertionError: embedding should be stored` (embed not yet wired in)

- [ ] **Step 3: Add embed import to core/pg_bridge.py**

Find the imports block at the top of `core/pg_bridge.py` (around line 8-20). Add after the existing imports:

```python
try:
    from core.embedder import embed as _embed_fn
except ImportError:
    _embed_fn = None


def embed(text: str) -> "list[float] | None":
    if _embed_fn is None:
        return None
    return _embed_fn(text)
```

- [ ] **Step 4: Modify knowledge_put() to embed on write and update**

Find `knowledge_put()` at line 546. Replace the entire method body:

```python
def knowledge_put(self, record: dict) -> str:
    self._ensure_conn()
    title = record.get("title") or ""
    summary = record.get("summary") or ""
    embedding = embed(f"{title} {summary}")
    with self.conn.cursor() as cur:
        cur.execute("""
            INSERT INTO knowledge
                (id, project, valid_at, invalid_at, title, summary, content,
                 source_type, category, embedding)
            VALUES
                (%(id)s, %(project)s, %(valid_at)s, %(invalid_at)s,
                 %(title)s, %(summary)s, %(content)s, %(source_type)s,
                 %(category)s, %(embedding)s)
            ON CONFLICT (id) DO UPDATE SET
                project     = EXCLUDED.project,
                valid_at    = EXCLUDED.valid_at,
                title       = EXCLUDED.title,
                summary     = EXCLUDED.summary,
                content     = EXCLUDED.content,
                source_type = EXCLUDED.source_type,
                category    = EXCLUDED.category,
                embedding   = EXCLUDED.embedding
        """, {
            "id":          record["id"],
            "project":     record.get("project", "global"),
            "valid_at":    record.get("valid_at", datetime.now(timezone.utc)),
            "invalid_at":  record.get("invalid_at"),
            "title":       record.get("title"),
            "summary":     record.get("summary"),
            "content":     psycopg2.extras.Json(record.get("content")),
            "source_type": record.get("source_type"),
            "category":    record.get("category"),
            "embedding":   embedding,
        })
    self.conn.commit()
    return record["id"]
```

- [ ] **Step 5: Modify ingest_opus_atom() to embed on write**

Find `ingest_opus_atom()` at line 709. Replace the INSERT execute and params:

```python
def ingest_opus_atom(self, content: str, domain: str = "meta",
                     depth: int = 1, source_session: Optional[str] = None) -> Optional[str]:
    self._ensure_conn()
    try:
        atom_id = self.gen_id(8)
        embedding = embed(content)
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO opus_atoms (id, content, domain, depth, source_session, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (atom_id, content, domain, depth, source_session, embedding))
        self.conn.commit()
        return atom_id
    except Exception:
        return None
```

- [ ] **Step 6: Modify jeles_extract_atom() to embed on write**

Find `jeles_extract_atom()` at line 809. Replace the INSERT execute and params:

```python
def jeles_extract_atom(self, agent: str, jsonl_id: str, content: str,
                       domain: str = "meta", depth: int = 1,
                       certainty: float = 0.98,
                       title: Optional[str] = None) -> dict:
    self._ensure_conn()
    try:
        aid = self.gen_id(8)
        embedding = embed(f"{title or ''} {content}")
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO jeles_atoms
                    (id, jsonl_id, agent, content, domain, depth, certainty, title, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (aid, jsonl_id, agent, content, domain, depth, certainty, title, embedding))
        self.conn.commit()
        return {"id": aid, "status": "extracted"}
    except Exception as e:
        return {"error": str(e)}
```

- [ ] **Step 7: Run write-path tests**

```bash
python -m pytest tests/test_pg_bridge_semantic.py -k "write or embed or put or ingest or extract" -v
```

Expected: all 4 new tests PASS

- [ ] **Step 8: Run full pg_bridge test suite to check for regressions**

```bash
python -m pytest tests/test_pg_bridge.py tests/test_pg_bridge_semantic.py -v
```

Expected: all PASSED

- [ ] **Step 9: Commit**

```bash
git add core/pg_bridge.py tests/test_pg_bridge_semantic.py
git commit -m "feat(sem): embed on write — knowledge_put, ingest_opus_atom, jeles_extract_atom"
```

---

## Task 4: pg_bridge.py — semantic search (RRF + ANN + search methods)

**Files:**
- Modify: `core/pg_bridge.py` — add `_rrf_merge()`, `_knowledge_ann()`, `knowledge_search_semantic()`, `search_opus_semantic()`, `search_jeles_semantic()`
- Modify: `tests/test_pg_bridge_semantic.py` — add search tests

- [ ] **Step 1: Add search tests to test_pg_bridge_semantic.py**

Append to `tests/test_pg_bridge_semantic.py`:

```python
def test_rrf_merge_combines_ann_and_ilike():
    """RRF merge: result present in only ANN list still appears in output."""
    from core.pg_bridge import _rrf_merge
    ann = [{"id": "A", "title": "ann-only"}, {"id": "B", "title": "both"}]
    ilike = [{"id": "B", "title": "both"}, {"id": "C", "title": "ilike-only"}]
    merged = _rrf_merge(ann, ilike)
    ids = [r["id"] for r in merged]
    assert "A" in ids, "ANN-only result must appear"
    assert "B" in ids, "shared result must appear"
    assert "C" in ids, "ILIKE-only result must appear"


def test_rrf_merge_shared_result_scores_higher():
    """RRF: result in both lists scores higher than result in only one."""
    from core.pg_bridge import _rrf_merge
    ann = [{"id": "SHARED"}, {"id": "ANN_ONLY"}]
    ilike = [{"id": "SHARED"}, {"id": "ILIKE_ONLY"}]
    merged = _rrf_merge(ann, ilike)
    ids = [r["id"] for r in merged]
    assert ids[0] == "SHARED", "Shared result should rank first"


def test_knowledge_search_semantic_falls_back_when_embed_none():
    """knowledge_search_semantic falls back to ILIKE when embed() returns None."""
    from core.pg_bridge import PgBridge
    pg = PgBridge()
    with patch("core.pg_bridge.embed", return_value=None):
        results = pg.knowledge_search_semantic("test fallback query")
    # Should not raise; returns list (may be empty in test DB)
    assert isinstance(results, list)


def test_search_jeles_semantic_days_ago_filter():
    """search_jeles_semantic with days_ago limits to recent atoms."""
    from core.pg_bridge import PgBridge
    import datetime as dt
    pg = PgBridge()
    fake_vec = [0.1] * 768
    with patch("core.pg_bridge.embed", return_value=fake_vec):
        # Should not raise; returns list
        results = pg.search_jeles_semantic("test", days_ago=30)
    assert isinstance(results, list)
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python -m pytest tests/test_pg_bridge_semantic.py::test_rrf_merge_combines_ann_and_ilike -v
```

Expected: FAIL — `ImportError: cannot import name '_rrf_merge' from 'core.pg_bridge'`

- [ ] **Step 3: Add _rrf_merge() to core/pg_bridge.py**

Add this module-level function after the `embed()` wrapper (added in Task 3):

```python
def _rrf_merge(ann_results: list, ilike_results: list, k: int = 60) -> list:
    scores: dict[str, dict] = {}
    for rank, row in enumerate(ann_results):
        rid = row["id"]
        scores.setdefault(rid, {"row": row, "score": 0.0})
        scores[rid]["score"] += 1.0 / (k + rank + 1)
    for rank, row in enumerate(ilike_results):
        rid = row["id"]
        scores.setdefault(rid, {"row": row, "score": 0.0})
        scores[rid]["score"] += 1.0 / (k + rank + 1)
    return [v["row"] for v in sorted(scores.values(), key=lambda x: -x["score"])]
```

- [ ] **Step 4: Add _knowledge_ann() to PgBridge class**

Add this method to `PgBridge`, after `knowledge_search()` at line ~640:

```python
def _knowledge_ann(self, vec: list, limit: int, project: "str | None") -> list:
    self._ensure_conn()
    filters = ["embedding IS NOT NULL", "invalid_at IS NULL"]
    params: list = [vec, limit]
    if project:
        filters.insert(1, "project = %s")
        params.insert(1, project)
    where = " AND ".join(filters)
    with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""
            SELECT *, embedding <=> %s AS distance
            FROM knowledge WHERE {where}
            ORDER BY distance ASC LIMIT %s
        """, params)
        return [dict(r) for r in cur.fetchall()]
```

- [ ] **Step 5: Add knowledge_search_semantic() to PgBridge**

Add after `_knowledge_ann()`:

```python
def knowledge_search_semantic(self, query: str, limit: int = 20,
                               project: "str | None" = None) -> list:
    vec = embed(query)
    if vec is None:
        return self.knowledge_search(query, limit=limit, project=project)
    ann = self._knowledge_ann(vec, limit=limit, project=project)
    ilike = self.knowledge_search(query, limit=limit, project=project)
    return _rrf_merge(ann, ilike)[:limit]
```

- [ ] **Step 6: Add search_opus_semantic() to PgBridge**

Add after `search_opus()` at line ~707:

```python
def search_opus_semantic(self, query: str, limit: int = 20) -> list:
    vec = embed(query)
    if vec is None:
        return self.search_opus(query, limit=limit)
    ann_results: list = []
    self._ensure_conn()
    with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT *, embedding <=> %s AS distance
            FROM opus_atoms WHERE embedding IS NOT NULL
            ORDER BY distance ASC LIMIT %s
        """, (vec, limit))
        ann_results = [dict(r) for r in cur.fetchall()]
    ilike_results = self.search_opus(query, limit=limit)
    return _rrf_merge(ann_results, ilike_results)[:limit]
```

- [ ] **Step 7: Add search_jeles_semantic() to PgBridge**

Add after `jeles_extract_atom()`:

```python
def search_jeles_semantic(self, query: str, limit: int = 20,
                           days_ago: "int | None" = None) -> list:
    vec = embed(query)
    ann_results: list = []
    self._ensure_conn()
    if vec is not None:
        filters = ["embedding IS NOT NULL"]
        params: list = [vec, limit]
        if days_ago is not None:
            filters.append("created_at > now() - interval '%s days'" % int(days_ago))
        where = " AND ".join(filters)
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT *, embedding <=> %s AS distance
                FROM jeles_atoms WHERE {where}
                ORDER BY distance ASC LIMIT %s
            """, params)
            ann_results = [dict(r) for r in cur.fetchall()]

    # ILIKE fallback leg
    date_filter = ""
    ilike_params: list = [f"%{query}%", f"%{query}%", limit]
    if days_ago is not None:
        date_filter = "AND created_at > now() - interval '%s days'" % int(days_ago)
    self._ensure_conn()
    with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""
            SELECT * FROM jeles_atoms
            WHERE (content ILIKE %s OR COALESCE(title, '') ILIKE %s)
            {date_filter}
            ORDER BY created_at DESC LIMIT %s
        """, ilike_params)
        ilike_results = [dict(r) for r in cur.fetchall()]

    if vec is None:
        return ilike_results
    return _rrf_merge(ann_results, ilike_results)[:limit]
```

- [ ] **Step 8: Run all semantic search tests**

```bash
python -m pytest tests/test_pg_bridge_semantic.py -v
```

Expected: all PASSED

- [ ] **Step 9: Run full suite for regressions**

```bash
python -m pytest tests/test_pg_bridge.py tests/test_pg_bridge_semantic.py -v
```

Expected: all PASSED

- [ ] **Step 10: Commit**

```bash
git add core/pg_bridge.py tests/test_pg_bridge_semantic.py
git commit -m "feat(sem): add RRF helpers and semantic search methods to pg_bridge"
```

---

## Task 5: willow_store.py — sqlite-vec setup + embed on put/update

**Files:**
- Modify: `core/willow_store.py`
- Create: `tests/test_willow_store_semantic.py`

**Context:** sqlite-vec is loaded via `conn.enable_load_extension(True); sqlite_vec.load(conn)`. The `records_vec` virtual table is created per-collection inside `_conn()`. Embedding happens *after* the main record write (outside the `self._lock` block) to avoid holding the write lock during the Ollama HTTP call. If Ollama is down on `update()`, the stale `records_vec` row is deleted so backfill picks it up.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_willow_store_semantic.py
import sys
import json
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    import importlib
    import core.willow_store as ws
    importlib.reload(ws)
    return ws.WillowStore()


def test_put_embeds_record(store):
    """put() inserts a row into records_vec when embed() succeeds."""
    fake_vec = [0.1] * 768
    with patch("core.willow_store.embed", return_value=fake_vec):
        rid, _, _ = store.put("test/col", {"id": "rec1", "text": "hello world"})
    conn = store._conn("test/col")
    row = conn.execute(
        "SELECT rowid FROM records WHERE id = ?", (rid,)
    ).fetchone()
    vec_row = conn.execute(
        "SELECT rowid FROM records_vec WHERE rowid = ?", (row[0],)
    ).fetchone() if row else None
    conn.close()
    assert vec_row is not None, "records_vec entry missing after put()"


def test_put_succeeds_without_sqlite_vec(store, monkeypatch):
    """put() writes record even when sqlite-vec is unavailable."""
    import core.willow_store as ws
    monkeypatch.setattr(ws, "_SQLITE_VEC_AVAILABLE", False)
    rid, _, _ = store.put("test/col", {"id": "rec2", "text": "no vec"})
    record = store.get("test/col", rid)
    assert record is not None


def test_update_refreshes_vec(store):
    """update() upserts records_vec with fresh embedding."""
    fake_vec = [0.1] * 768
    with patch("core.willow_store.embed", return_value=fake_vec):
        store.put("test/col", {"id": "rec3", "text": "original"})
    new_vec = [0.9] * 768
    with patch("core.willow_store.embed", return_value=new_vec):
        store.update("test/col", "rec3", {"text": "updated"})
    conn = store._conn("test/col")
    row = conn.execute("SELECT rowid FROM records WHERE id = ?", ("rec3",)).fetchone()
    vec_count = conn.execute(
        "SELECT COUNT(*) FROM records_vec WHERE rowid = ?", (row[0],)
    ).fetchone()[0] if row else 0
    conn.close()
    assert vec_count == 1, "records_vec should have exactly one row after update"


def test_update_deletes_stale_vec_when_ollama_down(store):
    """update() deletes records_vec row when embed() returns None."""
    fake_vec = [0.1] * 768
    with patch("core.willow_store.embed", return_value=fake_vec):
        store.put("test/col", {"id": "rec4", "text": "will go stale"})
    with patch("core.willow_store.embed", return_value=None):
        store.update("test/col", "rec4", {"text": "ollama down on update"})
    conn = store._conn("test/col")
    row = conn.execute("SELECT rowid FROM records WHERE id = ?", ("rec4",)).fetchone()
    vec_count = conn.execute(
        "SELECT COUNT(*) FROM records_vec WHERE rowid = ?", (row[0],)
    ).fetchone()[0] if row else 0
    conn.close()
    assert vec_count == 0, "stale records_vec row must be deleted when embed() returns None"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_willow_store_semantic.py::test_put_embeds_record -v
```

Expected: FAIL — `OperationalError` or `AssertionError: records_vec entry missing`

- [ ] **Step 3: Add sqlite-vec import guard to willow_store.py**

At the top of `core/willow_store.py`, after the existing imports (around line 22), add:

```python
_SQLITE_VEC_AVAILABLE = False
try:
    import sqlite_vec as _sqlite_vec
    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    pass

try:
    from core.embedder import embed
except ImportError:
    def embed(text):  # type: ignore[misc]
        return None
```

- [ ] **Step 4: Add _ensure_records_vec() helper function**

Add this module-level function after the existing module-level helpers (around line 120, before `_ensure_columns`):

```python
def _ensure_records_vec(conn: sqlite3.Connection) -> None:
    if not _SQLITE_VEC_AVAILABLE:
        return
    conn.enable_load_extension(True)
    _sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS records_vec
        USING vec0(embedding float[768])
    """)
    conn.commit()
```

- [ ] **Step 5: Call _ensure_records_vec in _conn()**

Find `_conn()` at line 175. After `_ensure_columns(conn)` at line 190, add:

```python
    _ensure_columns(conn)
    _ensure_records_vec(conn)
    return conn
```

- [ ] **Step 6: Add embedding to put() after lock release**

Find `put()` at line 200. After `self._hebbian_auto_link(collection, record)` (before `return rid, action, []`), add:

```python
        if _SQLITE_VEC_AVAILABLE:
            vec = embed(json.dumps(record, default=str)[:2000])
            if vec is not None:
                try:
                    conn2 = self._conn(collection)
                    row = conn2.execute(
                        "SELECT rowid FROM records WHERE id = ?", (rid,)
                    ).fetchone()
                    if row:
                        conn2.execute(
                            "INSERT OR REPLACE INTO records_vec(rowid, embedding) VALUES (?, ?)",
                            (row[0], _sqlite_vec.serialize_float32(vec)),
                        )
                        conn2.commit()
                    conn2.close()
                except Exception:
                    pass
```

- [ ] **Step 7: Add embedding refresh to update() after lock release**

Find `update()` at line 292. The method currently returns `rid, action, []` at line 324. Before the `return`, add:

```python
        if _SQLITE_VEC_AVAILABLE:
            try:
                conn2 = self._conn(collection)
                db_row = conn2.execute(
                    "SELECT rowid, data FROM records WHERE id = ?", (rid,)
                ).fetchone()
                if db_row:
                    vec = embed(db_row["data"][:2000])
                    if vec is not None:
                        conn2.execute(
                            "INSERT OR REPLACE INTO records_vec(rowid, embedding) VALUES (?, ?)",
                            (db_row["rowid"], _sqlite_vec.serialize_float32(vec)),
                        )
                    else:
                        conn2.execute(
                            "DELETE FROM records_vec WHERE rowid = ?", (db_row["rowid"],)
                        )
                    conn2.commit()
                conn2.close()
            except Exception:
                pass
```

- [ ] **Step 8: Run willow_store semantic tests**

```bash
python -m pytest tests/test_willow_store_semantic.py -v
```

Expected: all PASSED (skip `test_put_embeds_record` if sqlite-vec not installed — note below)

> **Note on sqlite-vec install:** If `pip install sqlite-vec` has not been run, the `_SQLITE_VEC_AVAILABLE` tests will pass vacuously (no vec table). Install with `pip install sqlite-vec` to test the full path.

- [ ] **Step 9: Run full willow_store suite for regressions**

```bash
python -m pytest tests/test_willow_store.py tests/test_willow_store_semantic.py -v
```

Expected: all PASSED

- [ ] **Step 10: Commit**

```bash
git add core/willow_store.py tests/test_willow_store_semantic.py
git commit -m "feat(sem): add sqlite-vec setup and write-path embedding to willow_store"
```

---

## Task 6: willow_store.py — search_semantic()

**Files:**
- Modify: `core/willow_store.py` — add `search_semantic()`
- Modify: `tests/test_willow_store_semantic.py` — add search tests

- [ ] **Step 1: Add search tests**

Append to `tests/test_willow_store_semantic.py`:

```python
def test_search_semantic_returns_knn_results(store):
    """search_semantic() returns records ordered by vector distance."""
    fake_vec = [0.1] * 768
    with patch("core.willow_store.embed", return_value=fake_vec):
        store.put("test/col", {"id": "r1", "text": "apple"})
        store.put("test/col", {"id": "r2", "text": "orange"})
        results = store.search_semantic("test/col", "fruit", limit=5)
    assert isinstance(results, list)


def test_search_semantic_falls_back_when_embed_none(store):
    """search_semantic falls back to substring search when embed() returns None."""
    store.put("test/col", {"id": "r5", "text": "fallback test record"})
    with patch("core.willow_store.embed", return_value=None):
        results = store.search_semantic("test/col", "fallback")
    assert any("fallback" in json.dumps(r) for r in results)


def test_search_semantic_falls_back_when_no_sqlite_vec(store, monkeypatch):
    """search_semantic falls back when sqlite-vec is unavailable."""
    import core.willow_store as ws
    monkeypatch.setattr(ws, "_SQLITE_VEC_AVAILABLE", False)
    store.put("test/col", {"id": "r6", "text": "no vec fallback"})
    results = store.search_semantic("test/col", "no vec fallback")
    assert isinstance(results, list)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_willow_store_semantic.py::test_search_semantic_returns_knn_results -v
```

Expected: FAIL — `AttributeError: 'WillowStore' object has no attribute 'search_semantic'`

- [ ] **Step 3: Add search_semantic() to WillowStore**

Add this method to `WillowStore` after `search_all()` (around line 382):

```python
def search_semantic(self, collection: str, query: str, limit: int = 20) -> list:
    if not _SQLITE_VEC_AVAILABLE:
        return self.search(collection, query)
    vec = embed(query)
    if vec is None:
        return self.search(collection, query)
    try:
        conn = self._conn(collection)
        rows = conn.execute("""
            SELECT r.data, rv.distance
            FROM records r
            JOIN (
                SELECT rowid, distance FROM records_vec
                WHERE embedding MATCH ? AND k = ?
            ) rv ON rv.rowid = r.rowid
            WHERE r.deleted = 0
            ORDER BY rv.distance
        """, (_sqlite_vec.serialize_float32(vec), limit)).fetchall()
        conn.close()
        return [json.loads(row["data"]) for row in rows]
    except Exception:
        return self.search(collection, query)
```

- [ ] **Step 4: Run all SOIL semantic tests**

```bash
python -m pytest tests/test_willow_store_semantic.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add core/willow_store.py tests/test_willow_store_semantic.py
git commit -m "feat(sem): add search_semantic() to WillowStore — sqlite-vec KNN with substring fallback"
```

---

## Task 7: sap_mcp.py — semantic flag on tools + dispatch + startup backfill

**Files:**
- Modify: `sap/sap_mcp.py` — tool schemas (lines 210-221, 314-324, 628-638), dispatch handlers (lines 1020-1026, 1074-1092, 1537-1542), startup backfill (after line 110)

- [ ] **Step 1: Add semantic parameter to store_search tool schema**

Find the `store_search` tool definition at line 210. Replace `inputSchema`:

```python
        types.Tool(
            name="store_search",
            description="Full-text search within a single collection. Multi-keyword queries are ANDed. Prefer willow_knowledge_search for the Postgres KB.",
            inputSchema={
                "type": "object",
                "properties": {
                    "collection": {"type": "string", "description": "Collection path to search within, e.g. 'hanuman/atoms'"},
                    "query": {"type": "string", "description": "Search terms — multiple words are ANDed"},
                    "after": {"type": "string", "description": "Optional ISO timestamp. Only return records whose 'timestamp' or 'date' field is strictly after this value."},
                    "semantic": {"type": "boolean", "default": False, "description": "If true, use hybrid ANN+substring search via sqlite-vec. Falls back to substring if Ollama is down."},
                },
                "required": ["collection", "query"],
            },
        ),
```

- [ ] **Step 2: Add semantic parameter to willow_knowledge_search tool schema**

Find `willow_knowledge_search` tool at line 314. Replace `inputSchema`:

```python
        types.Tool(
            name="willow_knowledge_search",
            description="Search Willow's Postgres knowledge graph (atoms, entities, ganesha). Returns pointers (title + path), not raw content. Use store_get to fetch the full record.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query — plain text, matched against title and summary"},
                    "limit": {"type": "integer", "default": 20, "description": "Maximum results to return across atoms, entities, and ganesha (default 20)"},
                    "semantic": {"type": "boolean", "default": False, "description": "If true, use hybrid RRF (ANN + ILIKE) via pgvector. Falls back to ILIKE if Ollama is down."},
                },
                "required": ["query"],
            },
        ),
```

- [ ] **Step 3: Add semantic parameter to opus_search tool schema**

Find `opus_search` tool at line 628. Replace `inputSchema`:

```python
        types.Tool(
            name="opus_search",
            description="Search opus.atoms by title or content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query — matched against opus atom title and content"},
                    "limit": {"type": "integer", "default": 20, "description": "Maximum results to return (default 20)"},
                    "semantic": {"type": "boolean", "default": False, "description": "If true, use hybrid RRF (ANN + ILIKE) via pgvector. Falls back to ILIKE if Ollama is down."},
                },
                "required": ["query"],
            },
        ),
```

- [ ] **Step 4: Update store_search dispatch handler**

Find the `store_search` handler at line 1020. Replace:

```python
        elif name == "store_search":
            if arguments.get("semantic"):
                result = store.search_semantic(
                    arguments["collection"],
                    arguments["query"],
                    limit=arguments.get("limit", 20),
                )
            else:
                result = store.search(
                    arguments["collection"],
                    arguments["query"],
                    after=arguments.get("after"),
                )
            _sanitize_result(result, f"store_search:{arguments['collection']}")
```

- [ ] **Step 5: Update willow_knowledge_search dispatch handler**

Find the `willow_knowledge_search` / `willow_query` handler at line 1074. Replace the inner logic:

```python
        elif name in ("willow_knowledge_search", "willow_query"):
            if not pg:
                result = {"error": "not_available", "reason": "Postgres not connected"}
            else:
                query = arguments["query"]
                limit = arguments.get("limit", 20)
                if arguments.get("semantic"):
                    knowledge = pg.knowledge_search_semantic(query, limit=limit)
                else:
                    knowledge = pg.knowledge_search(query, limit=limit)
                result = {
                    "knowledge": knowledge,
                    "ganesha_atoms": [],
                    "entities": [],
                    "total": len(knowledge),
                }
                _sanitize_result(result, "willow_knowledge_search")
                for atom in knowledge[:3]:
                    try:
                        pg.promote(atom["id"])
                    except Exception:
                        pass
```

- [ ] **Step 6: Update opus_search dispatch handler**

Find the `opus_search` handler at line 1537. Replace:

```python
        elif name == "opus_search":
            if not pg:
                result = {"error": "not_available", "reason": "Postgres not connected"}
            else:
                if arguments.get("semantic"):
                    results = pg.search_opus_semantic(
                        arguments["query"], arguments.get("limit", 20)
                    )
                else:
                    results = pg.search_opus(
                        arguments["query"], arguments.get("limit", 20)
                    )
                result = {"results": results, "count": len(results)}
```

- [ ] **Step 7: Add startup backfill check**

Find lines 109-113 in `sap/sap_mcp.py`:

```python
try:
    from pg_bridge import try_connect, PgBridge, init_schema
    pg = PgBridge()
    init_schema(pg.conn)
except Exception as _pg_init_err:
    pg = None
    print(f"[pg] PgBridge init failed: {_pg_init_err}", file=sys.stderr)
```

Replace with:

```python
try:
    from pg_bridge import try_connect, PgBridge, init_schema
    pg = PgBridge()
    init_schema(pg.conn)
    # Auto-queue embedding backfill if any tables have NULL embeddings
    try:
        with pg.conn.cursor() as _bfc:
            _bfc.execute("""
                SELECT (SELECT COUNT(*) FROM knowledge WHERE embedding IS NULL) +
                       (SELECT COUNT(*) FROM opus_atoms WHERE embedding IS NULL) +
                       (SELECT COUNT(*) FROM jeles_atoms WHERE embedding IS NULL)
                AS total_unembedded
            """)
            _unembedded = (_bfc.fetchone() or [0])[0]
        if _unembedded > 0:
            pg.submit_task(
                f"python3 scripts/willow_embed_backfill.py",
                submitted_by="sap",
                agent="kart",
            )
            print(f"[sem] {_unembedded} unembedded rows — backfill queued", file=sys.stderr)
    except Exception as _bfe:
        print(f"[sem] backfill check failed (non-fatal): {_bfe}", file=sys.stderr)
except Exception as _pg_init_err:
    pg = None
    print(f"[pg] PgBridge init failed: {_pg_init_err}", file=sys.stderr)
```

- [ ] **Step 8: Verify sap_mcp.py starts without error**

```bash
cd /home/sean-campbell/github/willow-1.9
python -c "import sap.sap_mcp" 2>&1 | head -20
```

Expected: no ImportError or SyntaxError. May see `[pg] PgBridge init failed:` if DB is not running — that's fine.

- [ ] **Step 9: Commit**

```bash
git add sap/sap_mcp.py
git commit -m "feat(sem): add semantic flag to MCP tools and startup backfill check"
```

---

## Task 8: scripts/willow_embed_backfill.py

**Files:**
- Create: `scripts/willow_embed_backfill.py`

**Context:** This script is submitted as a Kart task by the startup backfill check. It processes Postgres tables (knowledge, opus_atoms, jeles_atoms) and SOIL collections in batches of 100 with 50ms sleep between batches. SOIL collections are enumerated via `store.collections()` which does `root.rglob("*.db")`. For SOIL, unembedded records are found via `LEFT JOIN records_vec ON rv.rowid = r.rowid WHERE rv.rowid IS NULL`.

- [ ] **Step 1: Ensure scripts/ directory exists**

```bash
ls /home/sean-campbell/github/willow-1.9/scripts/ 2>/dev/null || mkdir /home/sean-campbell/github/willow-1.9/scripts
```

- [ ] **Step 2: Create the backfill script**

```python
#!/usr/bin/env python3
"""willow_embed_backfill.py — embed NULL rows in Postgres + SOIL collections.

Submitted as a Kart task by sap_mcp.py at startup when unembedded rows exist.
Run directly: python3 scripts/willow_embed_backfill.py [--dry-run]
"""
import sys
import time
import json
import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.embedder import embed
from core.pg_bridge import PgBridge
from core.willow_store import WillowStore

BATCH_SIZE = 100
SLEEP_S = 0.05


def _pg_backfill_table(pg, table: str, text_col: str, dry_run: bool) -> int:
    """Embed NULL rows in a Postgres table. Returns count processed."""
    processed = 0
    while True:
        with pg.conn.cursor() as cur:
            cur.execute(
                f"SELECT id, {text_col} FROM {table} WHERE embedding IS NULL LIMIT %s",
                (BATCH_SIZE,),
            )
            rows = cur.fetchall()
        if not rows:
            break
        for row_id, text in rows:
            if not text:
                continue
            vec = embed(str(text))
            if vec is None:
                continue
            if not dry_run:
                with pg.conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE {table} SET embedding = %s WHERE id = %s",
                        (vec, row_id),
                    )
                pg.conn.commit()
            processed += 1
        print(f"  [{table}] batch done — {processed} processed so far")
        time.sleep(SLEEP_S)
    return processed


def _knowledge_text(pg) -> None:
    """knowledge table uses title+summary as embed input."""
    processed = 0
    while True:
        with pg.conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, summary FROM knowledge WHERE embedding IS NULL LIMIT %s",
                (BATCH_SIZE,),
            )
            rows = cur.fetchall()
        if not rows:
            break
        for row_id, title, summary in rows:
            text = f"{title or ''} {summary or ''}".strip()
            if not text:
                continue
            vec = embed(text)
            if vec is None:
                continue
            with pg.conn.cursor() as cur:
                cur.execute(
                    "UPDATE knowledge SET embedding = %s WHERE id = %s",
                    (vec, row_id),
                )
            pg.conn.commit()
            processed += 1
        print(f"  [knowledge] batch done — {processed} processed")
        time.sleep(SLEEP_S)
    return processed


def _soil_backfill(store: WillowStore, dry_run: bool) -> int:
    try:
        import sqlite_vec
    except ImportError:
        print("  [SOIL] sqlite-vec not available — skipping SOIL backfill")
        return 0

    processed = 0
    for collection in store.collections():
        try:
            conn = store._conn(collection)
            # Records with no corresponding records_vec row
            rows = conn.execute("""
                SELECT r.rowid, r.data FROM records r
                LEFT JOIN records_vec rv ON rv.rowid = r.rowid
                WHERE rv.rowid IS NULL AND r.deleted = 0
                LIMIT ?
            """, (BATCH_SIZE,)).fetchall()
            while rows:
                for row in rows:
                    text = row["data"][:2000]
                    vec = embed(text)
                    if vec is None:
                        continue
                    if not dry_run:
                        conn.execute(
                            "INSERT OR REPLACE INTO records_vec(rowid, embedding) VALUES (?, ?)",
                            (row["rowid"], sqlite_vec.serialize_float32(vec)),
                        )
                        conn.commit()
                    processed += 1
                print(f"  [SOIL:{collection}] batch done — {processed} total")
                time.sleep(SLEEP_S)
                rows = conn.execute("""
                    SELECT r.rowid, r.data FROM records r
                    LEFT JOIN records_vec rv ON rv.rowid = r.rowid
                    WHERE rv.rowid IS NULL AND r.deleted = 0
                    LIMIT ?
                """, (BATCH_SIZE,)).fetchall()
            conn.close()
        except Exception as e:
            print(f"  [SOIL:{collection}] error: {e}")

    return processed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Count unembedded rows without writing")
    args = parser.parse_args()

    pg = PgBridge()
    store = WillowStore()

    print("=== willow_embed_backfill ===")
    if args.dry_run:
        print("DRY RUN — no writes")

    total = 0
    total += _knowledge_text(pg) if not args.dry_run else 0
    total += _pg_backfill_table(pg, "opus_atoms", "content", args.dry_run)
    total += _pg_backfill_table(pg, "jeles_atoms", "content", args.dry_run)
    total += _soil_backfill(store, args.dry_run)

    print(f"=== done — {total} rows embedded ===")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Test dry-run mode**

```bash
cd /home/sean-campbell/github/willow-1.9
python3 scripts/willow_embed_backfill.py --dry-run
```

Expected: prints `=== willow_embed_backfill ===`, `DRY RUN — no writes`, and `=== done — 0 rows embedded ===` (or counts from any real NULL rows). No writes occur.

- [ ] **Step 4: Commit**

```bash
git add scripts/willow_embed_backfill.py
git commit -m "feat(sem): add willow_embed_backfill script — batched Postgres + SOIL backfill for NULL embeddings"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| `core/embedder.py` — `embed(text) -> list[float] \| None`, 5s timeout, None on failure | Task 1 |
| `knowledge.embedding VECTOR(768)` + HNSW | Task 2 |
| `opus_atoms.embedding VECTOR(768)` + HNSW | Task 2 |
| `jeles_atoms.embedding VECTOR(768)` + HNSW | Task 2 |
| `records_vec` virtual table per SOIL collection | Task 5 |
| `knowledge_put()` embeds on write AND update | Task 3 |
| `ingest_opus_atom()` embeds on write | Task 3 |
| `jeles_extract_atom()` embeds on write | Task 3 |
| `store.put()` embeds after write | Task 5 |
| `store.update()` refreshes / deletes stale vec | Task 5 |
| `_rrf_merge()` | Task 4 |
| `_knowledge_ann()` | Task 4 |
| `knowledge_search_semantic()` — hybrid RRF | Task 4 |
| `search_opus_semantic()` — hybrid RRF | Task 4 |
| `search_jeles_semantic(days_ago=None)` — hybrid + time filter | Task 4 |
| `search_semantic()` on WillowStore — sqlite-vec KNN | Task 6 |
| `semantic: bool = False` on `willow_knowledge_search` MCP tool | Task 7 |
| `semantic: bool = False` on `store_search` MCP tool | Task 7 |
| `semantic: bool = False` on `opus_search` MCP tool | Task 7 |
| Startup backfill check → auto-submit Kart task | Task 7 |
| `willow_embed_backfill` script — Postgres batches | Task 8 |
| `willow_embed_backfill` script — SOIL via `store.collections()` + LEFT JOIN records_vec | Task 8 |
| Fallback: Ollama down → ILIKE/substring | Tasks 3, 4, 5, 6 |
| Fallback: semantic=False → existing behavior | Task 7 |

All spec requirements covered. No placeholders.

**Type/name consistency check:** `embed` function imported consistently as `embed` in both pg_bridge and willow_store. `_rrf_merge` is module-level (not a method) — referenced correctly in `knowledge_search_semantic`, `search_opus_semantic`. `_sqlite_vec` (the module) vs `_SQLITE_VEC_AVAILABLE` (the flag) — consistent throughout.
