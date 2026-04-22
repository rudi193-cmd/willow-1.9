---
name: shutdown
description: Graceful Willow 1.9 session close — write handoff, confirm stop pipeline, state next bite
---

# /shutdown — Willow 1.9 Graceful Close

## Sequence

1. **Write final handoff** — invoke `/handoff` skill. This produces the session summary and Q17.
2. **Confirm stop pipeline is wired** — check that `~/.claude/settings.json` Stop hook is present. If missing, alert Sean before exiting.
3. **Report what will happen at stop**:
   - Session turns composted to KB (`willow_knowledge_ingest`)
   - Pending feedback records processed (`opus_feedback_write`)
   - Handoff DB rebuilt (`willow_handoff_rebuild`)
   - Ingot reaction written
4. **State the next bite** from Q17. One sentence.

## Rules

- Never exit without writing the handoff. The next session reads from it.
- If the Stop hook is missing, the compost + feedback pipeline will not run. Flag it.
