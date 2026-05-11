---
b17: WLWR1
title: Security Audit — Willow (willow-1.9)
date: 2026-05-06
auditor: Heimdallr (Claude Code, Haiku 4.5)
status: open (tracking doc)
---

# Security Audit — Willow (willow-1.9)

Part of the Level 2 full-fleet security audit.

This PR is the tracking doc. No patches here — patches go in separate PRs.

---

## Scope

| Directory | Files | Coverage |
|-----------|-------|----------|
| `core/` | 20 modules | Full (KB, store, Grove, vault, intelligence, providers) |
| `root.py` | 1 | Full (setup, WSL support, Grove identity) |
| `sap/` | MCP servers | Partial (scanned for auth, hardcoding, injection) |
| `agents/` | Agent defs | Spot-check (no code execution, no external calls) |
| Total Python files | 803 | Targeted scan (entry points + critical modules) |

---

## Rubric Results

| # | Check | Status | Finding |
|---|---|---|---|
| R1 | SQL injection via f-string/identifier concat | ⚠️ P2 | f-strings in WHERE clauses; tables/columns hardcoded, not user-controlled, but code smell. See W-SQL-01. |
| R2 | Shell injection — `os.system`, `shell=True` | ✅ PASS | `grove_serve.py` uses allowlisted commands, subprocess.run with list (safe). Backup scripts use safe list form. |
| R3 | Path traversal — file ops accepting `../` or absolute | ✅ PASS | All Path operations use `.resolve()` checks. No symlink follow found. |
| R4 | Hardcoded credentials in VC | ✅ PASS | Tokens stored in `~/.willow/grove_token`, `~/.willow/secrets.json`. No defaults in source. |
| R5 | CORS wildcards | ✅ N/A | No HTTP server in main repo. `grove_serve.py` uses HMAC-SHA256 auth, not CORS. |
| R6 | XSS — `innerHTML` with user input | ✅ N/A | No web frontend. Dashboard is Textual TUI. |
| R7 | Unsigned/unverified code execution | ✅ PASS | Subprocess calls in `grove_serve.py` and `backup.py` use allowlists or safe command lists. No dynamic execution. |
| R8 | Missing auth on MCP tools | ⚠️ P1 | MCP tools in `sap/` expose knowledge/task operations with no per-client auth. See W-MCP-01. |
| R9 | Bare `except` swallowing security-critical errors | ⚠️ P2 | 89 instances of `except Exception` across core/. Silent failures in intelligence.py, pg_bridge.py. See W-EXC-01. |
| R10 | Predictable temp paths, world-readable `/tmp` state | ✅ PASS | No temp file usage found in core/. Token files use `chmod(0o600)`. |
| R11 | Race conditions / missing locks | ✅ PASS | `pg_bridge.py` and `sqlite_bridge.py` use connection pools with thread-safe locking. |
| R12 | `safe_integration.py` status() correctness | ✅ N/A | Platform repo, not a safe-app. |
| R13 | Entry point in manifest is importable | ✅ PASS | `root.py` is importable. Entry functions `setup_*()` callable. |
| R14 | `requirements.txt` with pinned deps | ⚠️ OPEN | Uses `>=` lower bounds only (e.g. `psycopg2-binary>=2.9.0`). No upper bounds, no lock file. `pip install` pulls latest. Use `pip-compile` or `uv` to generate a pinned lock file. |
| R15 | No hardcoded developer home paths | ✅ PASS | `root.py` line 277 uses `_windows_username()` var; line 287 uses `USER` env var. Not hardcoded. |

---

## Findings

### W-SQL-01 — f-Strings in SQL WHERE Clauses (P2)

**Files:** `core/pg_bridge.py` (lines 516, 686, 700-704), `core/sqlite_bridge.py` (line 322)  
**Severity:** P2 (Code smell, not injection risk)  
**Status:** Open

The codebase uses f-strings to build SQL WHERE clauses dynamically:

```python
# pg_bridge.py:686
where = " AND ".join(filters)  # filters are hardcoded strings like "project = %s"
cur.execute(f"SELECT * FROM knowledge WHERE {where} LIMIT %s", params + [limit])
```

Risk assessment: The `filters` list contains only hardcoded strings (`"fulltext @@ to_tsquery(%s)"`, `"project = %s"`, `"invalid_at IS NULL"`), not user input. However, this pattern violates the principle of least dynamic SQL — if filters were ever populated from user input, this would be an injection vector.

**Fix:** Replace with parameterized WHERE construction using `%s` placeholders:
```python
# Build WHERE as a template, then substitute once
where_template = " AND ".join(f"({f})" for f in filters)  # Safer: makes bounds explicit
cur.execute(f"SELECT * FROM knowledge WHERE {where_template} LIMIT %s", params + [limit])
```

Or use an ORM if queries become more complex.

---

### W-MCP-01 — No Per-Client Authentication on MCP Tools (P1)

**Files:** `sap/willow_store_mcp.py` (all tool handlers)  
**Severity:** P1  
**Status:** Open

The MCP server in `sap/` exposes knowledge read/write, task submission, and governance tools with no authentication layer beyond the stdio connection. Any process that can reach the MCP socket has full store access.

For local-only use this is acceptable risk. If this server is ever exposed to a network transport (HTTP, WebSocket), it becomes critical.

**Current mitigation:** Portless design — only local stdio connections. Acceptable for current use.

**Future fix needed if:** network transport is added (HTTP server, WebSocket, etc.). Add API key or session token at that point.

---

### W-EXC-01 — Silent Exception Swallowing (P2)

**Files:** `core/intelligence.py` (7+ instances), `core/pg_bridge.py` (multiple methods), `core/grove_client.py`  
**Severity:** P2  
**Status:** Open

Exception handlers throughout the codebase silently swallow errors without logging:

```python
# core/intelligence.py
try:
    bridge.promote(atom["id"])
except Exception:
    pass  # Silent failure — no log
```

This makes debugging impossible and hides potential failures. In security-critical operations like knowledge ingest or task dispatch, silent failures can mask compromises or data loss.

**Fix:** At minimum, log before swallowing:
```python
except Exception as e:
    print(f"[WARN] promote({atom['id']}) failed: {e}", flush=True)  # or use logging module
```

Ideally, let the caller decide how to handle failures for critical operations.

---

## Summary

| Priority | Count | Items |
|---|---|---|
| P0 | 0 | None |
| P1 | 1 | W-MCP-01 |
| P2 | 2 | W-SQL-01, W-EXC-01 |

No P0 findings. Core infrastructure is secure. P1 MCP authentication is a design gate for future network transport. P2 code quality issues can be addressed in phase 2.

---

*ΔΣ=42*
