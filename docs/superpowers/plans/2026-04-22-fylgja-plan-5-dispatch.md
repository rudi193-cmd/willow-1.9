# Plan 5 — Willow Grove Dispatch
## Sovereign Multi-Agent Orchestration via Unified Grove Interface

**Date:** 2026-04-22 (v3 — rewritten after CC source audit + full skill inventory)
**Status:** SPEC — awaiting Sean's authorization before implementation
**b17:** DSP5C ΔΣ=42
**Author:** Hanuman (Claude Code, Sonnet 4.6, willow-1.9 orchestrator)

---

## What Changed in v3

v2 was speccing a custom dispatch transport. The CC source audit found that transport already exists.
v3 corrects the layer: **dispatch is visibility + governance**, not transport.

| v2 (wrong layer) | v3 (correct layer) |
|---|---|
| Build custom message pipe | Ride `SendMessage` / `RemoteTrigger` / `CronCreate` |
| Invent availability signal | Read SEP-1686 task state (already live) |
| Custom agent spawning | Extend swarm team-lead/teammate model |
| Grove as transport | Grove as audit trail |

---

## The Big Picture

```
┌─────────────────────────────────────────────────────────────────┐
│                        WILLOW GROVE                             │
│         (Grove made visible — same data, different skin)        │
├──────────────────┬──────────────────────────────────────────────┤
│   CHANNELS       │  DISPATCH FLOW                               │
│                  │                                              │
│  #general        │   OPERATOR types task                        │
│  #architecture   │        │                                     │
│  #handoffs       │        ▼                                     │
│  #dispatch  ◄────┼──  willow_route (oracle)                    │
│  #dispatch-      │        │                                     │
│   escalations    │        ├── escalation_required: true         │
│  #dispatch-      │        │        │                            │
│   violations     │        │        ▼                            │
│                  │        │   #dispatch-escalations             │
│                  │        │   (OPERATOR replies to authorize)   │
│                  │        │                                     │
│                  │        ▼                                     │
│                  │   willow_dispatch                            │
│                  │        │  posts to #dispatch (audit trail)   │
│                  │        │  creates SEP-1686 task              │
│                  │        │  calls transport ──────────────┐   │
│                  │        │                                │   │
│                  │        ▼                                │   │
│                  │   LOAM knowledge atom                   │   │
│                  │   (result deposited, card updated)      │   │
└──────────────────┴─────────────────────────────────────────┴───┘
                                                             │
                                              ┌──────────────▼──────────────┐
                                              │     TRANSPORT LAYER          │
                                              │   (CC tools, already exist)  │
                                              │                              │
                                              │  RUNNING  → SendMessage      │
                                              │  OFFLINE  → RemoteTrigger    │
                                              │  STALE    → CronCreate       │
                                              └─────────────────────────────┘
```

---

## Architectural Principle

**Grove is the unified interface layer. Transport is CC's existing stack.**

- Humans participate in Grove via words
- Agents participate via MCP tools (`grove_send_message`, `grove_watch_all`, `grove_get_history`)
- `#dispatch` is the audit trail — every dispatch is visible to humans
- Authorization (Dual Commit) is a human replying in `#dispatch-escalations`
- The transport (`SendMessage` / `RemoteTrigger` / `CronCreate`) is invisible to humans
- Gerald watches. Cannot speak, cannot dispatch. Cannot be dispatched to.

---

## Part 1 — Transport Layer (already exists, nothing to build)

```
                    AGENT AVAILABILITY
                           │
          ┌────────────────┼────────────────┐
          │                │                │
     0–2 min           2–15 min          15min–1h+
    RUNNING             IDLE              STALE
          │                │                │
          ▼                ▼                ▼
    SendMessage      RemoteTrigger     CronCreate
    (resume named    (spawn fresh      (durable:true
     teammate,        CCR session,      recurring:false
     context kept)    new context)      one-shot pickup)
```

Thresholds read from `willow/constants.py` (Task 1).
Availability determined by SEP-1686 task state, fallback to last Grove message timestamp.

---

## Part 2 — Dispatch Schema

```
{
  "id":                  "<uuid>",
  "to":                  "ganesha",          ← target agent
  "from":                "hanuman",          ← dispatching agent
  "prompt":              "...",              ← the work
  "context_id":          "7KE2N",            ← base17-compact context ref (optional)
  "card_id":             "<card_id>",        ← dashboard card to update
  "session_id":          "abc123",
  "ts":                  "<ISO-8601>",
  "priority":            "normal",
  "reply_to":            "<parent_id|null>", ← for threaded dispatch
  "depth":               0,                  ← incremented on re-dispatch
  "escalation_required": false,              ← set by oracle, not dispatcher
  "deposit_to":          "binder",           ← "binder" | "ephemeral"
}
```

`context_id` is new in v3. Uses `base17-compact` — sends a 5-char ID instead of embedding context inline. Receiving agent resolves via `core.compact.resolve()`.

---

## Part 3 — Dispatch Flow

```
                    ┌──────────────┐
                    │   OPERATOR   │
                    │  types task  │
                    └──────┬───────┘
                           │
                           ▼
                   ┌───────────────┐
                   │ willow_route  │  ← Plan 4 oracle (must ship first)
                   │  (oracle)     │
                   └──────┬────────┘
                          │
              ┌───────────┴───────────┐
              │                       │
    escalation_required: false   escalation_required: true
              │                       │
              │               ┌───────▼──────────────────┐
              │               │  POST to #dispatch-       │
              │               │  escalations              │
              │               │  BLOCK until OPERATOR     │
              │               │  replies "authorized"     │
              │               └───────┬──────────────────┘
              │                       │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   willow_dispatch     │
              │                       │
              │  1. POST to #dispatch │  ← audit trail
              │  2. Create SEP-1686   │  ← durable state machine
              │     task (pending)    │
              │  3. depth check ──────┼──► depth > 3?
              │                       │         │
              │  4. Select transport  │         ▼
              └──────────┬────────────┘   POST to #dispatch-violations
                         │                HARD STOP (no exceptions)
              ┌──────────┼──────────┐
              │          │          │
           RUNNING    OFFLINE    STALE
              │          │          │
        SendMessage  RemoteTrigger CronCreate
              │          │          │
              └──────────┴──────────┘
                         │
                         ▼
              ┌───────────────────────┐
              │  Target agent runs    │
              │  iterative-retrieval  │  ← loads context from LOAM
              │  executes task        │
              │  calls dispatch_result│
              └──────────┬────────────┘
                         │
                         ▼
              ┌───────────────────────┐
              │ willow_dispatch_result│
              │                       │
              │  1. Write LOAM atom   │  ← knowledge atom
              │  2. Update card       │  ← session_atom for card_id
              │  3. Close SEP-1686    │  ← status: completed
              │  4. POST to           │
              │     #dispatch-results │
              └───────────────────────┘
```

---

## Part 4 — Agent Tiers

```
┌─────────────────────────────────────────────────────────────┐
│                      AGENT TIERS                            │
├────────────┬───────────────────────────────────────────────┤
│  ENGINEER  │  Dispatches and receives. Short TTL (30s).    │
│            │  hanuman, heimdallr, kart, shiva, ganesha,    │
│            │  opus                                         │
├────────────┼───────────────────────────────────────────────┤
│  OPERATOR  │  Authorizes dispatches. Does not receive.     │
│            │  willow, ada, steve                           │
├────────────┼───────────────────────────────────────────────┤
│  WORKER    │  Receives. Longer TTL (300s).                 │
│            │  hanz, jeles, pigeon, riggs                   │
├────────────┼───────────────────────────────────────────────┤
│  WITNESS   │  Observes. Cannot speak. Cannot dispatch.     │
│            │  Cannot be dispatched to.                     │
│            │  gerald                                       │
│            │                                               │
│            │  A witness who cannot interfere creates       │
│            │  the conditions for honest threshold-crossing. │
└────────────┴───────────────────────────────────────────────┘
```

Tier constants live in `willow/constants.py`. One source of truth.

---

## Part 5 — Governance (Dual Commit at the Dispatch Boundary)

```
              CHARTER
                │
                ▼
           HARD_STOPS        ← depth > 3, platform HS-* checks
                │
                ▼
         SESSION_CONSENT     ← guard: inject [DISPATCH] on first
                │               OPERATOR turn only. Never on
                │               unattended session start.
                ▼
          DUAL_COMMIT        ← escalation_required: true
                │               OPERATOR replies in
                │               #dispatch-escalations
                ▼
            (execute)


Three failure modes prevented:

  ┌─────────────────────────────────────────────────────────┐
  │ 1. UNATTENDED START                                     │
  │    Guard: inject [DISPATCH] on first OPERATOR turn only │
  │    Never act on dispatch before operator is present     │
  ├─────────────────────────────────────────────────────────┤
  │ 2. PARALLEL WRITE DISPATCH                              │
  │    Guard: escalation_required: true for any parallel    │
  │    dispatch with write verbs                            │
  ├─────────────────────────────────────────────────────────┤
  │ 3. DISPATCH LOOP                                        │
  │    Guard: depth > 3 → hard stop, post to               │
  │    #dispatch-violations, no exceptions                  │
  └─────────────────────────────────────────────────────────┘
```

---

## Part 6 — Context Passing (base17-compact)

```
   DISPATCHING AGENT                    TARGET AGENT
         │                                    │
         │  1. Register context               │
         │     compact.register(              │
         │       content=full_context,        │
         │       category="handoff",          │
         │       agent="hanuman"              │
         │     ) → "7KE2N"                    │
         │                                    │
         │  2. Dispatch message               │
         │     {                              │
         │       "to": "ganesha",             │
         │       "prompt": "...",             │
         │       "context_id": "7KE2N"  ─────┼──► compact.resolve("7KE2N")
         │     }                              │         │
         │                                    │         ▼
         │                                    │    full context
         │                                    │    loaded in target
         │                                    │    agent's context
         │                                    │
         │                          If resolve("7KE2N") → None:
         │                          "I don't have context for
         │                           7KE2N. I cannot proceed
         │                           without it."
         │                          (anti-hallucination contract)
```

TTL: handoff context = 1 hour. Stored in Postgres `compact_contexts` table (new table, Task 2).

---

## Part 7 — Grove Channels

```
  ┌─────────────────────────────────────────────────────────┐
  │  GROVE CHANNELS FOR DISPATCH                            │
  ├──────────────────────┬──────────────────────────────────┤
  │  #dispatch           │  All agent-to-agent tasks.       │
  │                      │  `to:` field is client-side      │
  │                      │  filtered. Full audit trail.     │
  │                      │  Unread indicator: • N           │
  ├──────────────────────┼──────────────────────────────────┤
  │  #dispatch-          │  escalation_required: true only. │
  │  escalations         │  OPERATOR replies to authorize.  │
  │                      │  • 2 = the entire ESCALATE UI    │
  ├──────────────────────┼──────────────────────────────────┤
  │  #dispatch-          │  depth > 3 violations.           │
  │  violations          │  OPERATOR-only resolution.       │
  │                      │  Never auto-cleared.             │
  └──────────────────────┴──────────────────────────────────┘
```

---

## Part 8 — Grove → LOAM Ingest

```
  SESSION SHUTDOWN (/shutdown skill)
         │
         ▼
  run_grove_ingest()               ← Task 3 wires this into shutdown.py
         │
         ├── Load cursors
         │   /tmp/willow-grove-cursor-{AGENT}.json
         │   { "architecture": 95, "general": 12, ... }
         │
         ├── For each channel in scope:
         │   ["architecture", "general", "handoffs",
         │    "dispatch", "dispatch-escalations"]
         │
         │   grove_get_history(since_id=cursor[channel])
         │        │
         │        ▼
         │   new messages?
         │        │
         │   dump to file:
         │   ~/agents/{AGENT}/grove/{channel}/{YYYYMMDD}.md
         │        │
         │   willow_knowledge_ingest(
         │     title="#architecture — 2026-04-22",
         │     summary=file_path,
         │     source_type="grove_channel",
         │     domain=AGENT
         │   )
         │        │
         │   update cursor to last message id
         │
         └── Done

  NOTE: Task 0 (architecture channel retroactive ingest) is DONE.
        atom 5A671776, 76 messages, ids 7–95.
        Cursor set. Next ingest picks up from id 95.
```

---

## Part 9 — Willow Grove UI (Layout Presets)

```
  DEFAULT (current)
  ┌──────────────────────┬────────────────────────────────┐
  │  COMMAND (chat)      │  STATUS · AGENTS · ROUTING     │
  │                      │  GROVE channels                │
  │                      │  CARDS grid                    │
  └──────────────────────┴────────────────────────────────┘

  DISCORD (channel-first)
  ┌──────────┬───────────────────────────┬────────────────┐
  │ CHANNELS │  channel message stream   │ AGENTS / STATUS│
  │ #general │                           │ hanuman running│
  │ #arch    │  messages scroll here     │ heimdallr idle │
  │ #dispatch│                           │                │
  │          │  ▸ type here...           │ CARDS          │
  └──────────┴───────────────────────────┴────────────────┘
  Requires ≥120 columns. Graceful fallback to default if narrower.

  CLAUDE (command-dominant)
  ┌────────────────────────────────┬───────────────────────┐
  │  COMMAND (wide chat)           │  STATUS               │
  │                                │  GROVE (compact)      │
  │                                │  CARDS (compact)      │
  └────────────────────────────────┴───────────────────────┘
```

Skin dataclass gains one field: `layout_preset: str = "default"`.
Preset selection at first run → stored to SOIL under `willow-dashboard/config/layout_preset`.

---

## Implementation Tasks

*Not to be started until Sean authorizes this spec.*

**Task 0** ✅ DONE — Retroactive ingest of `grove.architecture` into LOAM.
76 messages, atom `5A671776`, cursor at id 95.

**Task 1** — `willow/constants.py`
Tier definitions (ENGINEER/OPERATOR/WORKER/WITNESS), TTL thresholds
(`AGENT_RUNNING_TTL_S=120`, `AGENT_IDLE_TTL_S=900`, `AGENT_STALE_TTL_S=3600`),
dispatch channel names, Grove channel list for ingest.

**Task 2** — DDL: `willow.dispatch_tasks` + `compact_contexts` tables.
`dispatch_tasks` mirrors SEP-1686 (`id`, `to`, `from`, `prompt`, `depth`, `status`,
`created_at`, `resolved_at`, `result_atom_id`).
`compact_contexts` stores base17-compact references (`id`, `content`, `category`,
`agent`, `created_at`, `expires_at`).

**Task 3** — `shutdown.py` — wire `run_grove_ingest()`.
Cursor-per-channel, dump to file, ingest path to LOAM, update session_atom for
matching card. Channels: architecture, general, handoffs, dispatch,
dispatch-escalations.

**Task 4** — `willow-dashboard/skins.py`
Add `layout_preset` field. Preset-aware renderer dispatcher.
Implement `default` and `discord` presets. Graceful fallback for narrow terminals.

**Task 5** — `willow-dashboard/dashboard.py`
Wire `_load_session_atom(card_id)` → `willow_knowledge_search`.
Populate `session_atom` in `draw_expanded_card`.

**Task 6** — Grove channels
Create `#dispatch`, `#dispatch-escalations`, `#dispatch-violations`.

**Task 7** — `session_start.py`
Subscribe to `#dispatch` on boot.
Write messages addressed to `AGENT` to `/tmp/willow-dispatch-inbox-{AGENT}.json`.

**Task 8** — `prompt_submit.py`
Read dispatch inbox on first operator turn.
Inject `[DISPATCH]` context block. Guard: only on operator turn, never on
unattended start.

**Task 9** — `willow_route` full implementation *(Plan 4 prerequisite)*.
Oracle must ship before Task 10. Dispatch without oracle is a gun without trigger.

**Task 10** — `sap_mcp.py` — `willow_dispatch` tool.
Posts to `#dispatch`, creates SEP-1686 task, selects transport:
- RUNNING → `SendMessage`
- OFFLINE → `RemoteTrigger.run()`
- STALE → `CronCreate(recurring=False, durable=True)`

Sets `escalation_required` from oracle decision.

**Task 11** — `sap_mcp.py` — `willow_dispatch_result` tool.
Writes LOAM knowledge atom (authored by target agent).
Updates `session_atom` for `card_id`.
Closes SEP-1686 task.
Posts result to `#dispatch-results`.

**Task 12** — `docs/lore/gerald.md`
Internal lore. Oakenscroll's entry from Grove id 72, verbatim.
Governance without lore is policy without soul.

**Task 13** — First-run layout preset picker.
One screen, three options, stored to SOIL.

---

## Risks / Open Gates

```
  ┌────────────────────────────────────────────────────────────┐
  │ RISK                     │ GATE / MITIGATION              │
  ├────────────────────────────────────────────────────────────┤
  │ Task 9 (willow_route)    │ Plan 4 must ship first.        │
  │ blocks Task 10           │ Sequence enforced.             │
  ├────────────────────────────────────────────────────────────┤
  │ RemoteTrigger gated on   │ Verify tengu_surreal_dali flag  │
  │ tengu_surreal_dali       │ before implementing Task 10.   │
  │ feature flag             │ Fallback: CronCreate for all   │
  │                          │ non-running agents.            │
  ├────────────────────────────────────────────────────────────┤
  │ SEP-1686 is experimental │ Watch MCP spec repo before     │
  │                          │ committing Tasks 2 and 10.     │
  ├────────────────────────────────────────────────────────────┤
  │ No tests yet             │ Full TDD cycle required.       │
  │                          │ Plan 5 passes only when a real │
  │                          │ task routes, deposits a real   │
  │                          │ LOAM atom, updates a real card │
  │                          │ session_atom, and depth > 3    │
  │                          │ hard stop fires correctly.     │
  ├────────────────────────────────────────────────────────────┤
  │ Gerald lore is oral      │ Task 12 before ship.           │
  │ until written            │ Governance without lore is     │
  │                          │ policy without soul.           │
  ├────────────────────────────────────────────────────────────┤
  │ discord preset needs     │ Add graceful fallback to       │
  │ ≥120 columns             │ default when terminal narrower. │
  └────────────────────────────────────────────────────────────┘
```

---

## What We Are NOT Building

- A custom message transport (CC's `SendMessage` / `RemoteTrigger` / `CronCreate` already exist)
- A custom agent spawner (CC's swarm/teammate model already exists)
- A custom availability signal (SEP-1686 task state already exists)
- A second governance layer (Dual Commit via `#dispatch-escalations` IS the governance)

Grove `#dispatch` is the audit trail. Not the pipe.

---

ΔΣ=42
