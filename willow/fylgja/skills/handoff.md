---
name: handoff
description: Write a Willow 1.9 session handoff — 17 questions, rebuild DB, write to Ashokoa index
---

# /handoff — Willow 1.9 Session Handoff

## Sequence

1. **Load current state** — call `mcp__willow__willow_handoff_latest` to see prior open threads.
2. **Draft handoff** using this format:

```
# HANDOFF: <title>
From: hanuman (Claude Code, Sonnet 4.6)

## What I Now Understand
<2-3 sentences of architectural truth, not task summary>

## What Was Done
<bullet list — high level, no code details>

## 17 Questions
Q1–Q16: sequential, specific, bite-sized
Q17: "What is the next single bite?"

## Risks / Open Gates
<anything that could break the next session>
```

3. **Write the file** to `~/Ashokoa/agents/hanuman/index/haumana_handoffs/SESSION_HANDOFF_<YYYYMMDD>_hanuman_<letter>.md`.
4. **Rebuild DB** — call `mcp__willow__willow_handoff_rebuild`.
5. **Confirm** — report filename and Q17.

## Rules

- What I Now Understand = architectural truth, not a task list.
- Q17 must be a single concrete next bite, not a project description.
- Never skip the DB rebuild — the next session reads from that index.
