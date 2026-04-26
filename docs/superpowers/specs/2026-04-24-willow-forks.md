# Willow Forks — Universal Unit of Work
b17: FORK1  ΔΣ=42
Date: 2026-04-24
Status: approved — decisions resolved 2026-04-24
Author: Sean Campbell (bath, phone) + Hanuman

---

## The Insight

Git branches work not because they're good for code — they work because they give humans
a unit they can reason about: *what did this do, and can I undo it?*

The same question applies to everything in Willow. A Grove conversation changes things.
A Kart task changes things. A Claude Code session changes things. Right now none of those
changes are grouped, reversible, or legible as a unit.

A **fork** is the primitive that fixes this — for all of them simultaneously.

---

## What a Fork Is

A fork is a named, bounded unit of work that:

1. Any component can **participate in** by tagging its changes with the fork's ID
2. Has exactly one outcome: **merged** (changes promoted) or **deleted** (changes archived)
3. Is **human-readable** — its full history is inspectable at any time
4. Is **recoverable** — nothing is ever truly deleted, only archived

A fork is NOT:
- A git branch (though a git branch may be created alongside one)
- A transaction (no atomicity guarantees — this is eventual consistency)
- A session (sessions are one participant in a fork, not the fork itself)

---

## Fork Schema

Stored in SOIL at `willow/forks/{fork_id}` and mirrored to Postgres `forks` table.

```json
{
  "id": "FORK-{b17}",
  "title": "MCP hardening — timeouts + circuit breaker",
  "created_at": "2026-04-24T07:00:00Z",
  "created_by": "hanuman",
  "topic": "infrastructure",
  "status": "open",
  "participants": ["hanuman", "kart", "grove"],
  "changes": [
    {
      "component": "git",
      "type": "branch",
      "ref": "session/2026-04-24-mcp-hardening",
      "logged_at": "2026-04-24T07:01:00Z"
    },
    {
      "component": "kb",
      "type": "atom",
      "id": "39514B94",
      "title": "Night stack executed",
      "logged_at": "2026-04-24T07:15:00Z"
    },
    {
      "component": "kart",
      "type": "task",
      "task_id": "abc123",
      "description": "run migration script",
      "logged_at": "2026-04-24T08:00:00Z"
    },
    {
      "component": "grove",
      "type": "thread",
      "channel": "infrastructure",
      "message_range": ["msg_001", "msg_047"],
      "logged_at": "2026-04-24T08:30:00Z"
    }
  ],
  "merged_at": null,
  "deleted_at": null,
  "outcome_note": null
}
```

---

## Lifecycle

```
         fork()
            │
            ▼
          OPEN ──────────────────────────────────────────────┐
            │                                                │
            │  (work happens — any component logs changes)   │
            │                                                │
         merge()                                          delete()
            │                                                │
            ▼                                                ▼
         MERGED                                          DELETED
   (changes promoted)                          (changes archived, not lost)
```

### open
Created by any agent or by Sean in Grove/Dashboard. All participating components
tag their changes with `fork_id`.

### merged
Broadcast to all participants: "promote your changes."
- **KB atoms**: `project` tag upgraded, `fork_id` cleared, weight normalized
- **Kart tasks**: moved to permanent history
- **Git branch**: merged to main (or squash-merged with fork title as commit message)
- **Grove thread**: summary atom written to KB, thread archived with `status=merged`
- **SOIL records**: `fork_id` field cleared, records become permanent

### deleted
Broadcast to all participants: "archive your changes."
- **KB atoms**: `domain` set to `archived`, `fork_id` preserved for audit
- **Kart tasks**: cancelled if pending, marked `fork_deleted` if complete
- **Git branch**: deleted
- **Grove thread**: archived with `status=deleted`
- **SOIL records**: `domain` set to `archived`

Nothing is ever hard-deleted. FRANK's ledger records every fork outcome.

---

## Component Participation

### Grove
- Creating a new conversation thread optionally creates or joins a fork
- Thread is tagged with `fork_id` in its metadata
- On merge: thread summary → KB atom. Thread archived.
- On delete: thread archived. No KB write.

### Kart
- Tasks submitted with optional `fork_id` parameter
- Fork context included in task execution environment
- On fork delete: pending tasks cancelled, running tasks flagged

### Claude Code (Hanuman/Heimdallr)
- Session startup: joins or creates a fork
- Fork ID stored in session anchor (`~/.willow/session_anchor.json`)
- All KB writes during session tagged with `fork_id`
- Handoff includes fork ID and status
- Session end: fork stays open (continues next session) or is closed

### Knowledge Base (willow_19)
- `knowledge` table gets `fork_id TEXT` column (nullable — null = permanent)
- `willow_knowledge_ingest` accepts optional `fork_id`
- `willow_knowledge_search` by default excludes unmerged foreign forks
- On merge: `fork_id` set to null (atom becomes permanent)
- On delete: `domain` set to `archived`

### SOIL Store
- Records tagged with `fork_id` field
- `store_put` / `store_update` accept optional `fork_id`
- Fork-scoped queries possible: `store_list(collection, fork_id=X)`

### Git
- Fork optionally creates a branch: `session/{date}-{topic}`
- Branch name stored in fork's `changes` array
- On merge: `git merge --squash` + delete branch
- On delete: `git branch -D`

---

## Operations (MCP Tools)

```
willow_fork_create(title, topic, created_by, fork_id=None)
  → {fork_id, status: "open"}

willow_fork_join(fork_id, component)
  → {fork_id, participants}

willow_fork_log(fork_id, component, type, ref, description)
  → {logged}

willow_fork_merge(fork_id, outcome_note=None)
  → {merged, promoted_count}

willow_fork_delete(fork_id, reason)
  → {deleted, archived_count}

willow_fork_status(fork_id)
  → full fork record

willow_fork_list(status="open")
  → [{fork_id, title, created_at, participant_count, change_count}]
```

---

## Grove UI

In the Grove dashboard, forks appear as a first-class object alongside channels.
Each fork shows:
- Title + topic
- Who created it, when
- Which components are participating
- Change count (atoms written, tasks run, git commits)
- Status badge: OPEN / MERGED / DELETED
- Merge / Delete buttons (Sean-only, or per-trust-level)

Conversations in Grove can be started as "fork conversations" — the thread is
automatically scoped to the fork.

---

## Nested Forks

A fork can have a parent fork. Example:
- Fork: `FORK-MIGR1` (full legacy DB migration — long-running)
  - Fork: `FORK-MIGR1-SOIL` (SOIL store portion — one session)
  - Fork: `FORK-MIGR1-PG` (Postgres portion — another session)

Child fork merge → changes promoted to parent (not to main).
Parent fork merge → all child changes promoted to main.
Parent fork delete → all child forks deleted.

This gives you **hierarchical reversibility**: you can delete a sub-experiment
without affecting the parent effort.

---

## Kart Stability Connection

Kart hanging is partly a symptom of tasks having no fork scope. A task with
no fork has no natural cancellation signal. With fork scoping:
- Kart checks fork status before executing
- If fork is deleted, task is cancelled before execution
- Long-running tasks are always associated with a fork that can be cleaned up

---

## Decisions (resolved 2026-04-24)

1. **Auto-fork on session start?** → **Yes — automatic.**
   Every Claude Code session auto-creates a fork on boot. The fork ID is written
   to `~/.willow/session_anchor.json`. No opt-in required; session startup is
   already the natural hook.

2. **Fork expiry?** → **No automatic expiry.**
   System philosophy is "archive, don't delete." Forks stay open indefinitely
   until Sean explicitly merges or deletes them. No TTL, no background reaper.

3. **Trust level for merge/delete?** → **Sean-only for merge/delete.**
   Hanuman (and any agent) can create forks and join them. Only Sean can merge
   or delete a fork — enforced in the dashboard and MCP tools via trust level check.

4. **Grove channel vs fork?** → **Different primitives.**
   Channels are permanent, long-lived named spaces. Fork threads are ephemeral —
   they are archived on fork merge/delete. No conflation.

5. **Migration of existing work?** → **Yes — migrate.**
   All 69,871 existing KB atoms will be assigned to a bootstrap fork
   `FORK-ORIGIN` (b17: ORIGIN, status: merged) at migration time. This makes
   the entire history legible as a unit and preserves the chain. The migration
   script sets `fork_id = 'FORK-ORIGIN'` on all current atoms, then immediately
   marks `FORK-ORIGIN` as merged — so existing atoms are treated as permanent.

---

## Implementation Order (proposed)

1. **Postgres schema** — `forks` table + `fork_id` column on `knowledge`
2. **SOIL tagging** — `fork_id` field support in `store_put`/`store_update`
3. **MCP tools** — `willow_fork_*` toolset in sap_mcp.py
4. **Session anchor** — startup writes `fork_id` to anchor, all tools use it
5. **Kart integration** — task submission includes `fork_id`
6. **Grove integration** — thread metadata includes `fork_id`
7. **Dashboard** — fork list + status in Grove/Dashboard UI

Each step is independently useful. Step 1+2+3 alone gives you fork tracking.
Steps 4-7 add automation and UI.

---

*"The branches we took that didn't work are just as important as the ones that did.
The difference is knowing which is which."*
