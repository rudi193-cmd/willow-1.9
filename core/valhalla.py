#!/usr/bin/env python3
"""
valhalla.py — W19VH: Valhalla DPO pair collection.
b17: VAL19  ΔΣ=42

The Einherjar are the honored dead who train for Ragnarök.
The best knowledge atoms train for the next model.

DPO pair format:
  {"prompt": "...", "chosen": "...", "rejected": "...", "meta": {...}}

SLM training run is 2.0. This module handles collection only.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import psycopg2.extras as _pex
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False


def collect_dpo_pairs(bridge, store, output_dir: Optional[Path] = None,
                      project: Optional[str] = None) -> int:
    """
    Scan KB for high-quality atoms (community nodes, revelations, mirrors) as
    chosen candidates and draugr/null-summary atoms as rejected candidates.
    Writes JSONL to output_dir/dpo_pairs.jsonl.
    Returns count of pairs written. W19VH.
    """
    if output_dir is None:
        output_dir = Path.home() / ".willow" / "valhalla"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "dpo_pairs.jsonl"

    if not _PG_AVAILABLE:
        return 0

    try:
        proj_filter = "AND project = %s" if project else ""
        proj_params = [project] if project else []

        with bridge.conn.cursor(cursor_factory=_pex.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT id, project, title, summary, source_type FROM knowledge
                WHERE invalid_at IS NULL
                  AND source_type IN ('community_detection', 'revelation', 'mirror')
                  AND summary IS NOT NULL AND summary != ''
                  {proj_filter}
                ORDER BY created_at DESC LIMIT 50
            """, proj_params)
            chosen_candidates = [dict(r) for r in cur.fetchall()]

            cur.execute(f"""
                SELECT id, project, title, summary FROM knowledge
                WHERE invalid_at IS NULL
                  AND (category = 'draugr' OR summary IS NULL OR summary = '')
                  {proj_filter}
                ORDER BY created_at ASC LIMIT 50
            """, proj_params)
            rejected_candidates = [dict(r) for r in cur.fetchall()]
    except Exception:
        return 0

    if not chosen_candidates or not rejected_candidates:
        return 0

    pairs = []
    for i, chosen in enumerate(chosen_candidates):
        rejected = rejected_candidates[i % len(rejected_candidates)]
        chosen_text = (chosen.get("summary") or "").strip()
        rejected_text = (rejected.get("summary") or "").strip()
        if not chosen_text or not rejected_text or chosen_text == rejected_text:
            continue
        pairs.append({
            "prompt": f"What does Willow know about: {chosen.get('title', 'this topic')}?",
            "chosen": chosen_text,
            "rejected": rejected_text,
            "meta": {
                "chosen_id": chosen["id"],
                "chosen_type": chosen.get("source_type"),
                "chosen_project": chosen.get("project"),
                "rejected_id": rejected["id"],
                "collected_at": datetime.now(timezone.utc).isoformat(),
            },
        })

    with open(output_path, "w") as f:
        for pair in pairs:
            f.write(json.dumps(pair) + "\n")

    return len(pairs)
