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

### Consent Levels

```python
class ConsentLevel(IntEnum):
    UNIDENTIFIED   = 0  # unknown session user
    RESTRICTED     = 1  # known minor, no active guardian approval
    MINOR_GUARDED  = 2  # known minor, guardian sign-off active
    ADULT          = 3  # verified adult (Sean)
```

### User Profile Store Schema

Collection: `willow/users/{user_id}`

```json
{
  "user_id": "string",
  "name": "string",
  "dob": "YYYY-MM-DD",
  "age_band": "adult | minor",
  "guardian_id": "string | null",
  "created": "ISO timestamp"
}
```

### Guardian Approval Store Schema

Collection: `willow/guardian_approvals`

```json
{
  "user_id": "string",
  "guardian_id": "string",
  "granted_at": "ISO timestamp",
  "expires_at": "ISO timestamp",
  "scope": "session | day | week"
}
```

### `safety/consent.py`

On session start (first turn):
1. Reads `WILLOW_USER_ID` env var (or defaults to agent owner).
2. Calls `store_get willow/users/{user_id}` via `_mcp.call()`.
3. If minor: checks `willow/guardian_approvals` for non-expired record.
4. Derives consent level. Caches to `_state.py`.

### `safety/rules.py`

Hard-coded content rules per consent level. Not KB-driven. Rules define which tool calls and content categories are blocked at each level. `ADULT` has no hard stops.

### `safety/hard_stop.py`

Returns `{"decision": "block", "reason": "<user-facing message>"}`. The reason is always clear and non-technical — a child sees a plain explanation, not a system error.

### Safety Event Logging

Any hard stop fires a `store_put willow/safety_log` record: `user_id`, `timestamp`, `tool_name`, `consent_level`, `rule_violated`.

### KB Consolidation (Migration Step)

Before safety enforcement is live: search `willow_knowledge_search` for existing consent/age/guardian KB pieces, extract canonical data, write to `willow/users/` store collection, archive originals. This is a one-time migration script: `fylgja/install.py migrate-consent`.

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
2. Guardian sign-off expiry: does a "session" scope expire when the Stop hook fires, or on a time basis?
3. Ingot reactions: should they move from `ingot_reactions.jsonl` to `store_put hanuman/ingot` for KB continuity?

---

ΔΣ=42
