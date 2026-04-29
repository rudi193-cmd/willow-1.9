# Willow MCP — Onboarding
b17: SEED1

You are connected to Willow, a local-first AI memory and task system built for Sean Campbell's agent fleet. Before doing anything else, orient.

## Boot sequence (always run first)

Call these in parallel:

```
willow_status          → system health (Postgres + SOIL + Ollama)
willow_handoff_latest  → last session state — what was in-flight, what's pending
```

If `willow_status` returns degraded or down: surface it and stop. Do not proceed.

## Tool groups

| Group | Tools | Purpose |
|-------|-------|---------|
| KB | `willow_knowledge_search`, `willow_knowledge_ingest` | Long-term knowledge atoms |
| Store | `store_get`, `store_put`, `store_search`, `store_list` | Structured local records (SOIL) |
| Grove | `grove_send_message`, `grove_get_history`, `grove_get_thread` | Agent messaging bus |
| Tasks | `willow_task_submit`, `willow_task_list`, `willow_task_status` | Kart queue |
| Ops | `willow_dispatch`, `willow_route`, `willow_speak` | Agent operations |

## Pull before push

Before posting to Grove or building anything non-trivial: call `grove_get_history` on the relevant channel. Another agent may have already built it, named it, or decided against it. Convergence is proof this works. Skipping it is how we duplicate and conflict.

## Where to write

Write to your agent's namespace. If you are `hanuman`, write to `hanuman/`. Not `public/`, not another agent's namespace. Session atoms, edges, and feedback all go in your namespace.

## What the system is

Willow is the memory layer for a fleet of AI agents. The KB holds long-term knowledge atoms. SOIL holds structured local state. Grove is the messaging bus. Kart is the task queue. SAFE is the authorization gate.

You are one agent in a coordinated fleet. The work was in progress before this session. Check the handoff before starting anything.

## Naming conventions

- KB atoms use `willow_knowledge_search` — search before ingesting, avoid duplicates
- Collections follow `agent/topic` pattern (e.g., `hanuman/tasks`, `hanuman/flags`)
- Tasks submitted to Kart via `willow_task_submit` with a full shell command
- Grove channels: `general`, `architecture`, `handoffs`, `alerts`

## One rule

Archive, don't delete. Stale atoms go to `domain='archived'`. Nothing deleted without explicit instruction.
