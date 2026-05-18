# Machine path audit (willow-1.9)

**Date:** 2026-05-18  
**Host baseline:** Checkout at `/home/sean-campbell/willow-1.9`; `~/github` contained only `safe-app-willow-grove` (no `willow-1.9`, `willow-nest`, `willow-dashboard`, or `safe-app-grove`); `~/.willow-venv` absent; `…/willow-1.9/.venv-dev` present.

This document records **hardcoded or default paths that did not match that layout**. It is an audit only — no remediation tracked here.

---

## Summary table

| Assumption in repo | This machine |
|--------------------|--------------|
| `~/github/willow-1.9` or `/home/sean-campbell/github/willow-1.9` | **Missing** (repo is `~/willow-1.9`) |
| `~/.willow-venv` | **Missing** |
| `~/github/safe-app-grove` | **Missing** (actual: `~/github/safe-app-willow-grove`) |
| `~/github/safe-app-willow-grove` | **Present** |
| `~/github/willow-nest`, `~/github/willow-dashboard`, `~/github/yggdrasil-training-data/...` | **Missing** |
| `~/Ashokoa/...` | **Missing** |
| `~/agents/hanuman/...` | **Missing** (`~/agents` had only `heimdallr`) |
| `%h/github/willow-1.9` in systemd units | **Wrong** checkout location |

---

## High-impact code & units

### Systemd (`systemd/*.service`)

- **`willow-mcp.service`**, **`willow-grove-listen.service`**, **`willow-metabolic.service`**: `%h/github/willow-1.9`, `PYTHONPATH=%h/github/willow-1.9`, and/or `%h/.willow-venv/bin/python3`.
- **`grove-mcp.service`**: `%h/github/safe-app-willow-grove` — **aligned** with the audited host.

### Python defaults and helpers

- `app.py` — `WILLOW_ROOT` defaults to `Path.home() / "github" / "willow-1.9"`.
- `kart_worker.py` — ledger candidate includes `~/github/willow-1.9`; references `~/.willow-venv`.
- `fleet.py`, `kart_worker.py` — `~/.willow-venv/bin/python3`.
- `sap/openclaw_mcp.py` — `.willow-venv` + `cwd` under `github/willow-1.9`.
- `sap/core/inference.py` — `CODEX_REPO` → `~/github/willow-nest`.
- `sap/clients/soil_client.py`, `scripts/willow_watchdog.py`, `scripts/wt_create.py` — `~/github/willow-1.9` fallbacks.
- `willow/fylgja/skills/scripts/system_health.py` — `~/github/willow-1.9` default repo path.
- `scripts/grove_correction_extractor.py` — default output under `~/github/yggdrasil-training-data/...`.

### Grove repo naming inconsistency

Runtime code disagrees with the **actual** dirname on disk (`safe-app-willow-grove`):

- `willow/grove_monitor.py` uses `~/github/safe-app-grove`.
- `core/metabolic.py` uses sibling `safe-app-grove`.

`seed.py` uses **`safe-app-willow-grove`** (matches host).

---

## Config & IDE

- **`.mcp.json`**: Interpreter and args under **`/home/sean-campbell/willow-1.9`** — **matches** host; **`PYTHONPATH`** includes **`…/github/safe-app-willow-grove`** — **matches**.
- **`.claude/settings.local.json`**: Mix of **`…/willow-1.9`** (matches) and **`…/github/safe-app-willow-grove`** (matches); optional media path under **`/run/media/sean-campbell/writable`** (present on host when mounted).

---

## Documentation & commands

Broad surfaces assume **`~/github/willow-1.9`** and **`~/github/willow/fylgja`** style roots, including:

- `AGENTS.md` / `.cursor/commands/*.md` / `.claude/commands/*.md`
- `willow/fylgja/skills/power.md`, `willow/fylgja/powers/SURFACES.md`, `willow/fylgja/powers/overseer.md`, `wiki/the-fleet.md`, `README-FELIX.md`, `docs/IDE_INTEGRATION.md`
- **`docs/superpowers/**`** (plans, specs) — extensive `cd`, `git -C`, and `ExecStart` examples.

---

## Tests & placeholders

- `tests/test_fylgja/test_install.py`, `tests/test_fylgja/test_safety_platform.py` — `github/willow-1.9` or **`agents/hanuman`** paths.
- `tests/test_fylgja/test_pre_tool.py`, security tests — **`/home/sean/…`**, **`/home/user/…`** (intentional fixtures / placeholders).

---

## WSL / Windows (expected only in those environments)

- `seed.py`, `root.py`: `/mnt/c/Users/...` for Desktop launcher — not applicable to bare Linux unless WSL bridging is used.
- Regex examples in `sap/sap_mcp*.py`: `/Users/...` scrub patterns (not host paths).

---

## Cross-reference

- `.mcp.json.example` uses placeholder **`/path/to/safe-app-grove`** (generic).

When remediating, prefer env vars (`WILLOW_ROOT`, `WILLOW_FYLGJA_ROOT`, `PYTHONPATH`) and **`%h`-free drop-ins** for systemd rather than committing a single developer’s `$HOME` layout.
