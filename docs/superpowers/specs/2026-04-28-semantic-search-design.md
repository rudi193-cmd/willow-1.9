# Semantic Search (ANN) — Design Spec
**Date:** 2026-04-28 | **Status:** Approved | **b17:** SEM01

## What It Is

Adds approximate nearest-neighbor (ANN) semantic search to both Willow knowledge stores — the Postgres `knowledge` table (LOAM) and the SOIL SQLite store. Uses `nomic-embed-text` via the local Ollama instance (already running) to generate 768-dimensional embeddings at write time. Replaces neither store nor any existing search path — adds a `semantic=true` flag alongside current ILIKE/substring search.

## Motivation

Current `knowledge_search` (`pg_bridge.py:610`) is `ILIKE %query%` on title and summary. Current SOIL `search()` (`willow_store.py:353`) is a full Python scan of all records. Both miss semantically related content when exact words don't match. With 209K KB atoms and 2.1M SOIL records, the substring scan is also a performance problem.

`nomic-embed-text` is already running in Ollama. This spec wires it in.

## Architecture

```
write path:
  knowledge_put(title, summary, ...) → embed(title + summary) → store embedding in knowledge.embedding
  store_put(collection, record)      → embed(record_json[:2000]) → store in records_vec virtual table

search path (semantic=True):
  willow_knowledge_search(query, semantic=True) → embed(query) → ANN via pgvector → ranked results
  store_search(collection, query, semantic=True) → embed(query) → ANN via sqlite-vec → ranked results

fallback:
  Ollama down OR embedding IS NULL → falls back to existing ILIKE/substring search
  semantic=False (default)         → existing behavior, unchanged
```

## Components

| Component | Change |
|-----------|--------|
| `core/embedder.py` | **New.** Single `embed(text) -> list[float] \| None` function. Calls Ollama `/api/embeddings`, 5s timeout, returns `None` on any failure. |
| `core/pg_bridge.py` | `knowledge_put()` embeds on write. New `knowledge_search_semantic()` method using `<=>` cosine operator. |
| `core/willow_store.py` | `store_put()` embeds on write into `records_vec` virtual table. New `search_semantic()` method using sqlite-vec KNN. |
| `sap/sap_mcp.py` | Add `semantic: bool = False` parameter to `willow_knowledge_search` and `store_search` MCP tools. |

One new file. Targeted edits to three existing files. No new processes, no new services.

## Data Model

### Postgres

```sql
-- Enable extension (run once per DB)
CREATE EXTENSION IF NOT EXISTS vector;

-- Nullable column — existing rows keep NULL until backfill
ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS embedding VECTOR(768);

-- HNSW index — builds incrementally, no minimum row count
CREATE INDEX IF NOT EXISTS knowledge_embedding_hnsw
  ON knowledge USING hnsw (embedding vector_cosine_ops);
```

HNSW chosen over IVFFlat: no training phase required, works correctly on small collections, better recall at equivalent query latency.

### SOIL SQLite

Each collection's SQLite file gets a shadow virtual table linked by rowid:

```sql
-- Loaded when sqlite-vec extension is available
CREATE VIRTUAL TABLE IF NOT EXISTS records_vec
  USING vec0(embedding float[768]);
```

No new columns on the `records` table itself. Vector storage is fully managed by sqlite-vec's virtual table mechanism.

## Embedding Pipeline

### `core/embedder.py`

```python
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "nomic-embed-text"
TIMEOUT_S = 5

def embed(text: str) -> list[float] | None:
    try:
        resp = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": text}, timeout=TIMEOUT_S)
        resp.raise_for_status()
        return resp.json()["embedding"]  # list[float], len=768
    except Exception:
        return None
```

### What gets embedded

| Store | Input |
|-------|-------|
| `knowledge` | `f"{title} {summary}"` |
| SOIL | `record_json[:2000]` (truncated to avoid token limits) |

### Write behavior

Embedding is attempted after the record is written. If `embed()` returns `None`, the row is persisted without an embedding — the write never fails due to Ollama being unavailable.

### Backfill

Existing records (209K KB atoms + 2.1M SOIL records) are **not** backfilled at startup. A `willow_embed_backfill` Kart task — submitted manually — processes rows with `embedding IS NULL` in batches of 100 with a 50ms sleep between batches. Old records remain findable via substring search until backfilled.

## Search Path

### Postgres semantic search

```python
def knowledge_search_semantic(self, query: str, limit: int = 20,
                               project: str | None = None) -> list:
    vec = embed(query)
    if vec is None:
        return self.knowledge_search(query, limit=limit, project=project)
    filters = ["embedding IS NOT NULL", "invalid_at IS NULL"]
    params = [vec, limit]
    if project:
        filters.insert(1, "project = %s")
        params.insert(1, project)
    where = " AND ".join(filters)
    cur.execute(f"""
        SELECT *, embedding <=> %s AS distance
        FROM knowledge
        WHERE {where}
        ORDER BY distance ASC
        LIMIT %s
    """, params)
    return [dict(r) for r in cur.fetchall()]
```

### SOIL semantic search

```python
def search_semantic(self, collection: str, query: str, limit: int = 20) -> list:
    vec = embed(query)
    if vec is None:
        return self.search(collection, query)
    conn = self._conn(collection)
    rows = conn.execute("""
        SELECT r.data FROM records r
        JOIN records_vec rv ON rv.rowid = r.rowid
        WHERE knn_match(rv.embedding, ?, ?)
        AND r.deleted = 0
    """, (sqlite_vec.serialize_float32(vec), limit)).fetchall()
    conn.close()
    return [json.loads(row["data"]) for row in rows]
```

### MCP tool changes

`willow_knowledge_search` and `store_search` both gain `semantic: bool = False`. Default is `False` — existing behavior preserved, no regressions.

## Fallback Chain

```
semantic=True + Ollama up + embedding present  → ANN cosine search (ranked)
semantic=True + Ollama down                    → ILIKE/substring (existing)
semantic=True + embedding IS NULL              → row excluded from ANN results
semantic=False                                 → ILIKE/substring (existing, default)
```

## Error Handling

| Failure | Behavior |
|---------|----------|
| Ollama unavailable at write time | Row written without embedding; no error surfaced |
| pgvector extension missing | `UndefinedFunction` caught in `knowledge_put()`; GAP log entry written; row written without embedding |
| sqlite-vec unavailable | `ImportError` caught at module load; `search_semantic()` falls back to substring; one startup log line |
| `embedding IS NULL` in ANN query | Excluded by `WHERE embedding IS NOT NULL` guard |

## Testing

| Test file | Coverage |
|-----------|----------|
| `tests/unit/test_embedder.py` | Returns `list[float]` of length 768; returns `None` on connection failure (mock Ollama) |
| `tests/unit/test_pg_bridge_semantic.py` | Results ordered by cosine distance; fallback to ILIKE when embed returns None; NULL-embedding rows excluded |
| `tests/unit/test_willow_store_semantic.py` | Results returned from records_vec KNN; fallback when sqlite-vec absent |

No live Ollama required — unit tests mock `embedder.embed`. Manual smoke test: `willow_knowledge_search("memory distillation", semantic=True)` returns atoms that ILIKE misses.

## Dependencies

| Dependency | Install | Notes |
|------------|---------|-------|
| `pgvector` | `apt install postgresql-16-pgvector` (or `postgresql-17-pgvector`) | Postgres extension |
| `sqlite-vec` | `pip install sqlite-vec` | Pure Python wheel, self-contained |
| `nomic-embed-text` | Already in Ollama | Already running |

## Out of Scope

- Hybrid search (merge ILIKE + vector results in one call) — future work
- Automatic backfill at startup — performance risk with 2.1M records
- Embedding other stores (frank_ledger, opus_atoms) — out of scope for v1
- Re-embedding on record update — v1 embeds on first write only

ΔΣ=42
