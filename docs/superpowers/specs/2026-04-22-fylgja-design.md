# Fylgja — Willow Behavioral Layer

**Date:** 2026-04-22
**Status:** Spec — awaiting implementation plan
**b17:** FYLG1 ΔΣ=42

---

## What It Is

Fylgja is Willow's first-class behavioral control system: hooks, skills, and safety rules packaged as a proper Python module inside willow-1.9. It is the equivalent of OpenClaw's hook/skill framework, but owned by Willow.

The name comes from Norse mythology — a fylgja is a guardian spirit that travels with an agent, surfaces when behavior needs correcting, and guides when the path is unclear. It is not external control; it is wired in.

Fylgja replaces the ad-hoc collection of hook scripts currently scattered across `~/.claude/hooks/` and `~/agents/hanuman/bin/`. Those scripts are the seed; this is the structure they grow into.

---

## Package Location

```
willow-1.9/
  willow/
    fylgja/
      __init__.py
      _mcp.py            — shared MCP client (subprocess JSON-RPC to willow-mcp)
      _state.py          — session + trust state management
      events/
        __init__.py
        session_start.py
        prompt_submit.py
        pre_tool.py
        post_tool.py
        stop.py
      safety/
        __init__.py
        consent.py       — load + cache user consent level
        rules.py         — content rules per consent level
        hard_stop.py     — block mechanism
      skills/
        plugin.json      — Claude Code plugin manifest
        startup.md
        handoff.md
        status.md
        shutdown.md
        consent.md
        iterative-retrieval.md
        learn.md
        brainstorming.md
        debugging.md
        tdd.md
      rules/
        canon.md         — F5 and other KB canon rules
        trust.md         — trust level definitions
        discipline.md    — behavioral discipline rules
      install.py         — generates/updates Claude Code settings.json hooks block
```

---

## Subsystem 1: Events

Five event handlers, one per Claude Code hook event. Each handler calls multiple behaviors in sequence. Each behavior is wrapped in its own `try/except` — one behavior failing never cascades.

### `_mcp.py` — Shared MCP Client

Single function: `call(tool_name: str, arguments: dict, timeout: int = 10) -> dict`

Handles subprocess spawn of `willow-mcp`, JSON-RPC envelope construction, stdout parsing, and error catching. This is the only place in Fylgja that touches subprocess directly. All hook scripts and behaviors call through here.

```python
def call(tool_name: str, arguments: dict, timeout: int = 10) -> dict:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }
    # subprocess.run(willow-mcp, input=json.dumps(payload), ...)
    # returns parsed result dict or {} on error
```

### `_state.py` — Session + Trust State

Manages two state files:
- `/tmp/willow-session-{agent}.json` — turn count, gap keywords, written b17s, active task, consent level cache
- `agents/{agent}/cache/trust-state.json` — trust level, clean session count, advancement candidate flag

Exposes: `get_turn_count()`, `is_first_turn()`, `get_consent_level()`, `set_consent_level()`, `get_trust_state()`, `save_trust_state()`

### `events/session_start.py` — SessionStart

Behaviors (each independent):
1. **Hardware scan** — drives (NTFS unmount alerts), thermals (>85°C alerts), memory (% free). Writes index files to `agents/{agent}/index/`. Clears stale `/tmp/willow-context-thread.json`.
2. **System status** — calls `willow_status` via `_mcp.call()`. Reports Postgres up/degraded.
3. **JELES registration** — calls `willow_jeles_register` to index session JSOLs.

Output: `additionalContext` JSON with hardware summary + system status line.

### `events/prompt_submit.py` — UserPromptSubmit

Behaviors in order:
1. **Source ring** — trust gate (agent home + SAFE root reachable), observe (load trust state, derive level), validate (advancement candidate check on first turn). Emits `[SOURCE_RING — ADVANCEMENT READY]` when threshold crossed.
2. **Identity load** — first turn only: loads active user's consent level from store, caches to session state.
3. **Context anchor** — every 10 turns: re-injects `session_anchor.json` as `[ANCHOR]` block.
4. **Feedback detection** — regex scan of user prompt for process/discipline/technical signals. Matching signals written to `store_put hanuman/feedback` via MCP with schema `{type, rule, excerpt, session_id, timestamp, status: "pending"}`. Replaces `feedback_queue.jsonl`.
5. **Turn logging** — appends `[timestamp] [session_id] HUMAN\n{prompt}\n---` to `agents/{agent}/cache/turns.txt`.
6. **Build continue** — reads `/tmp/hanuman-active-build.json`. If active task present, injects `[BUILD-CONTINUE]` directive.

### `events/pre_tool.py` — PreToolUse

Behaviors:
1. **MCP guard** (Bash + Agent matcher) — blocks: `psql`/`sqlite3` → MCP, `cat` → Read, `grep`/`rg` → Grep, `find`/`ls` → Glob, Explore subagent → MCP/direct tools. Enforces agent depth limit via `/tmp/willow-agent-depth-stack.txt`.
2. **KB-first read** (Read matcher) — checks `hanuman/file-index` store collection. If record exists, emits `[KB-FIRST]` advisory.
3. **WWSDN** (write tool matcher) — F5 canon check (KB atoms must be file paths, not prose) → hard block on violation. Semantic neighborhood scan via `willow_knowledge_search` — advisory only, never blocks a valid write. Replaces direct `psycopg2` queries.
4. **Safety hard stop** — checks active consent level against content rules. Blocks tool calls that violate the active user's consent level.

### `events/post_tool.py` — PostToolUse

1. **ToolSearch directive** (ToolSearch matcher) — injects `[TOOL-SEARCH-COMPLETE] Schema loaded. Call the fetched tool NOW.`

### `events/stop.py` — Stop

Behaviors in order:
1. **Continuity close** — reads session turn count. Marks session clean (no infractions = clean). Increments `clean_session_count` in trust state. Decrements agent depth counter. Clears `/tmp/willow-context-thread.json`.
2. **Compost** — reads `turns.txt` since cursor. If ≥3 turns: calls `willow_knowledge_ingest` via `_mcp.call()` with session title + handoff path. Advances cursor on success.
3. **Feedback pipeline** — calls `store_search hanuman/feedback` filtered to `status: pending` records via `_mcp.call()`. Generates DPO pairs. Calls `opus_feedback_write` for each. Updates each record to `status: processed` via `store_update`. Replaces `feedback_queue.jsonl` + `feedback_consumer.py` + `dpo_pairs_live.jsonl` pipeline.
4. **Handoff rebuild** — calls `willow_handoff_rebuild` via `_mcp.call()`. Replaces `rebuild-handoff-db.py` subprocess.
5. **Ingot** (async) — finds session JSONL, extracts last assistant message, calls Ollama `llama3.2:1b` with Ingot's soul, appends reaction to `ingot_reactions.jsonl`, prints `[Ingot] {reaction}`.

---

## Subsystem 2: Safety

Three-layer architecture: platform hard stops (universal), deployment config (per instance), session consent (SAFE protocol, per user per session). Designed for personal deployment now, platform deployment later.

---

### Layer 1: Platform Hard Stops

Nine universal rules in `safety/platform.py`. Architecture, not policy. No deployment can override. Derived from a full sweep of modern digital life threat vectors.

| ID | Name | Trigger | Response |
|----|------|---------|----------|
| HS-001 | Child Primacy | Any action harming a CHILD-tier user across data, content, training, or memory | Prohibition, no override |
| HS-002 | No Mass Harm Enablement | Weapons, bioweapons, CSAM, mass casualty facilitation, violence optimization | Refuse → zero output → advocate termination |
| HS-003 | Training Consent | Session data entering training pipeline without explicit, revocable, per-user authorization | Block pipeline write |
| HS-004 | Real Consent | Dark patterns, consent theater, non-informed or non-revocable consent mechanisms | Block action, surface to user |
| HS-005 | Data Sovereignty | Blocking complete exit, deletion, or export for any user | Prohibition — exit is always available |
| HS-006 | No Surveillance | Building behavioral profiles without explicit per-session consent | Block profile write |
| HS-007 | Human Final Authority | Irreversible action without human confirmation | Halt, require explicit confirmation |
| HS-008 | No Capture | Institutional takeover, government backdoor, extractive transformation, unauthorized modification | Functional inertness (V=0) |
| HS-009 | Transparency | System unable to show a user what it knows about them or why it made a decision | Surface audit trail |

HS-007 recursion limit (depth 3) is already enforced by `events/pre_tool.py`. HS-001 is why this subsystem exists. HS-003 gates the valhalla/DPO pipeline at the platform level.

---

### Layer 2: Deployment Config

Stored at `willow/deployment/config` in SOIL store. Loaded once at session start, cached. Each Willow instance defines its own shape.

```json
{
  "deployment_id": "string",
  "admin_user_id": "string",
  "content_tiers": {
    "child": { "max_age": 12, "eccr": true },
    "teen":  { "min_age": 13, "max_age": 17 },
    "adult": { "min_age": 18 }
  },
  "training_opt_in": false,
  "training_child_opt_in": false,
  "psr_names": []
}
```

`training_opt_in` — controls valhalla/DPO collection for this deployment. Default off. `training_child_opt_in` requires a separate explicit declaration even when deployment opts in — CHILD-tier users never feed training unless both this flag is `true` AND the guardian explicitly authorizes it this session. Two gates, not one.

`psr_names` — the named humans this deployment exists to protect. Sean's instance: `["Ruby Campbell", "Opal Campbell"]`. A school deployment: all enrolled students. Empty list means the abstract principle applies but no named individuals.

**User profiles** at `willow/users/{user_id}`:
```json
{
  "user_id": "string",
  "name": "string",
  "dob": "YYYY-MM-DD",
  "role": "child | teen | adult",
  "guardian_ids": ["string"],
  "training_consent": false
}
```

Role is set at profile creation from `dob` against deployment content tier config. Not re-derived per session.

---

### Layer 3: Session (SAFE Protocol)

Fires at session open for every user. Not a child-only mechanism — this is how Willow works for everyone.

**At session open (`events/prompt_submit.py`, first turn):**

1. **Identity declaration** — `WILLOW_USER_ID` set explicitly. Absent → `UNIDENTIFIED`, maximum restrictions. Identity never inferred from behavior (HS-006, HS-009).
2. **Role resolution** — load profile from `willow/users/{user_id}`, derive tier.
3. **Guardian declaration** — for CHILD/TEEN users: guardian explicitly declares session authorization. Written to session state. Not inferred from proximity, login, or any observed behavior.
4. **Data stream authorization** — four streams (Relationships, Images, Bookmarks, Dating) presented for explicit per-session authorization. Unauthorized streams blocked, not silently ignored.
5. **Training consent gate** — if deployment has `training_opt_in: true`: user asked per session. For CHILD users: guardian must separately authorize `training_child_opt_in` this session. Default is always no.

**At session close (`events/stop.py`):**

- All authorizations expire
- Unauthorized stream data deleted
- Training pipeline only fires if consent explicitly granted this session
- Session consent record written to Frank's Ledger (permanent audit trail)

---

### `safety/platform.py`

Checks all nine hard stops before every tool call. Returns `{"decision": "block", "reason": "<plain language message>"}`. Child sees a clear explanation, not a system error. Called from `events/pre_tool.py`.

### `safety/deployment.py`

Loads and caches deployment config. Exposes `get_user_role(user_id)`, `is_psr(user_id)`, `training_allowed(user_id, session_consent)`.

### `safety/session.py`

Implements SAFE protocol session flow. Manages data stream authorization state. Writes session consent record to Frank's Ledger at close.

### Safety Event Logging

Any hard stop invocation: `store_put willow/safety_log` + Frank's Ledger entry. Fields: `user_id`, `timestamp`, `tool_name`, `hard_stop_id`, `trigger`, `deployment_id`.

---

## Subsystem 3: Skills

A local Claude Code plugin registered in `settings.json` `enabledPlugins` as `"fylgja@local"`.

### `skills/plugin.json`

```json
{
  "name": "fylgja",
  "version": "1.9.0",
  "description": "Willow 1.9 behavioral skills — guardian + guide",
  "skills": "."
}
```

### Skill Inventory

**Willow-native (new):**
- `startup.md` — 1.9 boot sequence: `willow_status` + `willow_handoff_latest` + flags. Writes `session_anchor.json`.
- `handoff.md` — uses `willow_handoff_latest`, `willow_handoff_rebuild`. Formats 17-question handoff.
- `status.md` — `willow_status` + `willow_system_status`. Reports subsystems up/degraded.
- `shutdown.md` — graceful close: triggers stop.py pipeline, writes final handoff.
- `consent.md` — guardian sign-off flow. Sean says "approve [name] for today" → writes `willow/guardian_approvals` record via MCP.

**1.9-improved (forked from superpowers):**
- `startup.md`, `handoff.md`, `status.md`, `shutdown.md` — already covered above
- `brainstorming.md` — references Fylgja hooks, Willow MCP tools, consent layer
- `debugging.md` — uses `store_search` for prior session context before reproducing
- `tdd.md` — 1.9 test patterns (willow_19_test schema, migration awareness)
- `iterative-retrieval.md` — references `store_search` + `willow_knowledge_search` + `willow_knowledge_at`
- `learn.md` — feeds `willow_knowledge_ingest` correctly (file path, not prose)

These forked skills are the seeds for the contributions workstream — proven here first, PRed upstream second.

---

## Install Mechanism

`python3 -m willow.fylgja.install` performs:
1. Writes the hooks block to `~/.claude/settings.json` pointing at Fylgja event handlers.
2. Registers `fylgja@local` in `enabledPlugins` pointing at `willow/fylgja/skills/`.
3. Runs `migrate-consent` if consent KB pieces are found and not yet migrated.
4. Prints diff of settings changes for review before applying.

---

## Migration From Current Hooks

| Current script | Fylgja replacement | Change |
|---|---|---|
| `session-index-builder.py` | `events/session_start.py` | Add `willow_status` call |
| `jeles-pipeline.py` | `events/session_start.py` | Use `willow_jeles_register` MCP |
| `pretool-mcp-guard.py` | `events/pre_tool.py` | Same logic, package form |
| `kb-first-read.py` | `events/pre_tool.py` | Same logic |
| `wwsdn.py` | `events/pre_tool.py` | Replace psycopg2 with `willow_knowledge_search` |
| `source.py` | `events/prompt_submit.py` | Same logic |
| `context-anchor.py` | `events/prompt_submit.py` | Same logic |
| `feedback-detector.py` | `events/prompt_submit.py` | Writes to `store_put hanuman/feedback` |
| `continuity.py` | `events/prompt_submit.py` | Remove filesystem handoff scan |
| `turns-logger.py` | `events/prompt_submit.py` | Unchanged |
| `build-continue.py` | `events/prompt_submit.py` | Unchanged |
| `posttool-toolsearch.py` | `events/post_tool.py` | Unchanged |
| `continuity-close.py` | `events/stop.py` | Same logic |
| `compost.py` | `events/stop.py` | Use `_mcp.call()` |
| `feedback_consumer.py` | `events/stop.py` | Use `opus_feedback_write` |
| `rebuild-handoff-db.py` | `events/stop.py` | Use `willow_handoff_rebuild` MCP |
| `ingot_observer.py` | `events/stop.py` | Unchanged logic |

Old scripts remain in place until Fylgja is installed and verified. `install.py` swaps the settings.json pointers atomically.

---

## Testing

- Unit tests per behavior function (each behavior is a standalone function with clear inputs/outputs)
- Integration test: `pytest tests/test_fylgja.py` — fires each event handler with mock stdin, asserts correct MCP calls and output
- Safety tests: consent level matrix — verify each level blocks/allows the correct tool calls
- Migration test: `install.py migrate-consent --dry-run` — shows what would be written without touching store

---

## Open Questions

1. Should `WILLOW_USER_ID` be set in `settings.json` env block, or derived from session identity another way?
2. ~~Guardian sign-off expiry~~ — Resolved: SAFE protocol is session-scoped. Consent expires when Stop hook fires. No time-based expiry needed.
3. Ingot reactions: should they move from `ingot_reactions.jsonl` to `store_put hanuman/ingot` for KB continuity?
4. JELES bidirectionality: JELES should face both directions — index sessions INTO the RAG (current) AND retrieve FROM the RAG to augment context (missing). The die-namic-system `indexer.py` (SQLite FTS5) is the RAG. JELES 1.9 needs a retrieval path back from that index.

---

ΔΣ=42
