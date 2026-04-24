#!/usr/bin/env python3
"""scripts/run_norn.py — fire norn_pass against production willow_19."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.metabolic import norn_pass

print("[norn] Starting production intelligence run...", flush=True)
report = norn_pass(dry_run=False)
print(json.dumps(report, indent=2, default=str))

totals = {
    "draugr_zombies":       report.get("draugr", 0),
    "serendipity_surfaced": report.get("serendipity", 0),
    "dark_matter_links":    report.get("dark_matter", 0),
    "revelations":          report.get("revelations", 0),
    "mirror_meta":          report.get("mirror", 0),
    "mycorrhizal_fed":      report.get("mycorrhizal", 0),
}
print("\n[norn] Summary:")
for k, v in totals.items():
    print(f"  {k}: {v}")

if report.get("intelligence_error"):
    print(f"\n[norn] ERROR: {report['intelligence_error']}", file=sys.stderr)
    sys.exit(1)

print("\n[norn] Done.", flush=True)
