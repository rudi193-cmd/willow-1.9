#!/usr/bin/env python3
"""
intelligence.py — Plan 3 intelligence passes.
b17: INT19  ΔΣ=42

W19DR: Draugr — zombie atom detection
W19SD: Serendipity — surfaces dormant knowledge
W19DM: Dark Matter — implicit connection inference
W19RV: Revelation — cross-project convergence detection
W19MR: Mirror — meta-community detection
W19MC: Mycorrhizal — sparse KB feeding from adjacent projects
PMEM2: Insight pass + Chunk synthesis
"""
import psycopg2.extras
import uuid as _uuid
from collections import Counter
from datetime import datetime, timezone, timedelta

try:
    from core.yggdrasil import ask_structured as _ygg_structured
except Exception:
    def _ygg_structured(prompt: str, timeout: int = 30) -> dict:  # type: ignore
        return {"summary": None, "importance": 0}

_AGENT = "hanuman"


_SYSTEM_SOURCE_TYPES = frozenset({
    "community_detection", "dark_matter", "revelation", "mirror", "mycorrhizal",
})
_SYSTEM_PROJECTS = frozenset({"dark_matter", "revelation", "mirror", "global"})


# ── W19DR — Draugr ────────────────────────────────────────────────────────────

def draugr_scan(bridge, days: int = 60) -> list:
    """
    Find atoms still valid but not updated in `days` days.
    Ignores system source types (community, dark matter, etc).
    Returns list of atom IDs. W19DR.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with bridge.conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM knowledge
            WHERE invalid_at IS NULL
              AND created_at < %s
              AND (source_type IS NULL OR source_type NOT IN %s)
            ORDER BY created_at ASC
            LIMIT 100
        """, (cutoff, tuple(_SYSTEM_SOURCE_TYPES)))
        return [row[0] for row in cur.fetchall()]


def draugr_mark(bridge, atom_ids: list) -> int:
    """Mark draugr atoms with category='draugr'. Does not close or delete them.
    System source types (community_detection, dark_matter, etc.) are never marked."""
    if not atom_ids:
        return 0
    with bridge.conn.cursor() as cur:
        cur.execute(
            "UPDATE knowledge SET category = 'draugr' "
            "WHERE id = ANY(%s) AND invalid_at IS NULL "
            "AND (source_type IS NULL OR source_type NOT IN %s)",
            (atom_ids, tuple(_SYSTEM_SOURCE_TYPES))
        )
        count = cur.rowcount
    bridge.conn.commit()
    return count


# ── W19SD — Serendipity ───────────────────────────────────────────────────────

def serendipity_pass(bridge, recent_days: int = 7,
                     old_min_days: int = 30, old_max_days: int = 180) -> list:
    """
    Surface atoms from old_min_days–old_max_days ago that share keywords
    with atoms created in the last recent_days. W19SD.
    Returns list of surfaced atom dicts (max 5).
    """
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=recent_days)
    old_min = now - timedelta(days=old_max_days)
    old_max = now - timedelta(days=old_min_days)

    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT title, summary FROM knowledge
            WHERE invalid_at IS NULL AND created_at >= %s
            LIMIT 20
        """, (recent_cutoff,))
        recent = [dict(r) for r in cur.fetchall()]

    if not recent:
        return []

    keywords = set()
    for atom in recent:
        for field in (atom.get("title") or "", atom.get("summary") or ""):
            keywords.update(w.lower() for w in field.split() if len(w) > 4)

    if not keywords:
        return []

    surfaced, seen = [], set()
    for kw in list(keywords)[:5]:
        with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM knowledge
                WHERE invalid_at IS NULL
                  AND created_at BETWEEN %s AND %s
                  AND (title ILIKE %s OR summary ILIKE %s)
                LIMIT 3
            """, (old_min, old_max, f"%{kw}%", f"%{kw}%"))
            for r in cur.fetchall():
                d = dict(r)
                if d["id"] not in seen:
                    seen.add(d["id"])
                    surfaced.append(d)

    for atom in surfaced[:5]:
        try:
            bridge.promote(atom["id"])
        except Exception:
            pass

    return surfaced[:5]


# ── W19DM — Dark Matter ───────────────────────────────────────────────────────

def _keywords(atom: dict) -> set:
    text = f"{atom.get('title') or ''} {atom.get('summary') or ''}".lower()
    return {w for w in text.split() if len(w) > 4}


def dark_matter_pass(bridge, min_overlap: int = 3, limit: int = 100) -> int:
    """
    Infer implicit connections from keyword overlap between atoms of different projects.
    Writes source_type='dark_matter' atoms to project='dark_matter'. W19DM.
    Returns count of atoms written.
    """
    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, project, title, summary FROM knowledge
            WHERE invalid_at IS NULL
              AND (source_type IS NULL OR source_type NOT IN %s)
            ORDER BY created_at DESC LIMIT %s
        """, (tuple(_SYSTEM_SOURCE_TYPES), limit))
        atoms = [dict(r) for r in cur.fetchall()]

    written, seen_pairs = 0, set()
    for i, a in enumerate(atoms):
        for b in atoms[i + 1:]:
            if a["project"] == b["project"]:
                continue
            pair_key = tuple(sorted([a["id"], b["id"]]))
            if pair_key in seen_pairs:
                continue
            overlap = _keywords(a) & _keywords(b)
            if len(overlap) >= min_overlap:
                seen_pairs.add(pair_key)
                dm_id = f"dm_{a['id'][:8]}_{b['id'][:8]}"
                bridge.knowledge_put({
                    "id": dm_id,
                    "project": "dark_matter",
                    "title": f"Implicit connection: {a['project']} ↔ {b['project']}",
                    "summary": f"Shared concepts: {', '.join(sorted(overlap)[:5])}",
                    "source_type": "dark_matter",
                    "category": "implicit",
                    "content": {
                        "atom_a": a["id"],
                        "atom_b": b["id"],
                        "overlap": sorted(overlap),
                    },
                })
                try:
                    bridge.promote(a["id"])
                    bridge.promote(b["id"])
                except Exception:
                    pass
                written += 1
                if written >= 20:
                    return written
    return written


# ── W19RV — Revelation ────────────────────────────────────────────────────────

def revelation_pass(bridge, min_overlap: int = 3) -> int:
    """
    Detect convergence between community nodes from different projects.
    Two isolated clusters discovering the same truth — Cauldron of Wisdom. W19RV.
    Writes source_type='revelation' atoms to project='revelation'.
    Returns count of revelation atoms written.
    """
    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, project, title, summary FROM knowledge
            WHERE invalid_at IS NULL AND source_type = 'community_detection'
            ORDER BY created_at DESC LIMIT 50
        """)
        nodes = [dict(r) for r in cur.fetchall()]

    written, seen_pairs = 0, set()
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            if a["project"] == b["project"]:
                continue
            pair_key = tuple(sorted([a["id"], b["id"]]))
            if pair_key in seen_pairs:
                continue
            overlap = _keywords(a) & _keywords(b)
            if len(overlap) >= min_overlap:
                seen_pairs.add(pair_key)
                # Monthly ID: one revelation per project-pair per month, newest wins
                rev_id = f"rev_{a['project'][:8]}_{b['project'][:8]}_{datetime.now(timezone.utc).strftime('%Y%m')}"
                bridge.knowledge_put({
                    "id": rev_id,
                    "project": "revelation",
                    "title": f"Revelation: {a['project']} ↔ {b['project']}",
                    "summary": (
                        f"Cauldron of Wisdom — two isolated projects converge. "
                        f"Shared: {', '.join(sorted(overlap)[:5])}"
                    ),
                    "source_type": "revelation",
                    "category": "convergence",
                    "content": {
                        "node_a": a["id"],
                        "node_b": b["id"],
                        "project_a": a["project"],
                        "project_b": b["project"],
                        "overlap": sorted(overlap),
                    },
                })
                written += 1
    return written


# ── W19MR — Mirror ────────────────────────────────────────────────────────────

def mirror_pass(bridge) -> int:
    """
    Meta-community detection: run community detection on community nodes.
    The KB looks at itself. W19MR.
    Requires >= 3 community nodes. Writes source_type='mirror'.
    Returns 1 if mirror atom written, 0 otherwise.
    """
    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, project, title, summary FROM knowledge
            WHERE invalid_at IS NULL AND source_type = 'community_detection'
        """)
        nodes = [dict(r) for r in cur.fetchall()]

    if len(nodes) < 3:
        return 0

    kw_counter = Counter()
    for node in nodes:
        kw_counter.update(_keywords(node))

    top_themes = [kw for kw, _ in kw_counter.most_common(5)]
    if not top_themes:
        return 0

    now = datetime.now(timezone.utc)
    mirror_id = f"mirror_{now.strftime('%Y%m')}"
    bridge.knowledge_put({
        "id": mirror_id,
        "project": "mirror",
        "title": f"Mirror — KB self-model {now.strftime('%Y-%m')}",
        "summary": (
            f"{len(nodes)} community nodes. "
            f"Dominant themes: {', '.join(top_themes)}"
        ),
        "source_type": "mirror",
        "category": "meta",
        "content": {
            "community_count": len(nodes),
            "top_themes": top_themes,
            "projects": list({n["project"] for n in nodes}),
        },
    })
    return 1


# ── W19MC — Mycorrhizal ───────────────────────────────────────────────────────

def mycorrhizal_pass(bridge, sparse_threshold: int = 5) -> int:
    """
    Feed sparse KBs from adjacent project community nodes.
    Projects with < sparse_threshold atoms receive nutrients from richer neighbors. W19MC.
    Returns count of mycorrhizal atoms written.
    """
    with bridge.conn.cursor() as cur:
        cur.execute("""
            SELECT project, COUNT(*) AS cnt FROM knowledge
            WHERE invalid_at IS NULL
              AND project NOT IN %s
            GROUP BY project
            HAVING COUNT(*) < %s
        """, (tuple(_SYSTEM_PROJECTS), sparse_threshold))
        sparse_projects = [row[0] for row in cur.fetchall()]

    if not sparse_projects:
        return 0

    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, project, title, summary FROM knowledge
            WHERE invalid_at IS NULL
              AND source_type = 'community_detection'
              AND project NOT IN %s
            ORDER BY created_at DESC LIMIT 20
        """, (tuple(_SYSTEM_PROJECTS),))
        donors = [dict(r) for r in cur.fetchall()]

    if not donors:
        return 0

    written = 0
    for sparse_project in sparse_projects:
        for node in donors[:3]:
            if node["project"] == sparse_project:
                continue
            myco_id = f"myco_{sparse_project[:8]}_{node['id'][:8]}"
            bridge.knowledge_put({
                "id": myco_id,
                "project": sparse_project,
                "title": f"Mycorrhizal — {node.get('title', '')}",
                "summary": node.get("summary", ""),
                "source_type": "mycorrhizal",
                "category": "fed",
                "content": {
                    "donor_project": node["project"],
                    "donor_id": node["id"],
                },
            })
            written += 1
    return written


# ── PMEM2: Insight pass ────────────────────────────────────────────────────────

def _domain_from_target(target: str) -> str:
    """Extract domain label from file target path.
    'core/pg_bridge.py' → 'pg_bridge', '' → 'general'
    """
    if not target:
        return "general"
    parts = target.replace("\\", "/").split("/")
    clean = parts[-1].replace(".py", "") if parts else "general"
    return clean or "general"


def _cluster_reflections(reflections: list) -> dict:
    """Group reflections by domain. Returns {domain: [reflection, ...]}."""
    clusters: dict = {}
    for r in reflections:
        if r.get("insight_skip"):
            continue
        domain = _domain_from_target(r.get("target", ""))
        clusters.setdefault(domain, []).append(r)
    return clusters


def insight_pass(store_call) -> dict:
    """Cluster reflection atoms by domain, write insight atom when N≥3.

    store_call: callable(tool_name, args_dict, timeout=N) → result
    Processes all existing reflections regardless of age (backlog pass).
    Returns {"insights_written": int}.
    """
    try:
        all_atoms = store_call("store_list", {
            "app_id": _AGENT,
            "collection": "hanuman/atoms/store",
        }, timeout=8) or []
    except Exception:
        return {"insights_written": 0, "error": "store_list failed"}

    reflections = [
        a for a in all_atoms
        if a.get("type") == "reflection"
        and not a.get("insight_skip")
        and a.get("invalid_at") is None
    ]

    clusters = _cluster_reflections(reflections)
    insights_written = 0

    for domain, members in clusters.items():
        if len(members) < 3:
            continue

        ref_summaries = "\n".join(f"- {r.get('summary', '')}" for r in members[:10])
        prompt = (
            f"These {len(members)} session reflections are all about domain '{domain}':\n"
            f"{ref_summaries}\n\n"
            "Is this actually a pattern or a coincidence?\n"
            "If a pattern: write the single transferable rule.\n"
            "Format: SUMMARY: <one sentence rule> | IMPORTANCE: <1-10>\n"
            "If coincidence: SUMMARY: coincidence | IMPORTANCE: 1"
        )
        result = _ygg_structured(prompt, timeout=60)

        if not result["summary"] or result["importance"] < 6:
            for r in members:
                try:
                    store_call("store_update", {
                        "app_id": _AGENT,
                        "collection": "hanuman/atoms/store",
                        "record_id": r["id"],
                        "record": {**r, "insight_skip": True},
                    }, timeout=4)
                except Exception:
                    pass
            continue

        now = datetime.now(timezone.utc)
        insight_id = f"insight-{_uuid.uuid4().hex[:8]}"

        try:
            store_call("store_put", {
                "app_id": _AGENT,
                "collection": "hanuman/atoms/store",
                "record": {
                    "id": insight_id,
                    "type": "insight",
                    "source": "insight",
                    "summary": result["summary"],
                    "domain": domain,
                    "evidence": [r["id"] for r in members],
                    "importance": result["importance"],
                    "next_review": (now + timedelta(days=7)).isoformat(),
                    "review_interval_days": 7,
                    "stability": 2.0,
                    "valid_at": now.isoformat(),
                    "invalid_at": None,
                    "superseded_by": None,
                },
            }, timeout=4)
            insights_written += 1
        except Exception:
            continue

        for r in members:
            try:
                store_call("store_update", {
                    "app_id": _AGENT,
                    "collection": "hanuman/atoms/store",
                    "record_id": r["id"],
                    "record": {**r, "invalid_at": now.isoformat(), "superseded_by": insight_id},
                }, timeout=4)
            except Exception:
                pass

    return {"insights_written": insights_written}


# ── PMEM2: Chunk synthesis ─────────────────────────────────────────────────────

_EXECUTABLE_DOMAINS = {
    "pg_bridge", "willow_store", "stop", "session_start",
    "intelligence", "metabolic", "sap_mcp", "post_tool",
}


def chunk_pass(store_call) -> dict:
    """Cluster insights on executable domains into reusable chunk atoms.

    store_call: callable(tool_name, args_dict, timeout=N) → result
    Returns {"chunks_written": int}.
    """
    try:
        all_atoms = store_call("store_list", {
            "app_id": _AGENT,
            "collection": "hanuman/atoms/store",
        }, timeout=8) or []
        existing_skills = store_call("store_list", {
            "app_id": _AGENT,
            "collection": "hanuman/skills/store",
        }, timeout=5) or []
    except Exception:
        return {"chunks_written": 0, "error": "store_list failed"}

    insights = [
        a for a in all_atoms
        if a.get("type") == "insight"
        and a.get("invalid_at") is None
        and a.get("domain") in _EXECUTABLE_DOMAINS
    ]

    existing_domains = {s.get("domain") for s in existing_skills}
    by_domain: dict = {}
    for ins in insights:
        by_domain.setdefault(ins["domain"], []).append(ins)

    chunks_written = 0
    for domain, members in by_domain.items():
        if len(members) < 2 or domain in existing_domains:
            continue

        insight_summaries = "\n".join(f"- {i['summary']}" for i in members)
        prompt = (
            f"These insights describe patterns in domain '{domain}':\n"
            f"{insight_summaries}\n\n"
            "Write a reusable pattern a developer can follow:\n"
            "Format:\n"
            "SUMMARY: <one-line pattern description>\n"
            "IMPORTANCE: <1-10>"
        )
        result = _ygg_structured(prompt, timeout=60)
        if not result["summary"] or result["importance"] < 6:
            continue

        now = datetime.now(timezone.utc)
        chunk_id = f"chunk-{_uuid.uuid4().hex[:8]}"

        try:
            store_call("store_put", {
                "app_id": _AGENT,
                "collection": "hanuman/skills/store",
                "record": {
                    "id": chunk_id,
                    "type": "chunk",
                    "source": "chunk",
                    "domain": domain,
                    "summary": result["summary"],
                    "evidence": [i["id"] for i in members],
                    "importance": result["importance"],
                    "success_count": 0,
                    "failure_count": 0,
                    "next_review": (now + timedelta(days=14)).isoformat(),
                    "review_interval_days": 14,
                    "stability": 3.0,
                    "valid_at": now.isoformat(),
                    "invalid_at": None,
                },
            }, timeout=4)
            chunks_written += 1
        except Exception:
            continue

    return {"chunks_written": chunks_written}
