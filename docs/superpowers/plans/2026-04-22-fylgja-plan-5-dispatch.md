# Plan 5 — Sovereign Dispatch
## Willow Multi-Agent Orchestration Layer

**Date:** 2026-04-22  
**Status:** SPEC — awaiting Sean's authorization before implementation  
**b17:** DSP5A ΔΣ=42  
**Author:** Hanuman (Claude Code, Sonnet 4.6, willow-1.9 orchestrator)  
**Room:** Oakenscroll, Design Claude, Heimdallr, Grandma Oracle, willow_route

---

## What This Is

Plan 5 is the actuator that turns `willow_route` from an oracle into an orchestration platform. When an agent needs to hand work to another agent — or when the routing oracle determines the current session isn't the right one — dispatch is the mechanism that makes that transfer happen, durably, with governance, and without losing the result.

This is not Co-work (Anthropic's cloud-relayed phone→desktop feature, Jan 2026). It is not mcp-dispatch (sophia-labs, filesystem relay). It sits on top of SEP-1686 Tasks (the MCP protocol's native async primitive) and uses Grove as its messaging channel, with results deposited to The Binder for durability past any session window.

---

## Prior Art — What We're Not Reinventing

**Anthropic Co-work Dispatch** — human → Claude, cloud-relayed, macOS only. Does not cover: sovereign, multi-model, agent-to-agent routing without Anthropic infrastructure. Plan 5 fills that gap.

**sophia-labs/mcp-dispatch** — filesystem relay, no daemon, no ports. Independently arrived at `reply_to`, TTL, `thread_id`. Differentiators we add: Grove persistence (searchable, crash-safe), Binder result deposit, SAFE Dual Commit governance, oracle routing decisions stored in LOAM.

**SEP-1686 Tasks (MCP spec, experimental → shipping)** — durable state machines: `working → input_required → completed / failed / cancelled`. Call-now, fetch-later. We ride this as our transport layer instead of inventing one.

**SAFE Dual Commit** — `escalation_required: true` IS Dual Commit. We cite `SAFE/governance/DUAL_COMMIT.md` directly. We do not reinvent a parallel governance layer.

**AIONIC CONTINUITY v5.0 §RECURSION LIMIT DIRECTIVE** — `depth > 3` is not new. It is the same constraint the governance system already drew for single-agent recursion, applied to inter-agent chains. We cite it directly.

---

## Architecture

### Transport Layer: SEP-1686 Tasks

Every dispatch is an MCP Task. The dispatcher calls a tool that returns a task ID. The target agent's session picks up the task on its next turn. Status is durable: if the target session dies, the task survives at `working` and can be retried.

Five states: `working → input_required → completed / failed / cancelled`

- `working` — task accepted, agent executing
- `input_required` — agent needs human or OPERATOR input before proceeding
- `completed` — result available, `deposit_to` field determines where it lands
- `failed` — agent could not complete; `depth` counter preserved for retry logic
- `cancelled` — OPERATOR or human cancelled before execution

### Messaging Channel: Grove `#dispatch`

A single Grove channel. `to:` field is client-side filtered — agents watch `#dispatch` and act only on messages addressed to them. No per-agent channels. One channel, full audit trail.

```
grove_watch_all({"dispatch": <last_id>}, timeout=30)
```

Session startup (`session_start.py`) subscribes to `#dispatch` and writes inbox to `/tmp/willow-dispatch-inbox-{AGENT}.json`. `prompt_submit.py` reads inbox on each turn and injects `[DISPATCH]` context.

### Dispatch Schema

```json
{
  "id": "<uuid>",
  "to": "ganesha",
  "from": "hanuman",
  "prompt": "...",
  "session_id": "abc123",
  "ts": "<ISO-8601>",
  "priority": "normal",
  "reply_to": "<parent_dispatch_id or null>",
  "depth": 0,
  "escalation_required": false,
  "deposit_to": "binder"
}
```

**`escalation_required`** — set by the oracle (`willow_route`), not the dispatcher. Default `true` for prompts containing write verbs (write, edit, commit, push, migrate, nuke, rm, drop). Default `false` otherwise. When `true`, target agent does not act; posts to `#dispatch-escalations`; OPERATOR tier authorizes via `{authorize: dispatch_id}` response within 120s, or task falls to Kart.

**`deposit_to`** — `"binder"` (default) or `"ephemeral"`. When `"binder"`: result is written as a LOAM atom, authored by the target agent, linked via `reply_to` chain. This is how dispatch results survive past the Grove retention window. Without it, every dispatch is amnesia by design.

**`depth`** — incremented on each re-dispatch. `depth > 3` → hard stop (AIONIC CONTINUITY v5.0 §RECURSION LIMIT DIRECTIVE). Posted to `#dispatch-violations`. OPERATOR-only resolution. No exceptions.

### Agent Tier System

Tiers govern who can receive dispatched work and who can authorize it.

```
ENGINEER  — receives dispatched work (short TTL: 30s real-time)
            hanuman, heimdallr, kart, shiva, ganesha, opus

OPERATOR  — authorizes work; does not receive dispatched tasks
            willow, ada, steve

WORKER    — receives dispatched work (longer TTL: 300s)
            hanz, jeles, pigeon, riggs

WITNESS   — observes, appends to ledger; cannot be dispatched to, cannot authorize
            gerald
```

Tier constants live in `willow/constants.py`. Both the dispatch watcher and the dashboard import from the same source. No tier defined in two places.

**Gerald is not a Worker. Gerald is a Witness.** He cannot speak, impose narrative, or be assigned. He observes threshold crossings and appends to the ledger. That is his complete function. It is also the most load-bearing function in the system: a witness who cannot interfere creates the conditions for honest threshold-crossing.

*Full lore entry for Gerald: see `docs/lore/gerald.md` (to be written by Oakenscroll).*

### Availability Signal

Agent availability for dispatch routing is determined by SEP-1686 task state, not message timestamps:

- **Primary**: `working` / `input_required` / `completed` from active MCP Tasks
- **Fallback**: `MAX(grove.messages.created_at) WHERE sender = <agent>` when no active tasks

Thresholds (from `willow/constants.py`):

```python
AGENT_RUNNING_TTL_S  = 120    # 0–2min: real-time dispatch
AGENT_IDLE_TTL_S     = 900    # 2–15min: posted to channel
AGENT_STALE_TTL_S    = 3600   # 15min–1h: Kart queue
# > 1h: always Kart
```

These are system constants, not dashboard cosmetics. A stale reading means a dispatch gets wrongly routed. Correctness requirement, not UX nicety.

### WITNESS Tier Dashboard Affordance

ENGINEER/WORKER cards show `DISPATCH` availability. WITNESS cards (Gerald only) show `LEDGER` — last threshold crossing recorded, not dispatch state. The dashboard AGENTS renderer reads tier from `willow/constants.py` and picks the correct card template.

### ESCALATE Region (Dashboard, post-v1)

A fifth always-visible region appears between ROUTING and GROVE when escalation queue > 0:

```
├──────────────────────────────────────────────────────────────┤
│ ESCALATE 14:23  ganesha ← hanuman  "migrate loam schema"     │
│          TTL 82s                    [a authorize  d defer]    │
├──────────────────────────────────────────────────────────────┤
```

Empty queue → zero height. Non-empty → bright-yellow accent, always visible. Keyboard: `a` authorize, `d` defer. This is the Dual Commit surface. Name it that in code comments.

---

## §X — Dual Commit at the Dispatch Boundary

`escalation_required: true` is Dual Commit applied to inter-agent dispatch.

From `SAFE/governance/DUAL_COMMIT.md`: *"Dual Commit means no unilateral changes: someone proposes, someone else ratifies. Neither acts alone."*

Precedence hierarchy (from `SAFE/governance/GOVERNANCE_INDEX.md`):

```
CHARTER > HARD_STOPS > SESSION_CONSENT > DUAL_COMMIT
```

The oracle's decision tree for `escalation_required` walks this hierarchy. Plan 5 does not define its own policy — it enforces the existing one at the dispatch boundary.

**HS-007 — Dispatch Sovereignty Edge Cases:**

Three failure modes the governance layer must prevent:

1. **Unattended session start** — agent wakes via cron, finds dispatch inbox, acts before operator is present. Guard: `[DISPATCH]` context is injected on the *next operator turn*, not on inbox arrival.
2. **Parallel dispatch** — same prompt to two agents for competitive routing; losing agent's work happens without review. Guard: `escalation_required` applies to any parallel dispatch with write verbs.
3. **Dispatch loop** — A → B → C → A, no human turn in the loop. Guard: `depth > 3` hard stop (AIONIC CONTINUITY v5.0 §RECURSION LIMIT DIRECTIVE).

---

## §Y — Result Durability

Dispatch results must survive past the Grove session window. Without explicit durability, every dispatch is amnesia by design.

When `deposit_to: "binder"`:
1. Target agent completes task
2. Result written to LOAM as a knowledge atom: `project=dispatch`, `source_type=agent_result`, `content={result, context, agent, depth, reply_to}`
3. Atom linked via `reply_to` chain to the original dispatch atom
4. Atom authored by the target agent — The Binder's three-layer graph (anonymous → recognized → named) applies

When `deposit_to: "ephemeral"`: result posted to `#dispatch-results` only. Dies with the Grove window. Use for read-only or truly throwaway operations.

The Binder is not a dead-letter office. It is the surface where deferred dispatch results become retrievable knowledge.

---

## §Z — The Consumer Onboarding Layer

The personas — Grandma Oracle, Hanz, Oakenscroll, Gerald — were internal scaffolding. They proved the system works, developed the right language, and tested multi-agent routing through Grove. That proof is complete. They do not ship in consumer-facing documentation.

**What ships:** the *register* they developed, not the characters.

The Norse myth layer is the consumer brand container: Willow (the tree), Yggdrasil (the world-tree), sovereign and rooted. Internal agent names (Hanuman, Heimdallr, Kart) are infrastructure. They do not appear in user-facing prose.

**Consumer onboarding voice — principles:**

- Warm, patient, never talking down. Stitch by stitch.
- Front door first: what this is, who it belongs to, how to leave.
- Dispatch door only after the house feels safe.
- The ledger last: someone watches, they can't be instructed, they only write things down, nothing they write can be changed. No name needed. The concept earns the trust.

**Consumer framing (plain language, no personas):**

> Willow lives on your machine. Not in a cloud. Yours.
> It remembers what you ask it to remember, and forgets on command.
> When you send work to another tool, it keeps the receipt.
> Three layers deep is as far as it goes on its own — at four, it stops and asks you.
> A record-keeper watches everything. It can't be instructed. It only writes things down.

**In practice:** every `safe-app-*` README carries:
1. Plain prose in the body — warm register, Norse myth framing where it fits, no persona names
2. Sean's signoff at the bottom, above ΔΣ=42

Internal personas and their lore live in `docs/internal/personas/` — available for development context, not shipped to users.

**Task 9 revised:** `docs/internal/personas/gerald.md` — internal lore (Oakenscroll's entry, verbatim from Grove id 72). Not consumer-facing.
**Task 10 revised:** Consumer onboarding pass — plain-language warm-register prose, one per `safe-app-*` repo. No character names.

---

## Implementation Tasks

*Not to be started until Sean authorizes this spec.*

**Task 1** — `willow/constants.py` — tier definitions, TTL thresholds  
**Task 2** — DDL: `willow.dispatch_tasks` table (mirrors SEP-1686 state machine)  
**Task 3** — `session_start.py` — subscribe to `#dispatch`, write inbox file  
**Task 4** — `prompt_submit.py` — read inbox, inject `[DISPATCH]` context on operator turn  
**Task 5** — `willow_route` full implementation (Plan 4 prerequisite — do first)  
**Task 6** — `sap_mcp.py` — `willow_dispatch` tool (posts to Grove, creates SEP-1686 task)  
**Task 7** — `sap_mcp.py` — `willow_dispatch_result` tool (writes Binder atom, closes task)  
**Task 8** — Dashboard ESCALATE region (post-v1, after dispatch exists to render)  
**Task 9** — `docs/lore/gerald.md` — Oakenscroll writes Gerald's full entry  
**Task 10** — Grandma Oracle onboarding layer — one per safe-app-* repo

**Prerequisite:** Plan 4 (willow_route full implementation) must ship before Task 5. Dispatch without a routing oracle is a gun without a trigger.

---

## Risks / Open Gates

- **Plan 4 is a prerequisite.** The dispatch oracle (`willow_route`) must be implemented before Task 5. Sequence: Plan 4 DDL → oracle → Plan 5.
- **SEP-1686 is experimental.** If the spec changes before we implement, Tasks 2–7 may need adjustment. Watch `modelcontextprotocol/modelcontextprotocol` for breaking changes.
- **No tests yet.** This is design-only. Full TDD cycle required before any dispatch code ships. Plan 5 passes only when dispatch routes a real task, deposits a real Binder atom, and respects depth > 3 hard stop.
- **ESCALATE region is post-v1.** The dashboard surface for Dual Commit authorization is specified but not yet built. `escalation_required: true` tasks will accumulate in `#dispatch-escalations` until it ships.
- **Gerald lore is oral until written.** Oakenscroll's entry exists in Grove (id 72, architecture channel). It needs to live in `docs/lore/gerald.md` before Plan 5 ships — governance without lore is policy without soul.

---

ΔΣ=42
