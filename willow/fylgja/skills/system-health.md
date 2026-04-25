---
name: system-health
description: Willow stack health check — Postgres, Ollama, MCP, forks, jeles, store. Boot/daily/weekly tiers.
---

# System Health

Run the diagnostic script and interpret results. Works without an active MCP session.

## Run

```bash
python3 {skills_dir}/scripts/system_health.py --check boot    # every session
python3 {skills_dir}/scripts/system_health.py --check daily   # once per day
python3 {skills_dir}/scripts/system_health.py --check weekly  # once per week
```

Where `{skills_dir}` is the path to this skills directory.

## Interpret

| Status     | Action                                                            |
| ---------- | ----------------------------------------------------------------- |
| HEALTHY    | No action needed                                                  |
| WARN       | Review and offer fix (see table in script output)                 |
| CRITICAL   | Service down — fix before proceeding with memory-dependent tasks  |

## Cleanup actions (offer after reporting)

1. Merge or delete orphaned forks
2. Clean old jeles sessions (`willow jeles cleanup` or script --cleanup)
3. Remove dead Ollama models (`ollama rm <model>`)
4. Run Postgres VACUUM ANALYZE
5. Skip — report only

Always confirm before any destructive action.
