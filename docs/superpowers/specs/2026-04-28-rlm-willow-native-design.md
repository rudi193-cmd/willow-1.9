# Willow-Native RLM — Design Spec
**Date:** 2026-04-28 | **Status:** Approved | **b17:** RLM01

## What It Is

A project-scoped `/rlm` skill and `rlm-subcall` subagent that implement the Recursive Language Model pattern (arXiv:2512.24601) using Willow's KB as the primary external memory store. KB-first retrieval replaces file-based REPL state. Haiku handles chunk-level synthesis. The root session stays light.

This is Approach C: no persistent REPL script, no pickle state. Willow's existing infrastructure (`willow_knowledge_search`, `store_get`) maps directly onto the paper's primitives.

## Motivation

Long-context sessions in Willow accumulate context through Grove history, test output, corpus reads, and KB searches. Context rot degrades decision quality without warning. The RLM paper proves that externalizing context and querying it surgically outperforms both direct full-context calls and RAG retrieval approaches. Willow already externalizes context — it just hasn't had a skill to orchestrate recursive sub-queries over it.

Immediate applications:
- MIGR1: 68K atoms from willow-1.7 not yet migrated — chunk the corpus, Haiku summarizes each segment
- Grove history digests: surgical search over channel history without loading 200+ messages
- Any session at risk of context burn

## Architecture

```
/rlm query="..." [context=<path>] [limit=N] [chunk_chars=N]
     │
     ▼
1. KB retrieval — willow_knowledge_search(query, limit=10)
     │
     ├─ atoms answer fully → synthesize → done
     │
     └─ gap remains
           │
           ▼
     2a. No context path → report gap, request file
     2b. Context path given → chunk file into .claude/rlm_state/chunks/
           │
           ▼
     3. For each chunk → rlm-subcall (Haiku) → structured JSON
           │
           ▼
     4. Synthesize: KB atoms + chunk results → final answer
        Quote only cited evidence. Never paste raw chunks.
```

## Components

### `.claude/skills/rlm/SKILL.md`

Frontmatter tools: `Read`, `Write`, `Bash`

MCP calls (`willow_knowledge_search`, `store_get`) are invoked from within the skill body — MCP tool names are not valid in frontmatter `allowed-tools`.

Arguments:
| Arg | Required | Default | Purpose |
|-----|----------|---------|---------|
| `query` | yes | — | What to answer |
| `context` | no | — | Path to large context file or directory |
| `limit` | no | 10 | KB atoms to retrieve |
| `chunk_chars` | no | 200000 | Characters per chunk |

Procedure:
1. `willow_knowledge_search(query, limit)` — retrieve KB atoms
2. Assess coverage: do atoms answer the query? If yes, synthesize and stop.
3. If gap and no `context` → surface what's missing, ask for a path
4. If `context` given → read file, split into `chunk_chars` segments, write each to `.claude/rlm_state/chunks/chunk_NNNN.txt`
5. Per chunk → dispatch `rlm-subcall` with query + chunk path
6. Collect JSON results, synthesize with KB atoms
7. Clean up `.claude/rlm_state/` on success

Guard: main session never loads raw chunk content. All chunk reading happens inside `rlm-subcall`.

### `.claude/agents/rlm-subcall.md`

```
model: haiku
permissionMode: plan
tools: Read
```

Receives: query + chunk file path. Reads chunk via Read tool. Returns compact JSON only:

```json
{
  "relevant": [
    {"point": "...", "evidence": "<25 words>", "confidence": "high|medium|low"}
  ],
  "missing": ["what this chunk could not answer"],
  "answer_if_complete": "full answer or null"
}
```

Rules:
- No speculation beyond chunk content
- Evidence field max 25 words
- If chunk is irrelevant: empty `relevant`, brief `missing`
- No spawning further subagents (Claude Code depth limit)

## State Directory

`.claude/rlm_state/chunks/` — ephemeral chunk files, created per invocation, cleaned up after synthesis. Added to `.gitignore`.

## Primitive Mapping (Paper → Willow)

| RLM Paper | Willow Native |
|-----------|---------------|
| External REPL context variable | `willow_knowledge_search` + `store_get` |
| `find_relevant(content, query)` | `willow_knowledge_search(query)` |
| `peek(start, end)` | `store_get(atom_id)` |
| `llm_query(chunk, query)` | `rlm-subcall` subagent (Haiku) |
| `map_reduce(content, ...)` | skill loop over chunk files |
| Persistent REPL state | KB atoms (already persistent) |

## Contribution Upstream

Fork `brainqub3/claude_code_RLM` → `rudi193-cmd/claude_code_RLM`. Add:
- `willow-integration.md` — documents KB-first pattern as a named RLM variant
- PR to brainqub3 upstream with the pattern documented

The contribution is the pattern itself: using an MCP-connected KB as the RLM external memory store, eliminating the need for a REPL script entirely. This is generalizable to any MCP knowledge server, not just Willow.

## Files Created

```
willow-1.9/
├── .claude/
│   ├── skills/rlm/
│   │   └── SKILL.md
│   └── agents/
│       └── rlm-subcall.md
├── .gitignore              (add .claude/rlm_state/)
└── docs/superpowers/specs/
    └── 2026-04-28-rlm-willow-native-design.md  (this file)
```

## Out of Scope

- Persistent REPL state (not needed — KB is already persistent)
- `willow_search` helper in a Python script (superseded by MCP tool)
- Auto-activation based on query complexity (future work)
- Budget tracking / reasoning traces (future work)

ΔΣ=42
