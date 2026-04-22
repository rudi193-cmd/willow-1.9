---
name: startup
description: Willow 1.9 session boot — health check, handoff load, flag scan, anchor write
---

# /startup — Willow 1.9 Boot

## Tool Pre-load

```
ToolSearch query: "select:mcp__willow__willow_status,mcp__willow__willow_handoff_latest,mcp__willow__store_list"
```

## Sequence

1+2. **Health + handoff in parallel** — call `mcp__willow__willow_status` AND `mcp__willow__willow_handoff_latest` simultaneously. If Postgres fails, surface and stop.
3. **Read prior handoff** — if content is a file pointer, use Read tool.
4. **Check open flags** — call `mcp__willow__store_list` with collection `hanuman/flags`. Filter `flag_state: open`. Note count and top 3 by severity.
5. **Write anchor cache** — Write tool to `~/.willow/session_anchor.json`:
   ```json
   {
     "written_at": "<ISO timestamp>",
     "agent": "hanuman",
     "postgres": "up|down",
     "handoff_title": "<filename>",
     "handoff_summary": "<one sentence>",
     "open_flags": <count>,
     "top_flags": ["<title1>", "<title2>", "<title3>"]
   }
   ```
   Also reset `~/.willow/anchor_state.json` to `{"prompt_count": 0}`.
6. **Report** — open flag count first (omit if zero), then subsystems, then last handoff summary (3 sentences max).

## Rules

- Source ring only. Read and orient before building.
- If Postgres is down, everything is degraded. Surface immediately and stop.
- Fleet ping is optional — skip unless something seems wrong.
