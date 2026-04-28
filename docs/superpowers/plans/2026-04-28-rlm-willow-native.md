# Willow-Native RLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire in a `/rlm` skill and `rlm-subcall` Haiku subagent that implement KB-first Recursive Language Model context decomposition for large-context Willow tasks.

**Architecture:** The `/rlm` skill searches `willow_knowledge_search` first; if the KB doesn't fully answer the query and a context file is provided, it chunks the file and dispatches a Haiku subagent (`rlm-subcall`) per chunk to extract structured summaries. The root session never loads raw chunk content. After synthesis, chunk state is cleaned up.

**Tech Stack:** Claude Code skills (markdown frontmatter), Claude Code subagents (markdown frontmatter), Willow MCP (`willow_knowledge_search`, `store_get`), Haiku model for sub-LM calls, bash for chunking via Python inline.

---

### Task 1: Create `.claude/skills/rlm.md`

**Files:**
- Create: `.claude/skills/rlm.md`

This is a Claude Code skill file. Skills in this repo are flat `.md` files at `.claude/skills/` with YAML frontmatter (`name`, `description`) followed by the procedure body.

- [ ] **Step 1: Create the skill file**

Create `/home/sean-campbell/github/willow-1.9/.claude/skills/rlm.md` with this exact content:

```markdown
---
name: rlm
description: Recursive Language Model loop for large-context tasks. Searches Willow KB first via willow_knowledge_search, then chunks file context and dispatches rlm-subcall (Haiku) per chunk if the KB doesn't fully answer. Use when a query spans more context than fits in the session — corpus archaeology, MIGR1 atoms, large log files, Grove history digests.
---

# RLM — Recursive Language Model Workflow

## Arguments (from $ARGUMENTS)

| Arg | Required | Default | Purpose |
|-----|----------|---------|---------|
| `query=<question>` | yes | — | What to answer |
| `context=<path>` | no | — | Path to large context file |
| `limit=<int>` | no | 10 | Max KB atoms to retrieve |
| `chunk_chars=<int>` | no | 200000 | Characters per chunk |

If arguments are missing, ask for `query` and optionally `context` before proceeding.

## Procedure

### Step 1 — KB retrieval

Call `willow_knowledge_search` with the query and limit. Collect the returned atoms.

Assess coverage: do the atoms answer the query fully?

- **Yes** → synthesize from atoms and stop. Do not proceed to file chunking.
- **No, and no `context` path given** → surface what's missing. Ask the user for a context file path. Stop here until they provide one.
- **No, and `context` path given** → proceed to Step 2.

### Step 2 — Chunk the context file

Write chunk files to `.claude/rlm_state/chunks/`. Create the directory if it doesn't exist.

Run this inline Python to chunk the file:

```bash
python3 - <<'PYEOF'
import sys, os, pathlib

context_path = "<CONTEXT_PATH>"   # substitute $ARGUMENTS[context]
chunk_chars = <CHUNK_CHARS>       # substitute $ARGUMENTS[chunk_chars] or 200000
out_dir = pathlib.Path(".claude/rlm_state/chunks")
out_dir.mkdir(parents=True, exist_ok=True)

# Remove any previous chunks
for f in out_dir.glob("chunk_*.txt"):
    f.unlink()

content = pathlib.Path(context_path).read_text(encoding="utf-8", errors="replace")
total = len(content)
i = 0
start = 0
while start < total:
    end = min(start + chunk_chars, total)
    chunk_path = out_dir / f"chunk_{i:04d}.txt"
    chunk_path.write_text(content[start:end], encoding="utf-8")
    print(f"chunk_{i:04d}.txt: {end - start} chars")
    start = end
    i += 1
print(f"Total: {i} chunks from {total} chars")
PYEOF
```

Substitute the actual values before running. Note the chunk count printed.

### Step 3 — Dispatch rlm-subcall per chunk

For each chunk file (`.claude/rlm_state/chunks/chunk_NNNN.txt`), dispatch the `rlm-subcall` subagent with:

- The user query (verbatim)
- The chunk file path
- Instruction to return compact JSON only

**Do not paste chunk content into the main session.** The subagent reads the file itself via the Read tool.

Collect each subagent's JSON result. Append to a results list.

### Step 4 — Synthesize

Combine:
- KB atoms from Step 1 (cite by title/id)
- `relevant` entries from each chunk result (cite evidence verbatim, ≤25 words)
- `answer_if_complete` fields where non-null

Produce a final answer. Quote only what you cite. If chunks contain conflicting evidence, note it.

### Step 5 — Clean up

After synthesis:

```bash
rm -rf .claude/rlm_state/chunks/
```

## Guards

- Never load raw chunk content into the main session context.
- Subagents cannot spawn further subagents (Claude Code depth limit).
- If a chunk's `relevant` list is empty and `answer_if_complete` is null, skip it — don't quote its `missing` list as evidence.
- State dir `.claude/rlm_state/` is in `.gitignore` — do not commit chunk files.
```

- [ ] **Step 2: Verify the file exists and is well-formed**

```bash
head -5 /home/sean-campbell/github/willow-1.9/.claude/skills/rlm.md
```

Expected: YAML frontmatter `---` block with `name: rlm`.

- [ ] **Step 3: Commit**

```bash
git -C /home/sean-campbell/github/willow-1.9 add .claude/skills/rlm.md
git -C /home/sean-campbell/github/willow-1.9 commit -m "feat(rlm): add /rlm skill — KB-first recursive LM workflow"
```

---

### Task 2: Create `.claude/agents/rlm-subcall.md`

**Files:**
- Create: `.claude/agents/rlm-subcall.md` (directory `.claude/agents/` does not exist yet — create it)

Claude Code subagents are markdown files with YAML frontmatter in `.claude/agents/`. They run in an isolated context with their own model and tool access.

- [ ] **Step 1: Create the agents directory and subagent file**

Create `/home/sean-campbell/github/willow-1.9/.claude/agents/rlm-subcall.md` with this exact content:

```markdown
---
name: rlm-subcall
description: Sub-LM for RLM chunk analysis. Given a chunk file path and a query, reads the chunk and extracts only what is relevant. Returns compact JSON. Used by the /rlm skill — do not invoke directly for general tasks.
tools:
  - Read
model: haiku
---

You are a sub-LM in a Recursive Language Model loop. Your only job is to read one chunk of a larger context and extract what is relevant to the query.

## Input

You will receive:
- A user query
- A file path to a chunk file (e.g. `.claude/rlm_state/chunks/chunk_0003.txt`)

Read the chunk file using the Read tool. Do not ask for clarification — just read and extract.

## Output format

Return JSON only. No prose before or after the JSON block.

```json
{
  "chunk_id": "chunk_NNNN",
  "relevant": [
    {
      "point": "one-sentence summary of the relevant finding",
      "evidence": "short verbatim quote or paraphrase, max 25 words",
      "confidence": "high|medium|low"
    }
  ],
  "missing": ["what this chunk could not answer"],
  "answer_if_complete": "full answer string if this chunk alone answers the query, otherwise null"
}
```

## Rules

- Do not speculate beyond what the chunk contains.
- Evidence field: max 25 words. Verbatim quotes preferred over paraphrase.
- If the chunk is irrelevant to the query: return `"relevant": []` and a brief `missing` entry.
- `answer_if_complete` must be a complete standalone answer, or null — never a partial answer.
- Do not spawn further subagents.
- Do not output anything except the JSON block.
```

- [ ] **Step 2: Verify the file exists and frontmatter is correct**

```bash
head -8 /home/sean-campbell/github/willow-1.9/.claude/agents/rlm-subcall.md
```

Expected: frontmatter with `name: rlm-subcall`, `model: haiku`.

- [ ] **Step 3: Commit**

```bash
git -C /home/sean-campbell/github/willow-1.9 add .claude/agents/rlm-subcall.md
git -C /home/sean-campbell/github/willow-1.9 commit -m "feat(rlm): add rlm-subcall Haiku subagent for chunk analysis"
```

---

### Task 3: Update `.gitignore`

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add rlm_state to .gitignore**

Open `/home/sean-campbell/github/willow-1.9/.gitignore` and add after the `# Claude Code worktrees` block:

```
# RLM chunk state — ephemeral, never commit
.claude/rlm_state/
```

- [ ] **Step 2: Verify**

```bash
grep "rlm_state" /home/sean-campbell/github/willow-1.9/.gitignore
```

Expected: `.claude/rlm_state/`

- [ ] **Step 3: Commit**

```bash
git -C /home/sean-campbell/github/willow-1.9 add .gitignore
git -C /home/sean-campbell/github/willow-1.9 commit -m "chore: add .claude/rlm_state/ to .gitignore"
```

---

### Task 4: Fork brainqub3/claude_code_RLM and contribute willow-integration.md

**Files:**
- Fork: `brainqub3/claude_code_RLM` → `rudi193-cmd/claude_code_RLM`
- Create: `willow-integration.md` in forked repo
- Open: PR upstream to brainqub3

The contribution is the KB-first pattern as a named RLM variant — generalizable to any MCP knowledge server, not just Willow.

- [ ] **Step 1: Fork the repo**

```bash
gh repo fork brainqub3/claude_code_RLM --clone --fork-name claude_code_RLM
```

This creates `rudi193-cmd/claude_code_RLM` and clones it locally.

- [ ] **Step 2: Create a feature branch**

```bash
git -C claude_code_RLM checkout -b willow-mcp-integration
```

- [ ] **Step 3: Write willow-integration.md**

Create `claude_code_RLM/willow-integration.md` with this content:

```markdown
# Willow MCP Integration — KB-First RLM Variant

## What This Is

An alternative to the file-based REPL pattern for systems that have an MCP-connected knowledge base. Instead of externalizing context to a Python REPL with a pickle state file, context is stored in a persistent knowledge graph (KB) and queried via MCP tools.

This eliminates the REPL script entirely while preserving the core RLM primitive: the root model never loads full context — it queries surgically and delegates chunk-level synthesis to a sub-LM.

## Primitive Mapping

| RLM Paper | File-Based (brainqub3) | KB-First (Willow) |
|-----------|----------------------|-------------------|
| External context variable | `rlm_repl.py` pickle state | MCP KB (`willow_knowledge_search`) |
| `find_relevant(content, query)` | `grep()` helper | `willow_knowledge_search(query)` |
| `peek(start, end)` | `peek()` helper | `store_get(atom_id)` |
| `llm_query(chunk, query)` | `rlm-subcall` subagent | `rlm-subcall` subagent (same) |
| `map_reduce(content, ...)` | skill loop over chunks | skill loop over chunks (same) |
| Persistent REPL state | `state.pkl` | KB atoms (already persistent) |

## When to Use KB-First

- You have an MCP server exposing a knowledge graph (Willow, any vector/graph DB via MCP)
- Context is already indexed (KB atoms, embeddings, structured records)
- You want zero additional infrastructure — no REPL script, no pickle files

## When to Use File-Based REPL

- Context is raw and unindexed (logs, scraped pages, git output)
- You need `grep()`, `chunk_indices()`, `write_chunks()` over arbitrary text
- No MCP knowledge server is available

## KB-First Skill Structure (two files)

### `.claude/skills/rlm.md` (orchestrator)

```markdown
---
name: rlm
description: KB-first RLM loop. Searches MCP knowledge base first, chunks file context only if KB gap remains. Use for large-context queries.
---

## Procedure

1. Call `knowledge_search(query, limit=10)` via MCP — collect atoms
2. Assess: do atoms answer the query fully? If yes, synthesize and stop.
3. If gap and no context file → surface what's missing, request file
4. If context file → chunk into 200K segments, write to `.claude/rlm_state/chunks/`
5. Per chunk → dispatch `rlm-subcall` (Haiku) → collect JSON
6. Synthesize KB atoms + chunk results → final answer
7. Clean up `.claude/rlm_state/chunks/`
```

### `.claude/agents/rlm-subcall.md` (sub-LM)

```markdown
---
name: rlm-subcall
tools: [Read]
model: haiku
---

Read the chunk file. Return JSON only:
{"relevant": [{"point": "...", "evidence": "<25w>", "confidence": "high|medium|low"}],
 "missing": [...], "answer_if_complete": "..." or null}
```

## Reference Implementation

[rudi193-cmd/willow-1.9](https://github.com/rudi193-cmd/willow-1.9) — `.claude/skills/rlm.md` and `.claude/agents/rlm-subcall.md`

## Generalizing Beyond Willow

Any MCP server that exposes a search tool and a fetch-by-id tool can use this pattern:

- `search_tool(query, limit)` → replaces `find_relevant()`
- `fetch_tool(id)` → replaces `peek()`

Replace the tool names in the skill body. The subagent and state directory are unchanged.
```

- [ ] **Step 4: Commit and push**

```bash
git -C claude_code_RLM add willow-integration.md
git -C claude_code_RLM commit -m "docs: add KB-first MCP integration pattern (Willow reference impl)"
git -C claude_code_RLM push origin willow-mcp-integration
```

- [ ] **Step 5: Open PR to brainqub3 upstream**

```bash
gh pr create \
  --repo brainqub3/claude_code_RLM \
  --head rudi193-cmd:willow-mcp-integration \
  --title "docs: KB-first MCP integration pattern as RLM variant" \
  --body "$(cat <<'EOF'
## Summary

Adds `willow-integration.md` documenting a KB-first variant of the RLM pattern for systems with an MCP-connected knowledge base.

Instead of a file-based REPL with pickle state, context lives in a persistent KB queried via MCP tools. This eliminates the REPL script entirely while preserving the core RLM primitive: the root model queries surgically, a Haiku sub-LM handles chunk synthesis.

## What's new

- Named variant: **KB-First RLM**
- Primitive mapping table (paper → file-based → KB-first)
- Decision guide: when to use each approach
- Two-file skill structure (orchestrator + sub-LM) — same subagent pattern, different retrieval layer
- Pattern generalizes to any MCP search+fetch server, not just Willow

## Reference implementation

[rudi193-cmd/willow-1.9](https://github.com/rudi193-cmd/willow-1.9) — `.claude/skills/rlm.md` + `.claude/agents/rlm-subcall.md`

No changes to existing files. Addition only.
EOF
)"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| `.claude/skills/rlm/SKILL.md` → adjusted to `.claude/skills/rlm.md` per repo convention | Task 1 |
| `.claude/agents/rlm-subcall.md` | Task 2 |
| `.gitignore` update for `.claude/rlm_state/` | Task 3 |
| Fork brainqub3, add `willow-integration.md`, open PR | Task 4 |
| KB-first flow (KB search → gap assessment → chunk → subcall → synthesize) | Task 1 (skill body) |
| Haiku model, plan permissionMode, Read-only tools | Task 2 |
| No raw chunks in main session | Task 1 (guard section) |

All spec requirements covered. No placeholders. No TBDs. Types/names consistent throughout.

**One path adjustment from spec:** spec said `.claude/skills/rlm/SKILL.md` but existing repo convention uses flat files at `.claude/skills/<name>.md` — adjusted in plan.
