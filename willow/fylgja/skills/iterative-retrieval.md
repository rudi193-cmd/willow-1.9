---
name: iterative-retrieval
description: Progressively refine a search across Willow KB, store, and JELES before reading files
---

# Iterative Retrieval

Use when looking for context about a topic before reading files or writing code.

## Retrieval Ladder (run in order — stop when you have enough)

**Rung 1 — KB search** (broadest, fastest):
```
ToolSearch query: "select:mcp__willow__willow_knowledge_search"
```
Call `mcp__willow__willow_knowledge_search` with your topic. Read titles and summaries. If 2+ relevant atoms found, go to Rung 3.

**Rung 2 — Store search** (collection-scoped):
```
ToolSearch query: "select:mcp__willow__store_search"
```
Call `mcp__willow__store_search` on `hanuman/atoms` or `hanuman/file-index`. Use when KB search returns nothing.

**Rung 3 — Temporal query** (if currency matters):
```
ToolSearch query: "select:mcp__willow__willow_knowledge_at"
```
Call `mcp__willow__willow_knowledge_at` with `at_time` to get KB state at a specific point in time.

**Rung 4 — JELES retrieval** (session history):
```
ToolSearch query: "select:mcp__willow__willow_jeles_extract"
```
Call `mcp__willow__willow_jeles_extract` to pull from indexed session JSOLs.

**Rung 5 — File read** (last resort):
Only use Read tool if Rungs 1–4 returned nothing useful. Read the specific section, not the whole file.

## Rule

Never skip to Rung 5. The KB is the map. Files are the territory. Read the map first.
