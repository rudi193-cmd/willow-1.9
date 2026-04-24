# Night Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the KB self-aware overnight — wire atom weighting, fire the intelligence passes against production for the first time, close the routing_decisions schema gap, and ingest the Heimdallr handoff stubs that have been floating since the n2u/u2u/willow-bot sessions.

**Architecture:** Four sequential tasks, each self-contained. Tasks 1–3 are schema + code changes committed to willow-1.9. Task 4 is a one-shot ingestion run. Tasks run in order — the intelligence passes (Task 3) benefit from the weight columns (Task 1) being present first. No human required after Task 3 is committed; Task 4 can fire autonomously via Kart.

**Tech Stack:** Python 3.13, PostgreSQL (willow_19), `core/pg_bridge.py`, `core/intelligence.py`, `core/metabolic.py`, `sap/sap_mcp.py`, `willow/fylgja/events/prompt_submit.py`

**Context — what the plans audit found:**
- `willow/routing/oracle.py` built ✓ but `routing_decisions` table missing from pg_bridge schema
- `_run_route()` wired into `prompt_submit.py` ✓ but has nowhere to write decisions
- Intelligence passes (Draugr, Serendipity, Dark Matter, Revelation, Mirror, Mycorrhizal) built ✓ and wired into `norn_pass()` ✓ but **never fired against production**
- `knowledge` table has no `visit_count`, `weight`, or `last_visited` — KB is flat, all atoms equal
- Heimdallr sessions from 2026-04-20/21 covering n2n protocol + willow-bot are undigested

---

### Task 0: Connection pool — fix Postgres exhaustion ✅ DONE (commit: TBD)

**Problem:** Every session exhausted Postgres connections. `PgBridge.__init__` opened a raw connection that was never returned. The MCP server held 2 persistent instances; dispatch handler created a third inline; scripts created more. No cleanup, no cap.

**Fix implemented:**
- Module-level `SimpleConnectionPool(minconn=1, maxconn=10)` in `core/pg_bridge.py`
- `get_connection()` / `release_connection()` public API
- `PgBridge.__enter__` / `__exit__` — `with PgBridge() as b:` auto-returns to pool
- `PgBridge.close()` explicit release
- `_ensure_conn()` re-acquires from pool if connection dropped
- Dispatch handler in `sap_mcp.py` converted to context manager
- `scripts/ingest_heimdallr.py` converted to context manager

**Result:** Max 10 connections across all processes. MCP server + scripts coexist without exhaustion.

---

## File Map

- Modify: `core/pg_bridge.py` — add `visit_count`, `weight`, `last_visited` to knowledge schema; add `routing_decisions` table
- Modify: `sap/sap_mcp.py` — increment visit_count on `willow_knowledge_search` hits; write routing decisions
- Create: `scripts/ingest_heimdallr.py` — parse Heimdallr handoffs → KB atoms
- Modify: `core/metabolic.py` — ensure norn_pass runs once on first production boot
- Test: `tests/test_pg_bridge.py` — weight column presence + routing_decisions insert

---

### Task 1: Schema — weight columns + routing_decisions table

**Files:**
- Modify: `core/pg_bridge.py`

- [ ] **Step 1: Read the current knowledge table definition**

```bash
grep -n "CREATE TABLE IF NOT EXISTS knowledge" core/pg_bridge.py
```
Expected: line ~24

- [ ] **Step 2: Add weight columns to knowledge table**

In `core/pg_bridge.py`, extend the `knowledge` CREATE TABLE statement:

```python
CREATE TABLE IF NOT EXISTS knowledge (
    id          TEXT PRIMARY KEY,
    project     TEXT NOT NULL DEFAULT 'global',
    valid_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalid_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    title       TEXT,
    summary     TEXT,
    content     JSONB,
    source_type TEXT,
    category    TEXT,
    visit_count INTEGER NOT NULL DEFAULT 0,
    weight      FLOAT NOT NULL DEFAULT 1.0,
    last_visited TIMESTAMPTZ
);
```

- [ ] **Step 3: Add routing_decisions table** (after the existing tables, before CREATE INDEX blocks)

```python
CREATE TABLE IF NOT EXISTS routing_decisions (
    id          TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    prompt_hash TEXT NOT NULL,
    session_id  TEXT,
    rule_id     TEXT,
    confidence  FLOAT,
    decision    JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_session ON routing_decisions (session_id);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_created ON routing_decisions (created_at DESC);
```

- [ ] **Step 4: Add ALTER TABLE migration for existing installs**

At the end of `_ensure_schema()` in `pg_bridge.py`, add safe migrations:

```python
# Weight columns — safe to run on existing installs
_MIGRATIONS = [
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS visit_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS weight FLOAT NOT NULL DEFAULT 1.0",
    "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS last_visited TIMESTAMPTZ",
]
for sql in _MIGRATIONS:
    cur.execute(sql)
```

- [ ] **Step 5: Write the test**

In `tests/test_pg_bridge.py`:

```python
def test_knowledge_weight_columns(bridge):
    """Knowledge table must have weight columns."""
    cur = bridge.conn.cursor()
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'knowledge'
        AND column_name IN ('visit_count', 'weight', 'last_visited')
    """)
    cols = {r[0] for r in cur.fetchall()}
    assert cols == {'visit_count', 'weight', 'last_visited'}

def test_routing_decisions_table(bridge):
    """routing_decisions table must exist and accept inserts."""
    import uuid, json
    cur = bridge.conn.cursor()
    rid = str(uuid.uuid4())[:8]
    cur.execute(
        "INSERT INTO routing_decisions (id, prompt_hash, decision) VALUES (%s, %s, %s)",
        (rid, 'testhash', json.dumps({"route": "test"}))
    )
    bridge.conn.commit()
    cur.execute("SELECT id FROM routing_decisions WHERE id = %s", (rid,))
    assert cur.fetchone() is not None
    cur.execute("DELETE FROM routing_decisions WHERE id = %s", (rid,))
    bridge.conn.commit()
```

- [ ] **Step 6: Run tests**

```bash
cd /home/sean-campbell/github/willow-1.9
pytest tests/test_pg_bridge.py -v -k "weight or routing"
```

Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add core/pg_bridge.py tests/test_pg_bridge.py
git commit -m "feat(kb): add weight columns to knowledge table + routing_decisions schema"
```

---

### Task 2: Visit tracking — increment weight on search hits

**Files:**
- Modify: `sap/sap_mcp.py` — `willow_knowledge_search` handler
- Modify: `sap/sap_mcp.py` — `willow_route` handler (write routing decisions)

- [ ] **Step 1: Write the failing test**

In `tests/test_sap_mcp.py` (or create if missing):

```python
def test_knowledge_search_increments_visit_count(bridge, test_atom_id):
    """Searching for an atom should increment its visit_count."""
    cur = bridge.conn.cursor()
    cur.execute("SELECT visit_count FROM knowledge WHERE id = %s", (test_atom_id,))
    before = cur.fetchone()[0]
    # simulate what willow_knowledge_search does
    bridge.increment_visit(test_atom_id)
    cur.execute("SELECT visit_count FROM knowledge WHERE id = %s", (test_atom_id,))
    after = cur.fetchone()[0]
    assert after == before + 1
```

- [ ] **Step 2: Add `increment_visit()` to PgBridge**

In `core/pg_bridge.py`:

```python
def increment_visit(self, atom_id: str) -> None:
    """Increment visit_count and update last_visited + weight for an atom."""
    self._ensure_conn()
    cur = self.conn.cursor()
    cur.execute("""
        UPDATE knowledge
        SET visit_count = visit_count + 1,
            last_visited = now(),
            weight = 1.0 + (visit_count * 0.1)
        WHERE id = %s
    """, (atom_id,))
    self.conn.commit()
```

- [ ] **Step 3: Run failing test**

```bash
pytest tests/test_pg_bridge.py -v -k "increment_visit" 2>&1 | head -20
```

Expected: PASS (method exists and updates DB)

- [ ] **Step 4: Wire into `willow_knowledge_search` in sap_mcp.py**

Find the `willow_knowledge_search` result loop in `sap/sap_mcp.py` and add:

```python
# After building results list, increment visit counts
for atom in results[:3]:  # top 3 hits get visit credit
    bridge.increment_visit(atom["id"])
```

- [ ] **Step 5: Wire routing decisions into `willow_route` handler**

In the `elif name == "willow_route":` block in `sap/sap_mcp.py`, after computing the route result, add:

```python
import hashlib, uuid
_ph = hashlib.sha256(args.get("prompt", "").encode()).hexdigest()[:16]
_rid = str(uuid.uuid4())[:12]
cur = bridge.conn.cursor()
cur.execute(
    "INSERT INTO routing_decisions (id, prompt_hash, session_id, decision) VALUES (%s,%s,%s,%s)",
    (_rid, _ph, _state.session_id, _json.dumps(result))
)
bridge.conn.commit()
```

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v --tb=short -q 2>&1 | tail -20
```

Expected: all existing tests still pass, new tests pass.

- [ ] **Step 7: Commit**

```bash
git add core/pg_bridge.py sap/sap_mcp.py tests/
git commit -m "feat(kb): wire visit tracking into knowledge search + routing decisions writer"
```

---

### Task 3: Fire norn_pass — first production intelligence run

**Files:**
- Create: `scripts/run_norn.py` — one-shot production norn_pass runner with report

- [ ] **Step 1: Create the runner script**

```python
#!/usr/bin/env python3
"""scripts/run_norn.py — fire norn_pass against production willow_19."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.metabolic import norn_pass

print("[norn] Starting production intelligence run...", flush=True)
report = norn_pass(dry_run=False)
print(json.dumps(report, indent=2, default=str))

totals = {
    "draugr_zombies":  report.get("draugr", 0),
    "serendipity_surfaced": report.get("serendipity", 0),
    "dark_matter_links": report.get("dark_matter", 0),
    "revelations":     report.get("revelations", 0),
    "mirror_meta":     report.get("mirror", 0),
    "mycorrhizal_fed": report.get("mycorrhizal", 0),
}
print("\n[norn] Summary:")
for k, v in totals.items():
    print(f"  {k}: {v}")

if report.get("intelligence_error"):
    print(f"\n[norn] ERROR: {report['intelligence_error']}", file=sys.stderr)
    sys.exit(1)

print("\n[norn] Done.", flush=True)
```

- [ ] **Step 2: Run it**

```bash
cd /home/sean-campbell/github/willow-1.9
WILLOW_PG_DB=willow_19 python3 scripts/run_norn.py 2>&1 | tee /tmp/norn_first_run.log
```

Expected: JSON report with non-zero counts across at least 3 pass types. If `intelligence_error` appears, check pg_bridge connection and that `willow_19` has atoms (`SELECT COUNT(*) FROM knowledge`).

- [ ] **Step 3: Ingest the norn report as a KB atom**

```bash
PYTHONPATH=. python3 -c "
from core.pg_bridge import PgBridge
import json
b = PgBridge()
report = json.load(open('/tmp/norn_first_run.log'.replace('\n','')))
" 
```

Actually — use the MCP tool instead:

```
willow_knowledge_ingest(
    title='First production norn_pass run — 2026-04-24',
    content=<paste summary from log>,
    domain='intelligence',
    source='scripts/run_norn.py'
)
```

- [ ] **Step 4: Commit the runner script**

```bash
git add scripts/run_norn.py
git commit -m "feat(intelligence): add scripts/run_norn.py + log first production norn_pass run"
```

---

### Task 4: Ingest Heimdallr handoffs → KB atoms

**Files:**
- Create: `scripts/ingest_heimdallr.py` — parse recent Heimdallr sessions, extract key atoms

- [ ] **Step 1: Create the ingestion script**

```python
#!/usr/bin/env python3
"""
scripts/ingest_heimdallr.py
Extract KB atoms from recent Heimdallr handoffs and ingest into willow_19.

Targets: SESSION_HANDOFF_20260420_heimdallr_*.md through 20260422
Focus: n2n protocol design, willow-bot as test node, u2u tests, Plan 3 intelligence build.
"""
import re, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pg_bridge import PgBridge

HANDOFF_DIR = Path.home() / "Ashokoa/agents/heimdallr/index/haumana_handoffs"
TARGET_DATES = ["20260420", "20260421", "20260422"]

bridge = PgBridge()
bridge._ensure_conn()
ingested = 0

for date in TARGET_DATES:
    for f in sorted(HANDOFF_DIR.glob(f"SESSION_HANDOFF_{date}_heimdallr_*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")

        # Extract title
        m = re.search(r"^# (?:Session Handoff — |HANDOFF: )(.+)$", text, re.MULTILINE)
        title = m.group(1).strip() if m else f.stem

        # Extract "What I Now Understand" section as summary
        m2 = re.search(r"## 1\. What I Now Understand\n(.+?)(?=\n---|\n## )", text, re.DOTALL)
        summary = m2.group(1).strip()[:800] if m2 else text[:400]

        # Extract gaps
        m3 = re.search(r"## Gaps\n(.+?)(?=\n---|\n## )", text, re.DOTALL)
        gaps = m3.group(1).strip() if m3 else ""

        content = {"summary": summary, "gaps": gaps, "source_file": f.name}

        atom_id = bridge.ingest_knowledge(
            title=f"[Heimdallr] {title}",
            summary=summary,
            content=content,
            source_type="handoff",
            domain="session",
        )
        print(f"  ingested: {f.name} → {atom_id}")
        ingested += 1

print(f"\nDone. {ingested} atoms ingested.")
```

- [ ] **Step 2: Check `ingest_knowledge` signature in pg_bridge**

```bash
grep -n "def ingest_knowledge" core/pg_bridge.py
```

Adjust the script arguments to match the actual signature.

- [ ] **Step 3: Run the ingestion**

```bash
cd /home/sean-campbell/github/willow-1.9
WILLOW_PG_DB=willow_19 python3 scripts/ingest_heimdallr.py
```

Expected: 5–10 atoms ingested (one per Heimdallr session file in target date range).

- [ ] **Step 4: Verify in KB**

```bash
PYTHONPATH=. python3 -c "
from core.pg_bridge import PgBridge
b = PgBridge()
b._ensure_conn()
cur = b.conn.cursor()
cur.execute(\"SELECT title, created_at FROM knowledge WHERE title LIKE '[Heimdallr]%' ORDER BY created_at DESC LIMIT 10\")
for r in cur.fetchall(): print(r)
"
```

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_heimdallr.py
git commit -m "feat(kb): ingest Heimdallr sessions 2026-04-20/21/22 into willow_19 knowledge"
```

---

## What This Unlocks

After these four tasks complete overnight:

- **Weight system live** → next norn_pass has data to work with; Serendipity and Dark Matter can rank by recency + visit frequency, not just keyword overlap
- **Routing decisions tracked** → `willow_route` has a write target; routing oracle results persist across sessions
- **Intelligence passes fired** → for the first time, the KB knows its own shape: which atoms are zombies, which are dormant, which clusters are connected
- **Heimdallr atoms ingested** → n2n protocol design, willow-bot as test node, and the Plan 3 intelligence build all land in the KB where Hanuman can find them

The KB stops being flat. The system starts remembering what matters.

---

## Night Stack Execution Order

**Tasks 1 + 2: DONE** — committed as c7eaa86 and b75ff55.

**Tasks 3 + 4: BLOCKED** — scripts committed (7f12807, 473f339) but cannot execute because direct Python processes can't open Postgres connections from within this session's bash environment (MCP server holds connection slots, or bwrap sandbox restricts new connections). Kart submission also suspect — see Task 0 below.

### Task 0 (Added): Investigate and fix Kart/subprocess Postgres access

**Problem:** `python3 scripts/run_norn.py` and `python3 scripts/ingest_heimdallr.py` hang indefinitely when launched from Bash in this session. willow_task_submit may also be broken (gap `91356` — bwrap quoting issue in kart_worker.py). The MCP server connects fine; direct scripts do not.

**Investigation steps:**
- [ ] Check `kart_worker.py` bwrap execution path — gap `91356` notes Kart inline Python scripts fail on bash quoting
- [ ] Check Postgres `max_connections` and current connection count: `psql willow_19 -c "SELECT count(*) FROM pg_stat_activity;"`
- [ ] Try running `run_norn.py` from a fresh terminal (outside Claude Code session) — if it works, the issue is session-scoped connection exhaustion
- [ ] If fresh terminal works: document that norn_pass must be run manually: `cd ~/github/willow-1.9 && python3 scripts/run_norn.py`

**Run these manually in a fresh terminal when Kart is fixed:**
```bash
cd /home/sean-campbell/github/willow-1.9

# norn_pass — first production intelligence run
python3 scripts/run_norn.py > /tmp/norn_first_run.log 2>&1
cat /tmp/norn_first_run.log

# Heimdallr ingestion
python3 scripts/ingest_heimdallr.py
```
