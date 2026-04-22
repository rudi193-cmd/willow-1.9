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
        chosen_filters = [
            "invalid_at IS NULL",
            "source_type IN ('community_detection', 'revelation', 'mirror')",
            "summary IS NOT NULL", "summary != ''",
        ]
        rejected_filters = [
            "invalid_at IS NULL",
            "(category = 'draugr' OR summary IS NULL OR summary = '')",
        ]
        chosen_params: list = []
        rejected_params: list = []
        if project:
            chosen_filters.append("project = %s")
            chosen_params.append(project)
            rejected_filters.append("project = %s")
            rejected_params.append(project)

        with bridge.conn.cursor(cursor_factory=_pex.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, project, title, summary, source_type FROM knowledge "
                f"WHERE {' AND '.join(chosen_filters)} ORDER BY created_at DESC LIMIT 50",
                chosen_params,
            )
            chosen_candidates = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT id, project, title, summary FROM knowledge "
                f"WHERE {' AND '.join(rejected_filters)} ORDER BY created_at ASC LIMIT 50",
                rejected_params,
            )
            rejected_candidates = [dict(r) for r in cur.fetchall()]
    except Exception as _e:
        import sys as _sys
        print(f"[valhalla] collection error: {_e}", file=_sys.stderr)
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
