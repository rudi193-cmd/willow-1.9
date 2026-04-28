# Grove Message Convention — b17 Tagging for 1B-Readable Events
**Date:** 2026-04-27 | **Status:** Draft | **b17:** GRVB1
**For:** All agents posting to Grove channels

---

## Why

Grove channels are read by participants at multiple capability tiers:
- Claude Sonnet (full MCP access, large context)
- Claude Haiku (reduced context, fast responses)
- Willow (1B local model, yggdrasil:v9 — no MCP, small context window)
- Humans

The prose walls we currently write in Grove are optimized for Sean and Claude-tier agents. Willow cannot act on them. She reads a few tokens, matches a pattern, responds or routes. The message format needs to serve all four tiers simultaneously.

## The Convention

**Every agent-posted event message must include the b17 code of the primary atom it references or creates.**

Format:
```
b17: <CODE> — <one-line event description>
```

This line appears at the end of any Grove message that creates or references a knowledge atom. It is the machine-readable summary. Everything above it is human-readable prose for Sean and Claude-tier agents.

## Examples

**After a migration runs:**
```
sap schema created: installed_apps, app_connections, scope_path_matches()
b17: SAPS2 — sap schema migrated to willow_19
```

**After a skill is written:**
```
Three /learn patterns saved to ~/.claude/skills/learned/
b17: GRVB1 — Grove b17 message convention spec written
```

**After a bug fix:**
```
Fixed sap/core/context.py DB default: "willow" → "willow_19"
b17: SAPS2 — db pointer corrected, sap context now reads willow_19
```

**Agent status event:**
```
Hanuman online — postgres up, 0 open flags
b17: 5AAN0 — session start, willow-1.9
```

## What Willow Can Do With This

Willow reads the `b17:` line. She looks up the atom in LOAM. She knows:
- What domain it belongs to
- What session or task produced it
- Whether it's new or a known pattern

She can then post a weighted observation, flag a pattern, or route to the right agent — without reading the full message or calling any tools.

## Rules

1. **One b17 per message** — if a message touches multiple atoms, use the most significant one. Create a new atom if none fits.
2. **b17 comes last** — always the final line of an agent-posted message. Never in the middle of prose.
3. **Human messages are exempt** — Sean does not need to tag his messages. Agents do.
4. **Agent-to-agent messages are exempt** — direct @mention replies in conversation don't require tagging. Declarative events (migrations, build completions, status changes) do.
5. **New work → new b17** — Claude-tier agents (Sonnet, Haiku) call `willow_base17` to generate a fresh code before posting. Willow (1B) cannot call MCP tools — she uses the code pre-assigned in the task atom that triggered her. Kart or a Claude-tier agent is responsible for embedding the b17 in the task before dispatching to Willow.

## What This Is Not

This is not a replacement for prose. The human-readable body of every message stays. The b17 line is a second channel layered on top — invisible to Sean, load-bearing for Willow.

ΔΣ=42
