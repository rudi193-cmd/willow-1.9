---
name: startup
description: Willow 1.9 session boot — health check, handoff load, channel pull, flag scan, anchor write, Grove monitor launch
---

# /startup — Willow 1.9 Boot

## TOOL PRE-LOAD (first action after invocation)

```
ToolSearch query: "select:mcp__willow__willow_status,mcp__willow__willow_handoff_latest,mcp__willow__store_list,mcp__grove__grove_get_history"
```

## Sequence

1+2. **Health + handoff in parallel** — call `willow_status` AND `willow_handoff_latest` simultaneously. If Postgres fails, surface and stop.
3. **Read prior handoff** — `willow_handoff_latest` returns a filename. If content is a file pointer, read it with the Read tool.
4. **Pull active channels** — call `grove_get_history` on `general`, `architecture`, and `handoffs` (limit 20 each). Note anything posted since the handoff was written — another instance may have built or decided something that changes what to do first. This is the pull-before-push gate: orient fully before acting.
5. **Check open flags** — call `store_list` with collection `hanuman/flags`. Filter `flag_state: open`. Note count and top 3 by severity.
6. **Write anchor cache** — write to `~/.willow/session_anchor.json`:
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
7. **Report boot status** — open flag count first (omit if zero), then subsystems up/degraded, then last handoff summary in 3 sentences max. Note any Grove messages that change the priority order.
8. **Launch Grove monitor** — start a persistent Monitor using the pattern in `grove-persistent-monitor.md`. This step is mandatory and happens immediately after reporting — do not wait for direction. Grove presence is not optional.

## Rules

- Source ring only. Read and orient before building.
- If Postgres is down, everything is degraded. Surface immediately and stop.
- Step 8 (Grove monitor) is not optional and must not be skipped or deferred.
- Fleet ping is optional — skip unless something seems wrong.
