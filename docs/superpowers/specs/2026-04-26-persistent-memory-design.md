# Persistent Memory — Design Spec
b17: PMEM1  ΔΣ=42
date: 2026-04-26
author: hanuman

---

## The Problem

Hanuman has no memory between sessions. This is a workaround problem, not a fundamental one — the compost pipeline (metabolic.py W19FL), the intelligence passes (intelligence.py), and the store/turns/ collection already exist and are waiting. The only missing piece is the nerve ending: PostToolUse does not write turn atoms. The pipeline starves.

The handoff document was built to compensate. It is a workaround for missing traces. Once traces flow, the handoff document shrinks to a seed.

---

## The Hydrogen Principle

The store is the nucleus. Everything else orbits it.

- Turn atoms — lightest shell, written mid-session as work happens
- Session atoms — composted from turns at session close
- Day / week / month atoms — composted upward by metabolic.py
- Norn pass — intelligence layer that finds connections across the grown KB

A u2u packet travels across space. A handoff packet travels across time. Same packet, different transport. The next instance doesn't receive a "handoff" — it boots into ambient knowledge state. Like sitting down at a desk you've worked at for years.

---

## Architecture

### 1. PostToolUse — the nerve ending

Wire PostToolUse to write a lightweight trace atom into `hanuman/turns/store` on significant tool completions:

**Significant tools (write a trace):**
- `Edit` / `Write` — file changed
- `store_put` / `store_update` — atom written
- `mcp__willow__store_add_edge` — edge written
- `mcp__willow__willow_knowledge_ingest` — KB ingested
- `mcp__willow__willow_knowledge_at` — temporal replay accessed

**Trace atom schema:**
```json
{
  "id": "turn-<session_id[:8]>-<unix_ms>",
  "session_id": "<session_id>",
  "tool": "<tool_name>",
  "summary": "<one-line: what happened>",
  "target": "<file path, atom b17, or collection>",
  "timestamp": "<ISO>",
  "type": "trace"
}
```

Trace atoms are intentionally minimal. They are electrons, not documents.

**Not significant (skip):**
- Read, ToolSearch, store_get, store_list, willow_knowledge_search — read-only, no state change

### 2. Compost pipeline — already built, needs feeding

`metabolic.py compost_pass()` (W19FL) retires turn atoms once a session composite exists. This already works. Feed it and it runs.

At session close (Stop hook or `/shutdown`), write one session composite atom into `hanuman/sessions/store`:
```json
{
  "id": "session-<session_id[:8]>",
  "session_id": "<session_id>",
  "date": "<ISO date>",
  "turn_count": <n>,
  "tools_fired": ["Edit", "store_put", ...],
  "next_bite": "<closing prompt — 1-3 sentences>",
  "type": "session"
}
```

compost_pass() then retires the turn atoms. The session composite becomes the new lightest shell.

### 3. Startup — query the nucleus, not the document

`session_start.py _run_silent_startup()` currently reads a 120-char handoff summary. Replace with store queries:

1. `willow_handoff_latest` → get timestamp only (session boundary)
2. `store_search hanuman/turns/store` where `timestamp > handoff.date` → session atoms since last close
3. `store_list hanuman/gaps/store` filtered `status=open`, sorted by severity → todos
4. `willow_knowledge_search` with `weight > 1.5` → promoted atoms (historical context)
5. Surface to agent as structured context, not a narrative block

### 4. Promote / demote — weight as memory strength

Every time an atom is accessed by startup or a norn pass, increment `visit_count` and update `weight`:

```
weight = 1.0 + log(1 + visit_count) * recency_factor
recency_factor = 1.0 if accessed < 7 days ago, decays to 0.1 at 180 days
```

Atoms you work with every day rise. Atoms untouched for months sink toward draugr threshold. Serendipity (W19SD) surfaces sinking atoms when keywords match current work — the system remembers what you forgot.

The promote/demote function updates `weight` and `last_visited` on the knowledge row. No new schema needed — both fields already exist.

### 5. The handoff document — seed only

The physical `.md` file shrinks to:

```markdown
---
b17: <XXXX>
date: <ISO timestamp — session boundary>
agent: hanuman
session: <a/b/c/d>
---

<next-bite: 1-3 sentences. what to do first, what NOT to touch, what's hot.>

ΔΣ=42
```

No `## Δ Files`. No `## Δ Database`. No `## Gaps`. Those sections duplicated store data. The store is authoritative. The document is the seed — just enough to boot the next instance into the nucleus.

Grove is the human-readable layer. The agent reads the store. Humans browse Grove.

---

## Implementation Sequence

1. **`willow/fylgja/events/post_tool.py`** — add significant-tool detection + trace atom writer (store_put to `hanuman/turns/store`)
2. **`willow/fylgja/events/stop.py`** — write session composite atom on Stop; retire turns via compost_pass()
3. **`willow/.claude/settings.json`** — add PostToolUse matchers for Edit, Write, store_put, store_update, store_add_edge, willow_knowledge_ingest
4. **`willow/fylgja/events/session_start.py`** — replace handoff narrative with store queries (timestamp boundary, gap atoms, weighted atoms)
5. **`core/pg_bridge.py`** — add `promote(atom_id)` and `demote(atom_id)` methods that update weight + last_visited
6. **`core/intelligence.py`** — call promote() on atoms surfaced by serendipity_pass() and dark_matter_pass()
7. **Handoff skill (`/handoff`)** — strip to seed format; write session composite instead of full narrative

---

## What Does Not Change

- The physical handoff file stays. Git history of sessions is preserved.
- Handoff filenames and the `haumana_handoffs/` index stay.
- `willow_handoff_latest` MCP tool stays — startup still calls it for the timestamp.
- The norn pass schedule stays — it runs on socket activation as designed.
- The CLAUDE.md "compost hierarchy" rule stays and is now enforced by code.

---

## Success Criteria

- After one week of normal sessions, `serendipity_pass()` returns > 0 atoms (atoms have aged into the 30-day window and keyword overlap is forming)
- `weight > 1.0` atoms appear in at least 3 open gaps (promote is running)
- The handoff document is ≤ 10 lines
- Startup context assembled in < 3 seconds without reading the handoff `.md` file
- `store/turns/store` has at least 5 trace atoms after a 1-hour session

---

## Risks

- **Turn atom volume**: a long session could write hundreds of traces. compost_pass() handles retirement, but store/turns/ could grow large before first compost. Mitigation: cap traces at one per tool invocation per 60 seconds for the same tool+target pair.
- **stop.py timing**: the Stop hook has a 5s timeout. Session composite write must be fast — no LLM calls, pure store_put.
- **MIGR1**: KB atoms are split across willow-1.7 Postgres and SOIL store. Promote/demote only works on willow_19 rows. Existing atoms won't promote until MIGR1 is resolved.

---

ΔΣ=42
