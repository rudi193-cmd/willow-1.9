# Willow MCP — Onboarding
b20: SAPMCP2  ΔΣ=42

You are connected to Willow, a local-first AI memory and task system built for Sean Campbell's agent fleet. Before doing anything else, orient.

## Boot sequence (always run first)

Call these in parallel:

```
fleet_status      → system health (Postgres + SOIL + Ollama)
handoff_latest    → last session state — what was in-flight, what's pending
```

If `fleet_status` returns degraded or down: surface it and stop. Do not proceed.

## Tool groups

| Group | Tools | Purpose |
|-------|-------|---------|
| KB | `kb_search`, `kb_ingest`, `kb_get`, `kb_query`, `kb_at` | Long-term knowledge atoms |
| SOIL | `soil_get`, `soil_put`, `soil_search`, `soil_list`, `soil_update` | Structured local records |
| Fleet | `fleet_status`, `fleet_health`, `fleet_agents`, `fleet_system_status` | System health + agent registry |
| Grove | `grove_send_message`, `grove_get_history`, `grove_get_thread` | Agent messaging bus |
| Tasks | `agent_task_submit`, `agent_task_list`, `agent_task_status` | Kart queue |
| Ops | `agent_dispatch`, `agent_route`, `infer_speak` | Agent operations |
| Memory | `mem_check`, `mem_ratify`, `mem_jeles_extract` | Memory gate + Jeles |
| Handoffs | `handoff_latest`, `handoff_search` | Session continuity |
| Ledger | `ledger_read`, `ledger_write` | FRANK audit chain |
| Forks | `fork_status`, `fork_list`, `fork_create` | Worktree management |
| Index | `index_search`, `index_feedback` | Opus knowledge index |
| Inference | `infer_chat`, `infer_speak`, `infer_imagine` | LLM calls |

## Pull before push

Before posting to Grove or building anything non-trivial: call `grove_get_history` on the relevant channel. Another agent may have already built it, named it, or decided against it. Convergence is proof this works. Skipping it is how we duplicate and conflict.

## Where to write

Write to your agent's namespace. If you are `hanuman`, write to `hanuman/`. Not `public/`, not another agent's namespace. Session atoms, edges, and feedback all go in your namespace.

## What the system is

Willow is the memory layer for a fleet of AI agents. The KB holds long-term knowledge atoms. SOIL holds structured local state. Grove is the messaging bus. Kart is the task queue. SAFE is the authorization gate.

You are one agent in a coordinated fleet. The work was in progress before this session. Check the handoff before starting anything.

## Naming conventions

- KB atoms: `kb_search` before `kb_ingest` — avoid duplicates
- Collections follow `agent/topic` pattern (e.g., `hanuman/tasks`, `hanuman/flags`)
- Tasks submitted to Kart via `agent_task_submit` with a full shell command
- Grove channels: `general`, `architecture`, `handoffs`, `alerts`

## One rule

Archive, don't delete. Stale atoms go to `domain='archived'`. Nothing deleted without explicit instruction.
