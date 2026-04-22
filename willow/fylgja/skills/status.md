---
name: status
description: Willow 1.9 system status — Postgres, Ollama, local store, open flags
---

# /status — Willow 1.9 System Status

## Sequence

1. **Pre-load tools**:
   ```
   ToolSearch query: "select:mcp__willow__willow_status,mcp__willow__willow_system_status,mcp__willow__store_list"
   ```
2. **Run in parallel**: `mcp__willow__willow_status` AND `mcp__willow__willow_system_status` AND `mcp__willow__store_list` (collection `hanuman/flags`).
3. **Report** in this format:
   ```
   SUBSYSTEMS
     Postgres:    up / down / degraded
     Ollama:      up (N models) / down
     LocalStore:  N collections · M records
     Manifests:   N/N pass

   OPEN FLAGS: N
     • <top flag 1>
     • <top flag 2>
     • <top flag 3>
   ```
   Omit OPEN FLAGS section if count is zero.

## Rules

- If Postgres is down, surface immediately. Everything downstream is degraded.
- Report subsystems first, then flags. Never bury a Postgres failure in the middle.
