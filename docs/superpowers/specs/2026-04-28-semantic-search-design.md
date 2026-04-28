# Semantic Search (ANN) — Design Spec
**Date:** 2026-04-28 | **Status:** Approved | **b17:** SEM01

## What It Is

Adds approximate nearest-neighbor (ANN) semantic search to both Willow knowledge stores — the Postgres `knowledge` table (LOAM) and the SOIL SQLite store — plus `opus_atoms` and `jeles_atoms`. Uses `nomic-embed-text` via the local Ollama instance (already running) to generate 768-dimensional embeddings at write time. Replaces neither store nor any existing search path — adds a `semantic=true` flag alongside current ILIKE/substring search. `semantic=true` uses hybrid RRF (ANN + ILIKE) rather than pure ANN for better precision on exact-match queries.

## Motivation

Current `knowledge_search` (`pg_bridge.py:610`) is `ILIKE %query%` on title and summary. Current SOIL `search()` (`willow_store.py:353`) is a full Python scan of all records. Both miss semantically related content when exact words don't match. With 209K KB atoms and 2.1M SOIL records, the substring scan is also a performance problem.

`search_opus()` (`pg_bridge.py:699`) is `ILIKE %content%` on opus_atoms — the distillation store. Semantic gaps here are the highest-cost misses in the system.

`nomic-embed-text` is already running in Ollama. This spec wires it in.

## Architecture

```
write path:
  knowledge_put(title, summary, ...) → embed(title + summary) → store in knowledge.embedding
  ingest_opus_atom(content, ...)     → embed(content) → store in opus_atoms.embedding
  jeles_extract_atom(title, content) → embed(title + content) → store in jeles_atoms.embedding
  store_put(collection, record)      → embed(record_json[:2000]) → store in records_vec virtual table

search path (semantic=True):
  willow_knowledge_search(query, semantic=True) → hybrid: ANN (pgvector) + ILIKE → RRF merge
  opus_search(query, semantic=True)             → hybrid: ANN + ILIKE → RRF merge
  store_search(collection, query, semantic=True) → embed(query) → ANN via sqlite-vec → ranked results

fallback:
  Ollama down OR embedding IS NULL → falls back to existing ILIKE/substring search
  semantic=False (default)         → existing behavior, unchanged

startup:
  If any embedded table has rows with embedding IS NULL → auto-submit willow_embed_backfill Kart task
```

## Components

| Component | Change |
|-----------|--------|
| `core/embedder.py` | **New.** Single `embed(text) -> list[float] \| None` function. Calls Ollama `/api/embeddings`, 5s timeout, returns `None` on any failure. |
| `core/pg_bridge.py` | `knowledge_put()` embeds on write AND on update (upsert path). `ingest_opus_atom()` embeds on write. `jeles_extract_atom()` embeds on write. New `knowledge_search_semantic()`, `search_opus_semantic()`, `search_jeles_semantic()` methods using hybrid RRF. |
| `core/willow_store.py` | `store_put()` embeds on write into `records_vec` virtual table. New `search_semantic()` method using sqlite-vec KNN. |
| `sap/sap_mcp.py` | Add `semantic: bool = False` parameter to `willow_knowledge_search`, `store_search`, and `opus_search` MCP tools. |
| `sap/sap_mcp.py` | Startup backfill check: after DB health gate, count NULL embeddings across all embedded tables; if > 0, submit `willow_embed_backfill` Kart task automatically. |

One new file. Targeted edits to three existing files. No new processes, no new services.

## Data Model

### Postgres

```sql
-- Enable extension (run once per DB)
CREATE EXTENSION IF NOT EXISTS vector;

-- knowledge: nullable column — existing rows keep NULL until backfill
ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS embedding VECTOR(768);
CREATE INDEX IF NOT EXISTS knowledge_embedding_hnsw
  ON knowledge USING hnsw (embedding vector_cosine_ops);

-- opus_atoms: same pattern
ALTER TABLE opus_atoms ADD COLUMN IF NOT EXISTS embedding VECTOR(768);
CREATE INDEX IF NOT EXISTS opus_atoms_embedding_hnsw
  ON opus_atoms USING hnsw (embedding vector_cosine_ops);

-- jeles_atoms: same pattern
ALTER TABLE jeles_atoms ADD COLUMN IF NOT EXISTS embedding VECTOR(768);
CREATE INDEX IF NOT EXISTS jeles_atoms_embedding_hnsw
  ON jeles_atoms USING hnsw (embedding vector_cosine_ops);
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
| `opus_atoms` | `content` |
| `jeles_atoms` | `f"{title or ''} {content}"` |
| SOIL | `record_json[:2000]` (truncated to avoid token limits) |

### Write behavior

Embedding is attempted after the record is written. If `embed()` returns `None`, the row is persisted without an embedding — the write never fails due to Ollama being unavailable.

### Update behavior

**Postgres (`knowledge_put` upsert):** `knowledge_put()` uses `ON CONFLICT (id) DO UPDATE SET`. The SET clause includes `embedding = EXCLUDED.embedding` so a revised title/summary triggers a fresh embed. If Ollama is down, the upserted embedding is set to NULL — backfill picks it up. A stale embedding is never left on a record whose content has changed.

**SOIL (`store.update()`):** `update()` does `INSERT OR REPLACE INTO records` but never touches `records_vec`. After the record write, `store.update()` must also upsert the embedding into `records_vec` by rowid. If Ollama is down, delete the `records_vec` row for that rowid (forcing backfill) rather than leaving a stale vector.

### Backfill

**Postgres:** `willow_embed_backfill` Kart task queries `embedding IS NULL` on `knowledge`, `opus_atoms`, and `jeles_atoms` in batches of 100 with 50ms sleep.

**SOIL:** SOIL is per-collection SQLite files. The backfill task calls `store.collections()` (which does `root.rglob("*.db")`) to enumerate all collection files, then for each collection queries `SELECT r.rowid, r.data FROM records r LEFT JOIN records_vec rv ON rv.rowid = r.rowid WHERE rv.rowid IS NULL AND r.deleted = 0` to find unembedded records. Processes in batches of 100 per collection.

**Backfill priority:** Collections with prose-heavy records (notes, summaries, descriptions) should be backfilled first. Collections with primarily structured records (flags, tasks, anchors) have poor semantic signal from raw JSON — `{"flag_state": "open", "severity": 3}` embeds poorly. These are still backfilled (they benefit from hybrid RRF's ILIKE leg), but should be deprioritized in the Kart task's collection ordering.

**Auto-queue at startup:** During the Willow session start sequence, after the DB health gate, SAP checks `SELECT COUNT(*) FROM knowledge WHERE embedding IS NULL` (and same for `opus_atoms`, `jeles_atoms`). If any count > 0, it auto-submits `willow_embed_backfill`. SOIL is not checked at startup — the Kart task handles it. Old records remain findable via substring search until backfilled.

## Search Path

### Hybrid RRF (Postgres)

`semantic=True` runs both ANN and ILIKE in parallel, then merges via Reciprocal Rank Fusion:

```python
def _rrf_merge(ann_results: list, ilike_results: list, k: int = 60) -> list:
    scores = {}
    for rank, row in enumerate(ann_results):
        scores.setdefault(row["id"], {"row": row, "score": 0})
        scores[row["id"]]["score"] += 1 / (k + rank + 1)
    for rank, row in enumerate(ilike_results):
        scores.setdefault(row["id"], {"row": row, "score": 0})
        scores[row["id"]]["score"] += 1 / (k + rank + 1)
    return [v["row"] for v in sorted(scores.values(), key=lambda x: -x["score"])]

def knowledge_search_semantic(self, query: str, limit: int = 20,
                               project: str | None = None) -> list:
    vec = embed(query)
    if vec is None:
        return self.knowledge_search(query, limit=limit, project=project)
    ann = self._knowledge_ann(vec, limit=limit, project=project)
    ilike = self.knowledge_search(query, limit=limit, project=project)
    return _rrf_merge(ann, ilike)[:limit]
```

The same pattern applies to `search_opus_semantic()` and `search_jeles_semantic()`.

### Postgres ANN helper

```python
def _knowledge_ann(self, vec, limit, project):
    filters = ["embedding IS NOT NULL", "invalid_at IS NULL"]
    params = [vec, limit]
    if project:
        filters.insert(1, "project = %s")
        params.insert(1, project)
    where = " AND ".join(filters)
    cur.execute(f"""
        SELECT *, embedding <=> %s AS distance
        FROM knowledge WHERE {where}
        ORDER BY distance ASC LIMIT %s
    """, params)
    return [dict(r) for r in cur.fetchall()]
```

### SOIL semantic search

SOIL returns ANN results only (no hybrid) — the sqlite substring scan is already O(N) so ILIKE is available via the existing `search()` fallback if needed.

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

`willow_knowledge_search`, `store_search`, and `opus_search` gain `semantic: bool = False`. Default is `False` — existing behavior preserved, no regressions.

## Fallback Chain

```
semantic=True + Ollama up + embedding present  → RRF (ANN + ILIKE merged)
semantic=True + Ollama down                    → ILIKE/substring (existing)
semantic=True + embedding IS NULL              → row excluded from ANN leg; ILIKE leg still runs
semantic=False                                 → ILIKE/substring (existing, default)
```

## Error Handling

| Failure | Behavior |
|---------|----------|
| Ollama unavailable at write time | Row written without embedding; no error surfaced |
| Ollama unavailable at Postgres update time | embedding set to NULL in upsert; backfill picks it up |
| Ollama unavailable at SOIL update time | `records_vec` row deleted for that rowid; backfill re-embeds on next pass |
| pgvector extension missing | `UndefinedFunction` caught in write path; GAP log entry written; row written without embedding |
| sqlite-vec unavailable | `ImportError` caught at module load; `search_semantic()` falls back to substring; one startup log line |
| `embedding IS NULL` in ANN query | Excluded from ANN leg; ILIKE leg still contributes to RRF |

## Testing

| Test file | Coverage |
|-----------|----------|
| `tests/unit/test_embedder.py` | Returns `list[float]` of length 768; returns `None` on connection failure (mock Ollama) |
| `tests/unit/test_pg_bridge_semantic.py` | RRF merge: ANN-only result + ILIKE-only result both appear in output; ANN result scores higher when it also matches ILIKE; fallback to ILIKE when embed returns None; NULL-embedding rows excluded from ANN leg |
| `tests/unit/test_willow_store_semantic.py` | Results returned from records_vec KNN; fallback when sqlite-vec absent |
| `tests/unit/test_opus_jeles_semantic.py` | opus_atoms and jeles_atoms embed on write; `search_opus_semantic()` and `search_jeles_semantic()` return hybrid results |

No live Ollama required — unit tests mock `embedder.embed`. Manual smoke test: `willow_knowledge_search("memory distillation", semantic=True)` returns atoms that ILIKE misses.

## Dependencies

| Dependency | Install | Notes |
|------------|---------|-------|
| `pgvector` | `apt install postgresql-16-pgvector` (or `postgresql-17-pgvector`) | Postgres extension |
| `sqlite-vec` | `pip install sqlite-vec` | Pure Python wheel, self-contained |
| `nomic-embed-text` | Already in Ollama | Already running |

## Out of Scope

- Automatic backfill *inline* at startup — performance risk with 2.1M records. Auto-queue via Kart is in scope.
- Embedding `frank_ledger` — append-only hash chain for audit, not a retrieval store
- Embedding `cmb_atoms` — scratch/composition buffer, no search surface exposed
- Hybrid search for SOIL — sqlite substring scan is already O(N); SOIL callers who need both can call `search()` + `search_semantic()` separately

ΔΣ=42
