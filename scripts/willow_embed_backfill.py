#!/usr/bin/env python3
"""
willow_embed_backfill.py — Backfill NULL embeddings across Postgres tables.
b17: SEM01  ΔΣ=42

Run by Kart when queued via willow_embed_backfill task. Processes knowledge,
opus_atoms, and jeles_atoms in batches of 100.
Safe to interrupt and restart — re-queries NULL each pass.

Usage:
    python3 scripts/willow_embed_backfill.py [--limit N] [--dry-run]
"""
import argparse
import collections
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.embedder import embed
from core.pg_bridge import PgBridge
from core.willow_store import WillowStore

BATCH_SIZE = 100
MAX_EMBED_CHARS = 4000
MIN_TEXT_LEN = 20       # skip atoms shorter than this — garbage vectors
MAX_SKIPPED = 1000      # bail on a table if this many atoms fail — Ollama likely down
PROGRESS_COLLECTION = "hanuman/tasks"
PROGRESS_ID = "embed_backfill_progress"

# Projects to exclude from knowledge table backfill.
# High-volume, low-signal — don't benefit from semantic search.
_SKIP_PROJECTS = (
    'session-turn', 'conversation', 'file_location',
    'die-namic-index', 'willow_index',
    'sessions', 'telemetry', 'training',
)

_shutdown = False


def _handle_signal(sig, frame):
    global _shutdown
    print("\n[backfill] interrupt — finishing current batch then stopping", flush=True)
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

RATE_WINDOW = collections.deque(maxlen=10)


def _write_progress(store: WillowStore, table: str, done: int, total: int, started_at: float) -> None:
    now = time.time()
    elapsed = now - started_at
    rate = done / elapsed if elapsed > 0 else 0

    RATE_WINDOW.append((now, done))
    if len(RATE_WINDOW) >= 2:
        dt = RATE_WINDOW[-1][0] - RATE_WINDOW[0][0]
        dc = RATE_WINDOW[-1][1] - RATE_WINDOW[0][1]
        rate_recent = dc / dt if dt > 0 else rate
    else:
        rate_recent = rate

    display_rate = rate_recent if rate_recent > 0 else rate
    remaining = (total - done) / display_rate if display_rate > 0 else 0
    try:
        store.put(PROGRESS_COLLECTION, {
            "id": PROGRESS_ID,
            "task": "willow_embed_backfill",
            "table": table,
            "atoms_done": done,
            "total": total,
            "pct": round(100 * done / total, 1) if total else 0,
            "rate_per_sec": round(rate, 2),
            "rate_recent": round(rate_recent, 2),
            "eta_seconds": int(remaining),
            "eta_human": f"{int(remaining // 3600)}h {int((remaining % 3600) // 60)}m",
            "started_at": datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat(),
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        })
    except Exception:
        pass  # progress write failure never kills the run


def _check_ollama() -> bool:
    try:
        return embed("x") is not None
    except Exception:
        return False


def _backfill_table(pg: PgBridge, store: WillowStore, table: str, text_expr: str,
                    dry_run: bool, limit: int, total_offset: int, grand_total: int,
                    started_at: float, extra_filter: str | None = None) -> int:
    """Backfill NULL embeddings for one table. Returns count of rows processed."""
    processed = 0
    skipped_ids: set = set()
    where = "embedding IS NULL"
    if extra_filter:
        where += f" AND {extra_filter}"

    while not _shutdown:
        # Fetch batch of IDs + text in one query — no per-atom round trips.
        pg._ensure_conn()
        with pg.conn.cursor() as cur:
            skip_clause = " AND id != ALL(%s)" if skipped_ids else ""
            params = [list(skipped_ids), BATCH_SIZE] if skipped_ids else [BATCH_SIZE]
            cur.execute(
                f"SELECT id, {text_expr} FROM {table} WHERE {where}{skip_clause} "
                f"ORDER BY created_at DESC LIMIT %s",
                params,
            )
            rows = cur.fetchall()
        pg.conn.commit()

        if not rows:
            break

        batch_done = 0
        for row_id, text in rows:
            if _shutdown or (limit and processed >= limit):
                return processed

            if dry_run:
                processed += 1
                batch_done += 1
                continue

            text = (text or "").strip()
            if len(text) < MIN_TEXT_LEN:
                skipped_ids.add(row_id)
                continue

            vec = None
            for attempt in range(3):
                vec = embed(text[:MAX_EMBED_CHARS])
                if vec is not None:
                    break
                if attempt < 2:
                    print(f"  [{table}] {row_id}: Ollama unavailable (attempt {attempt+1}/3) — retrying in 5s", flush=True)
                    time.sleep(5)

            if vec is None:
                print(f"  [{table}] {row_id}: embed failed — skipping", flush=True)
                skipped_ids.add(row_id)
                if len(skipped_ids) >= MAX_SKIPPED:
                    print(f"  [{table}] {MAX_SKIPPED} failures — aborting table (Ollama may be down)", flush=True)
                    return processed
                processed += 1
                batch_done += 1
                continue

            pg._ensure_conn()
            with pg.conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} SET embedding = %s::vector WHERE id = %s",
                    (str(vec), row_id),
                )
            pg.conn.commit()
            processed += 1
            batch_done += 1

        print(f"  [{table}] +{batch_done} embedded (total {processed})", flush=True)
        _write_progress(store, table, total_offset + processed, grand_total, started_at)

    return processed


def main():
    parser = argparse.ArgumentParser(description="Backfill NULL embeddings")
    parser.add_argument("--limit", type=int, default=0, help="Max rows per table (0 = unlimited)")
    parser.add_argument("--dry-run", action="store_true", help="Count rows without writing")
    args = parser.parse_args()

    if not args.dry_run:
        print("[backfill] checking Ollama...", flush=True)
        if not _check_ollama():
            print("[backfill] ERROR: Ollama not reachable — aborting. Start Ollama and retry.", flush=True)
            sys.exit(1)
        print("[backfill] Ollama OK", flush=True)

    pg = PgBridge()
    store = WillowStore()

    skip_projects = ", ".join(f"'{p}'" for p in _SKIP_PROJECTS)
    tables = [
        ("knowledge",
         "COALESCE(title, '') || ' ' || COALESCE(summary, '')",
         f"invalid_at IS NULL AND project NOT IN ({skip_projects})"),
        ("opus_atoms",  "content", None),
        ("jeles_atoms", "COALESCE(title, '') || ' ' || content", None),
    ]

    grand_total = 0
    table_counts = []
    for table, text_expr, extra_filter in tables:
        where = "embedding IS NULL"
        if extra_filter:
            where += f" AND {extra_filter}"
        with pg.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}")
            null_count = cur.fetchone()[0]
        pg.conn.commit()
        table_counts.append((table, text_expr, extra_filter, null_count))
        grand_total += null_count

    print(f"[backfill] {grand_total} atoms to embed", flush=True)

    started_at = time.time()
    total_offset = 0
    total = 0

    for table, text_expr, extra_filter, null_count in table_counts:
        if null_count == 0:
            print(f"[{table}] 0 NULL embeddings — skipping", flush=True)
            continue
        if _shutdown:
            break

        print(f"[{table}] {null_count} NULL embeddings — backfilling...", flush=True)
        n = _backfill_table(pg, store, table, text_expr, args.dry_run, args.limit,
                            total_offset, grand_total, started_at, extra_filter)
        total_offset += n
        total += n
        print(f"[{table}] done: {n} rows {'would be ' if args.dry_run else ''}processed", flush=True)

    if not args.dry_run and grand_total > 0:
        _write_progress(store, "done", total, grand_total, started_at)

    elapsed = time.time() - started_at
    rate = total / elapsed if elapsed > 0 else 0
    print(f"\n[backfill] total: {total} rows in {elapsed:.0f}s ({rate:.1f}/s)", flush=True)


if __name__ == "__main__":
    main()
