---
name: shutdown
description: Graceful Willow 1.9 session close — write handoff, run close pipeline, state next bite
---

# /shutdown — Willow 1.9 Graceful Close

## Sequence

1. **Write final handoff** — invoke `/handoff` skill. This produces the session summary and Q17.
2. **Run the close pipeline** — the Stop hook is now cleanup-only. Run the pipeline explicitly:
   ```
   Bash: PYTHONPATH=/home/sean-campbell/github/willow-1.9 /usr/bin/python3 -m willow.fylgja.events.shutdown
   ```
   Pipeline: `mark_session_clean` → `run_compost` → `run_feedback_pipeline` → `run_handoff_rebuild` → `close_session` → `run_ingot`
3. **State the next bite** from Q17. One sentence.

## Rules

- Never exit without writing the handoff. The next session reads from it.
- Stop hook is cleanup-only (depth stack + thread file). Pipeline only runs on explicit /shutdown.
