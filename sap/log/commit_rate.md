# Commit Rate Report

**Generated:** 2026-04-30T12:00:00Z
**Windows:** last 2 h (since 2026-04-30T10:00:00Z) · last 24 h (since 2026-04-29T12:00:00Z)

---

## Access Constraints

> The GitHub MCP server is scoped exclusively to `rudi193-cmd/willow-1.9`.
> No `gh` CLI is available. Only `willow-1.9` commit data could be retrieved.
> All other repos under `rudi193-cmd` are listed as INACCESSIBLE.

---

## Repositories — rudi193-cmd

| Repo | Commits (2 h) | Commits (24 h) | Classification |
|------|:---:|:---:|---|
| willow-1.9 | 0 | 31 | **settling** |
| willow-1.5 | — | — | INACCESSIBLE |
| *(other repos)* | — | — | INACCESSIBLE — `gh repo list` unavailable |

---

## Detail: willow-1.9

- **Classification:** settling (commits in 24 h, none in last 2 h)
- **2-h window commits:** 0 (since 2026-04-30T10:00:00Z)
- **24-h window commits:** 31 (since 2026-04-29T12:00:00Z)
- **Latest commit SHA:** `5580a969` (2026-04-29T23:31:52Z)

### Change Summary (31 commits, newest first)

| SHA | Date (author) | Message |
|-----|---------------|---------|
| `5580a969` | 2026-04-29T23:31 | fix(ci): use pgvector/pgvector:pg15 image — stock postgres:15 lacks vector extension |
| `124aeb52` | 2026-04-29T23:23 | fix(test): loosen pg_sleep timing threshold 2s → 4s |
| `073e46a2` | 2026-04-29T21:46 | chore: remove deleted rlm skill file |
| `245afdce` | 2026-04-29T21:43 | chore: add groq agent script + sean notes |
| `b94b09f5` | 2026-04-29T09:10 | feat(corrections): grove correction extractor — triplet signal DPO pair extraction |
| `d02e2e56` | 2026-04-29T02:18 | feat: search mode flag + rolling backfill rate |
| `1fa4175a` | 2026-04-29T00:58 | docs(sap): strengthen key tool descriptions for cold-connect orientation |
| `9c3a04e5` | 2026-04-29T00:39 | fix(docs): move MCP quick-start to sap/README.md, revert root README |
| `f4ad796a` | 2026-04-29T00:38 | docs(readme): add MCP connection quick-start section |
| `d32f2507` | 2026-04-29T00:37 | feat(sap): MCP server onboarding instructions |
| `4cf7b560` | 2026-04-28T23:33 | feat(backfill): write progress to SOIL hanuman/tasks after each batch |
| `0b0095ea` | 2026-04-28T23:23 | fix(embedder): increase TIMEOUT_S from 5s to 60s — long atoms exceed 5s limit |
| `2715e795` | 2026-04-28T22:52 | feat(sem01): willow_embed_backfill Kart script |
| `0b04614c` | 2026-04-28T22:50 | feat(sem01): semantic flag on 3 MCP tools + startup backfill auto-queue |
| `ec134ccd` | 2026-04-28T22:43 | feat(sem01): SOIL embedding on write/update + search_semantic via sqlite-vec |
| `10b211e4` | 2026-04-28T22:36 | feat(sem01): hybrid RRF semantic search for knowledge/opus_atoms/jeles_atoms |
| `feda5e62` | 2026-04-28T22:31 | feat(sem01): embed on write for knowledge/opus_atoms/jeles_atoms |
| `6e86041a` | 2026-04-28T22:29 | feat(sem01): pgvector migrations + HNSW indexes on knowledge/opus_atoms/jeles_atoms |
| `81d50fa1` | 2026-04-28T22:00 | feat(sem): add core/embedder.py — embed() with Ollama nomic-embed-text |
| `c0fb6c6d` | 2026-04-28T21:54 | feat(sem): add SEM01 implementation plan — 8 tasks, embedder through backfill script |
| `eeb280de` | 2026-04-28T21:37 | feat(sem): add days_ago filter to search_jeles_semantic |
| `25007e8f` | 2026-04-28T21:20 | feat(sem): address Loki review — SOIL backfill traversal, store_update embedding refresh |
| `4b1ecd4e` | 2026-04-28T21:08 | feat(sem): expand SEM01 spec — hybrid RRF, opus/jeles embeddings, auto-backfill |
| `d14045cd` | 2026-04-28T21:03 | feat(sem): add semantic search design spec (SEM01) |
| `21c9edda` | 2026-04-28T20:36 | fix(rlm): convert to directory-format skill (.claude/skills/rlm/SKILL.md) |
| `5fb23f2a` | 2026-04-28T20:29 | feat(rlm): add rlm-subcall Haiku subagent + gitignore for rlm_state |
| `54a1d9d4` | 2026-04-28T20:28 | fix(rlm): absolute chunk path, clarify chunk_chars placeholder |
| `e7e33b1f` | 2026-04-28T20:27 | feat(rlm): add /rlm skill — KB-first recursive LM workflow |
| `2e072230` | 2026-04-28T20:22 | docs(plan): RLM Willow-native implementation plan |
| `eb0bf4fd` | 2026-04-28T19:36 | docs(spec): Willow-native RLM design — KB-first recursive LM pattern |
| `df26da6f` | 2026-04-29T19:06 | chore(watch): pr + commit rate (previous watcher run) |

**Theme summary:** Batch push of SEM01 semantic search (pgvector + sqlite-vec, hybrid RRF, backfill Kart script, embedder), /rlm skill, MCP onboarding docs, grove correction extractor, and CI fixes for pgvector image and timing thresholds.

---

## Settling Repos — Detail

### willow-1.9 — settling

Active SEM01 semantic search sprint landed in a large force-push (31 commits,
author dates span 2026-04-28T19:36 → 2026-04-29T23:31, all squashed/rebased
with committer timestamp 2026-04-29T21:46:10Z). Final two commits at 23:23 and
23:31 are hot CI fixes for pgvector image and test timing. Repo has been quiet
since ~23:32 UTC.

---

## Action Required

To enable full multi-repo monitoring:

1. Set `GITHUB_TOKEN` / `GH_TOKEN` with `repo:read` scope, **or**
2. Expand MCP allow-list to all monitored repos, **or**
3. Install and authenticate `gh` CLI (`gh auth login`).
