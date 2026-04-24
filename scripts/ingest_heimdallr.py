#!/usr/bin/env python3
"""
scripts/ingest_heimdallr.py
Extract KB atoms from recent Heimdallr handoffs and ingest into willow_19.

Targets: SESSION_HANDOFF_20260420_heimdallr_*.md through 20260422
Focus: n2n protocol design, willow-bot as test node, u2u tests, Plan 3 intelligence build.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pg_bridge import PgBridge

HANDOFF_DIR = Path.home() / "Ashokoa/agents/heimdallr/index/haumana_handoffs"
TARGET_DATES = ["20260420", "20260421", "20260422"]


def _extract_section(text: str, header: str) -> str:
    m = re.search(rf"^{re.escape(header)}\n(.+?)(?=\n---|\n## |\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def main():
    ingested = 0
    skipped = 0

    with PgBridge() as bridge:
        for date in TARGET_DATES:
            pattern = f"SESSION_HANDOFF_{date}_heimdallr_*.md"
            files = sorted(HANDOFF_DIR.glob(pattern))
            if not files:
                print(f"  [skip] no files for {date}")
                continue

            for f in files:
                text = f.read_text(encoding="utf-8", errors="replace")

                m = re.search(r"^#+ (?:Session Handoff\s*[—-]\s*|HANDOFF:\s*)(.+)$", text, re.MULTILINE)
                title = m.group(1).strip() if m else f.stem

                summary = _extract_section(text, "## 1. What I Now Understand")
                if not summary:
                    body = re.sub(r"^---.*?---", "", text, flags=re.DOTALL).strip()
                    paras = [p.strip() for p in body.split("\n\n") if p.strip() and not p.startswith("#")]
                    summary = paras[0][:600] if paras else text[:400]
                summary = summary[:800]

                gaps = _extract_section(text, "## Gaps") or _extract_section(text, "## 4. Open Flags")

                atom_id = bridge.ingest_atom(
                    title=f"[Heimdallr] {title}",
                    summary=summary,
                    source_type="handoff",
                    source_id=f.name,
                    category="session",
                    domain="session",
                )

                if atom_id:
                    print(f"  ✓ {f.name} → {atom_id}")
                    ingested += 1
                else:
                    print(f"  ✗ {f.name} — ingest failed: {bridge._last_ingest_error}")
                    skipped += 1

    print(f"\nDone. {ingested} ingested, {skipped} failed.")


if __name__ == "__main__":
    main()
