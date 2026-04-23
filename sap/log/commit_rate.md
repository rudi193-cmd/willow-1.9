# Commit Rate — 2026-04-23T16:10:00Z

## willow-1.9 — settling
- Last push: 2026-04-23T07:59:10Z
- Commits last 2h / 24h: 0 / 30+
- Recent changes:
  - feat(startup): silent boot sequence wires in before first prompt
  - chore(sap): commit accumulated gap log entries through 2026-04-23
  - fix(tracker): always create/update dashboard issue, not only on merge
  - feat(community): fork watcher, upstream PR tracker, contributors system
  - fix(tests): add no_chain flag to sleipnir to prevent os.execv in test context
  - refactor(boot): rename pipeline files to tree metaphor; fix chain and gaps
  - fix(ci): create willow_19_test DB and run init_schema before test suite
  - fix(pre_tool): narrow psql bash block to command-start only
  - fix(route): hook uses rules-only path — no LLM fallback in prompt hook context
  - fix(plan5): code audit — 6 bugs fixed
  - feat(plan5): Tasks 10-12 — willow_dispatch, dispatch_result, gerald lore
  - feat(plan5): Task 9 — willow_route oracle (Plan 4 complete)
  - feat(plan5): Tasks 6-8 — Grove channels, dispatch subscription, inbox injection
  - feat(plan5): Tasks 1-3 — constants, DDL, grove ingest on shutdown
  - feat(nest): Layer 0 pipeline — classify, route, scrub, promote, archive
  - perf(fylgja): raise anchor interval 10→25 to reduce per-turn token injection
  - feat(fylgja): Plan 3 complete — Safety subsystem (platform, deployment, session)
  - feat(fylgja/safety): wire safety gate into pre_tool.py + HS-003 gate
  - feat(fylgja/safety): session.py — SAFE protocol, stream auth, consent record
  - feat(fylgja/safety): deployment.py — config loader, user role, PSR, training gate
  - feat(fylgja/safety): platform.py — 9 hard stops, 5 active
  - feat(fylgja): Plan 2 complete — skills plugin wired, fylgja@local registered

## willow-mcp — settling
- Last push: 2026-04-23T03:18:30Z
- Commits last 2h / 24h: 0 / 1
- Recent changes:
  - docs: improve README for public discoverability — badges, cleaner description

## willow-seed — settling
- Last push: 2026-04-23T02:25:51Z
- Commits last 2h / 24h: 0 / 1
- Recent changes:
  - refactor(seed): trim to bootstrap only — prereqs + clone + exec root.py

## willow-dashboard — settling
- Last push: 2026-04-23T02:25:50Z
- Commits last 2h / 24h: 0 / 1
- Recent changes:
  - docs(dashboard): orchestration terminal design spec — 6 regions, routing feed, reactor-door placard

## willow-nest — settling
- Last push: 2026-04-23T01:00:10Z
- Commits last 2h / 24h: 0 / 1
- Recent changes:
  - feat: willow-nest Layer 0 — Nest file lifecycle pipeline

## safe-app-grove — settling
- Last push: 2026-04-22T18:35:25Z
- Commits last 2h / 24h: 0 / 1
- Recent changes:
  - feat(grove): sync mcp_local + mcp_server — since_id, grove_watch, grove_watch_all

## fastapi, openclaw, willow-1.7, safe-app-* (20+ repos) — stable
- No commits in last 24h
