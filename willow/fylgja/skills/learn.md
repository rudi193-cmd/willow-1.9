---
name: learn
description: Extract a reusable pattern from this session and ingest it into Willow KB
---

# /learn — Extract and Ingest

Use when something non-obvious was discovered: a workaround, a subtle invariant, a constraint not visible in the code.

## What NOT to learn

- Code patterns derivable by reading the repo
- Git history (use `git log`)
- Task state or in-progress work from this session
- Anything already in CLAUDE.md

## Steps

1. **Name the pattern** — one short title. Examples:
   - "Gleipnir rate window resets per app_id independently"
   - "knowledge_put ON CONFLICT does not preserve invalid_at"

2. **Write the atom content to a file** — F5 canon: content goes in a file, the KB stores the path.
   ```
   Write to: ~/agents/hanuman/learned/<slug>.md
   Content: full explanation, constraint, or workaround
   ```

3. **Ingest the file path** — call `willow_knowledge_ingest`:
   ```json
   {
     "app_id": "hanuman",
     "title": "<pattern name>",
     "summary": "/home/sean-campbell/agents/hanuman/learned/<slug>.md",
     "source_type": "learned",
     "category": "pattern",
     "domain": "hanuman"
   }
   ```

4. **Confirm** — report the atom title and the file path stored.

## Rule

The KB stores the path. Never pass prose as `summary` or `content`. The file IS the content.
