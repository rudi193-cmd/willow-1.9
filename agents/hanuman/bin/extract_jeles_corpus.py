#!/usr/bin/env python3
"""
extract_jeles_corpus.py — Track 1: Jeles → KB pipeline
b17: JXTR1  ΔΣ=42

Reads each registered Jeles session JSONL, finds assistant turns that mention
professors (Gerald, Hanz, Oakenscroll, UTETY), and ingests them as knowledge
atoms so willow_knowledge_search can find them.

Usage:
    WILLOW_PG_DB=willow_19 python3 agents/hanuman/bin/extract_jeles_corpus.py
    python3 agents/hanuman/bin/extract_jeles_corpus.py --dry-run
    python3 agents/hanuman/bin/extract_jeles_corpus.py --limit 20
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.pg_bridge import PgBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [jxtr] %(message)s")
log = logging.getLogger("jxtr")

PROFESSOR_TOKENS = ["Gerald", "Hanz", "Oakenscroll", "UTETY", "Professor"]
MIN_TEXT_LEN = 80
MAX_EXCERPT = 1200


def _iter_professor_turns(jsonl_path: str) -> list[dict]:
    """Return assistant text blocks mentioning professors from one JSONL file."""
    hits = []
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message", {})
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "text":
                        continue
                    text = block.get("text", "")
                    if len(text) < MIN_TEXT_LEN:
                        continue
                    if any(token in text for token in PROFESSOR_TOKENS):
                        hits.append({
                            "text": text[:MAX_EXCERPT],
                            "timestamp": obj.get("timestamp", ""),
                            "session_id": obj.get("sessionId", ""),
                        })
    except FileNotFoundError:
        log.warning("JSONL not found: %s", jsonl_path)
    return hits


def _professor_label(text: str) -> str:
    """Pick the most prominent professor name from a text block."""
    for name in ["Oakenscroll", "Gerald", "Hanz"]:
        if name in text:
            return name
    return "UTETY"


def main():
    parser = argparse.ArgumentParser(description="Extract Jeles corpus → KB atoms")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    parser.add_argument("--limit", type=int, default=0, help="Max sessions to process (0=all)")
    args = parser.parse_args()

    pg = PgBridge()

    with pg.conn.cursor() as cur:
        cur.execute(
            "SELECT id, jsonl_path, session_id, turn_count FROM jeles_sessions "
            "WHERE agent = 'hanuman' ORDER BY turn_count DESC"
        )
        sessions = cur.fetchall()

    if args.limit:
        sessions = sessions[: args.limit]

    log.info("Processing %d sessions", len(sessions))

    ingested = 0
    skipped = 0

    for jid, jsonl_path, session_id, turn_count in sessions:
        hits = _iter_professor_turns(jsonl_path)
        if not hits:
            skipped += 1
            continue

        for hit in hits:
            prof = _professor_label(hit["text"])
            ts = hit["timestamp"][:10] if hit["timestamp"] else "unknown"
            title = f"{prof} — {ts} (jeles/{jid[:6]})"
            summary = hit["text"]

            if args.dry_run:
                log.info("[DRY] %s", title)
                log.info("      %s...", summary[:120])
                ingested += 1
                continue

            atom_id = pg.ingest_atom(
                title=title,
                summary=summary,
                source_type="jeles",
                source_id=jid,
                category="professor",
                domain="utety",
            )
            if atom_id:
                log.info("Ingested %s → %s", title, atom_id)
                ingested += 1
            else:
                log.warning("Ingest failed for %s: %s", title, pg._last_ingest_error)

    log.info("Done. ingested=%d skipped=%d", ingested, skipped)


if __name__ == "__main__":
    main()
