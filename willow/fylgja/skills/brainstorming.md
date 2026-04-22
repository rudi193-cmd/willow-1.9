---
name: brainstorming
description: Structured brainstorm before any plan or implementation — Willow 1.9 fork
---

# Brainstorming

Use BEFORE entering plan mode or starting any implementation.

## Pre-load

```
ToolSearch query: "select:mcp__willow__willow_knowledge_search,mcp__willow__store_search"
```

## Steps

1. **Search existing KB** — call `mcp__willow__willow_knowledge_search` with the feature/problem as the query. Read relevant atoms before forming opinions.
2. **Search prior session context** — call `mcp__willow__store_search` on `hanuman/atoms` with relevant keywords. Check if this problem was approached before.
3. **State the problem** — one sentence. What are we actually solving?
4. **Generate 3 approaches** — for each: name it, state the core tradeoff in one sentence.
5. **Recommend one** — which and why in 2 sentences.
6. **Flag Fylgja constraints** — does this touch:
   - MCP tools → use `_mcp.call()` subprocess client, not direct import
   - Session state → use `_state.py` functions, not direct file writes
   - Hook events → each behavior needs its own `try/except`
   - `settings.json` → use `install.py`, not manual edits
7. **Stop** — do not implement until Sean confirms the approach.

## Rules

- KB search first. Never brainstorm in a vacuum when prior context exists.
- Three approaches minimum. Two is lazy, four is stalling.
- Fylgja constraints are hard gates, not suggestions.
