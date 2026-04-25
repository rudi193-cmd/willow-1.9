---
name: memory-health
description: Audit Willow memory files for staleness, redundancy, dark records, and contradictions.
---

# Memory Health

Audit the agent's memory directory for four failure modes: STALE/DEAD files, REDUNDANT pairs, DARK records (invisible to search), and CONTRADICTIONS.

## Run

```bash
python3 {skills_dir}/scripts/memory_health.py --dir <memory-dir> --limit 50
python3 {skills_dir}/scripts/memory_health.py --dir <memory-dir> --limit 50 --qmd  # enable DARK detection
```

## Interpret

| Bucket      | Age        | Action                                          |
| ----------- | ---------- | ----------------------------------------------- |
| HOT         | < 7 days   | Healthy — no action                             |
| WARM        | 7–30 days  | Healthy — no action                             |
| STALE       | 30–90 days | Review — update or archive                      |
| DEAD        | > 90 days  | Archive — move to memory/archive/               |
| REDUNDANT   | —          | Merge — show both files, ask which to keep      |
| DARK        | —          | Re-index — run `qmd update` or `openclaw memory sync` |
| CONTRADICTION | —        | Clarify — show conflicting phrases, ask user    |

## Cleanup actions (offer after reporting)

1. Archive all DEAD files → `memory/archive/`
2. Show REDUNDANT pairs for manual review
3. Fix DARK records via re-index
4. Show CONTRADICTION files for editing
5. Skip — report only

Always confirm before moving or modifying files.
