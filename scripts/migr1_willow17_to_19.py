#!/usr/bin/env python3
"""
MIGR1 — Migrate 68K knowledge atoms from willow-1.7 (willow db) to willow-1.9 (willow_19 db).

ID mapping:
  - Row with b17 code  → use b17 as text ID
  - Row without b17    → "MIGR1-{old_bigint_id:08X}"

Extra 1.7 fields (lattice_domain, lattice_type, lattice_status, ring,
source_id, compact_id, b17) are packed into content jsonb so nothing is lost.

Run: PYTHONPATH=/home/sean-campbell/github/willow-1.9 python3 scripts/migr1_willow17_to_19.py
Add --dry-run to count without writing.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

BATCH = 1000
USER = os.environ.get("USER", "sean-campbell")


def parse_ts(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(str(val).strip(), fmt)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def make_id(row):
    b17 = (row["b17"] or "").strip()
    if b17:
        return b17
    return f"MIGR1-{row['id']:08X}"


def run(dry_run=False):
    conn17 = psycopg2.connect(dbname="willow", user=USER)
    conn19 = psycopg2.connect(dbname="willow_19", user=USER)
    conn19.autocommit = False
    cur17 = conn17.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur19 = conn19.cursor()

    cur17.execute("SELECT COUNT(*) FROM knowledge")
    total = cur17.fetchone()["count"]
    print(f"Source: {total} atoms in willow-1.7")

    cur19.execute("SELECT COUNT(*) FROM knowledge")
    before = cur19.fetchone()[0]
    print(f"Target: {before} atoms already in willow-1.9")

    if dry_run:
        print("DRY RUN — no writes.")
        conn17.close()
        conn19.close()
        return

    inserted = skipped = 0
    offset = 0

    while True:
        cur17.execute(
            """
            SELECT id, title, summary, source_type, source_id, category,
                   lattice_domain, lattice_type, lattice_status,
                   compact_id, ring, b17, project,
                   created_at, valid_at, invalid_at,
                   visit_count, weight, last_visited, fork_id
            FROM knowledge
            ORDER BY id
            LIMIT %s OFFSET %s
            """,
            (BATCH, offset),
        )
        rows = cur17.fetchall()
        if not rows:
            break

        records = []
        for row in rows:
            new_id = make_id(row)
            content = {
                "migrated_from": "willow-1.7",
                "original_id": row["id"],
            }
            for field in ("source_id", "lattice_domain", "lattice_type",
                          "lattice_status", "compact_id", "ring", "b17"):
                if row[field]:
                    content[field] = row[field]

            records.append((
                new_id,
                row["project"] or "global",
                row["valid_at"] or datetime.now(timezone.utc),
                row["invalid_at"],
                parse_ts(row["created_at"]) or datetime.now(timezone.utc),
                row["title"],
                row["summary"],
                json.dumps(content),
                row["source_type"],
                row["category"],
                row["visit_count"] or 0,
                row["weight"] or 1.0,
                row["last_visited"],
                row["fork_id"],
            ))

        psycopg2.extras.execute_values(
            cur19,
            """
            INSERT INTO knowledge
                (id, project, valid_at, invalid_at, created_at,
                 title, summary, content, source_type, category,
                 visit_count, weight, last_visited, fork_id)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
            """,
            records,
            template="(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)",
            page_size=BATCH,
        )
        batch_inserted = cur19.rowcount if cur19.rowcount >= 0 else len(records)
        skipped += len(records) - batch_inserted
        inserted += batch_inserted
        conn19.commit()

        offset += BATCH
        pct = min(100, round(offset / total * 100))
        print(f"  {offset}/{total} ({pct}%) — inserted {inserted}, skipped {skipped}",
              flush=True)

    cur19.execute("SELECT COUNT(*) FROM knowledge")
    after = cur19.fetchone()[0]

    conn17.close()
    conn19.close()

    print(f"\nDone. willow-1.9 knowledge: {before} → {after} (+{after - before})")
    print(f"Inserted: {inserted} | Skipped (conflict): {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
