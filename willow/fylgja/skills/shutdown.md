---
name: shutdown
description: Graceful Willow 1.9 session close — audit KB, write handoff, run full pipeline
---

# /shutdown — Willow 1.9 Graceful Close

## Sequence

1. **Resolve open process flags** — call `soil_list` with prefix `flags/` and filter for any
   record where `flag_state` is `running`, `open`, or `awaiting authorization` and the `id`
   starts with `process-`. For each one: check whether the process completed this session by
   reading its log file (the flag's `note` field usually contains the log path) or checking
   `pgrep`. If the process finished, close the flag with `soil_put` (`flag_state: complete`,
   resolution note, elapsed time if known) **before** writing the handoff. If it is still
   running, update the flag with current progress so the next session reads accurate state, not
   the state from when the flag was first opened. A handoff with a stale open process flag is a
   lie to the next session.

2. **KB close audit** — for every task completed or closed this session, verify its KB atom
   reflects the resolution. Search with `kb_search` for each task name. If the atom says the
   task is open or unsolved, update it with `kb_ingest` (new atom) marking it resolved and
   citing the commit or output. This step exists because atoms written at task-open never get
   updated on close — that's what causes rediscovery loops in future sessions.

   Also check: did this session discover new patterns, governance gaps, conflicts of interest,
   or durable lessons? Each one requires **all three** of the following — not a subset:
   1. A memory file written to `~/.claude/projects/.../memory/<type>_<slug>.md`
   2. A one-line entry added to `MEMORY.md` with the KB atom ID
   3. A KB atom ingested via `kb_ingest`

   A Grove post is communication, not memory. Scan MEMORY.md entries added this session — any
   entry missing a KB atom ID is incomplete. Fix before handoff. If patterns were extracted but
   edges are missing, add them now with `soil_add_edge`.

3. **Memory audit** — run `/health memory` to check for STALE/DEAD/REDUNDANT/DARK records. Archive or fix before handing off.

4. **Write final handoff** — invoke `/handoff` skill. This produces the session summary and Q17.

5. **Run the close pipeline** — the Stop hook is now cleanup-only. Run the full pipeline explicitly:
   ```
   Bash: PYTHONPATH=/home/sean-campbell/willow-1.9 /home/sean-campbell/willow-1.9/.venv-dev/bin/python3 -m willow.fylgja.events.shutdown
   ```
   **Pipeline stages:**
   - `mark_session_clean` — track successful session close
   - `run_grove_ingest` — pull new Grove channel messages
   - `run_compost` — ingest session activity summary
   - `run_atom_synthesis` — Phase 3: extract atoms missed by hooks
   - `run_edge_linking` — Phase 4: connect atoms into knowledge graph
   - `run_feedback_pipeline` — process any pending feedback
   - `run_handoff_rebuild` — rebuild handoffs DB
   - `close_session` — mark session complete in SAFE
   - `run_ingot` — cat observation from local model

6. **State the next bite** from Q17. One sentence.

## Rules

- Never exit without writing the handoff. The next session reads from it.
- Never skip the KB close audit (step 1). An unclosed atom is a future rediscovery loop.
- Phases 3+4 (atom synthesis + edge linking) only run if `WILLOW_ATOM_EXTRACTION=1`.
- Stop hook is cleanup-only (depth stack + thread file). Pipeline only runs on explicit /shutdown.
- Step 1 (process flag resolution) is not optional. A handoff written over a stale running flag is incorrect state — the next session will surface it as an open problem that is already solved.
