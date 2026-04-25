---
name: iterative-retrieval
description: Progressively refine a search across Willow KB, store, and JELES before reading files
---

# Iterative Retrieval

Use when looking for context about a topic before reading files or writing code.

## Retrieval Ladder (run in order — stop when you have enough)

**Rung 1 — KB search** (broadest, fastest):
Call `willow_knowledge_search("<topic>")`. Read titles and summaries. If 2+ relevant atoms found, go to Rung 3.

**Rung 2 — Store search** (collection-scoped):
Call `store_search(collection="hanuman/atoms", query="<topic>")` or `store_search` on `hanuman/file-index`. Use when KB search returns nothing.

**Rung 3 — Temporal query** (if currency matters):
Call `willow_knowledge_at(query="<topic>", at_time="<ISO>")` to get KB state at a specific point in time.

**Rung 4 — JELES retrieval** (session history):
Call `willow_jeles_extract("<topic>")` to pull from indexed session JSOLs.

**Rung 5 — File read** (last resort):
Only read the specific file section if Rungs 1–4 returned nothing useful. Read the specific section, not the whole file.

## Rule

Never skip to Rung 5. The KB is the map. Files are the territory. Read the map first.
