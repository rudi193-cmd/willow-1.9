---
name: willow-status
description: Quick system health check — postgres, ollama, active fork. Use instead of /startup for orientation.
---

Call willow_status (app_id: hanuman). Then call willow_fork_list (status: open).

Report:
  Postgres: up/down (N atoms)
  Ollama: up/down
  Active fork: FORK-ID or "none open"
  Open flags: N

If postgres=down: stop, tell Sean. Everything depends on it.
If services degraded: note it, keep going at reduced capability.
