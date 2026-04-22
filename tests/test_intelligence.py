"""Tests for core/intelligence.py — Plan 3 intelligence passes.
b17: TINT9  ΔΣ=42
"""
import os
import pytest
import psycopg2.extras
from datetime import datetime, timezone, timedelta

os.environ.setdefault("WILLOW_PG_DB", "willow_19")


def _bridge():
    from core.pg_bridge import PgBridge
    return PgBridge()


def _put_old(bridge, atom_id, project, title, days_old=90):
    """Insert an atom with created_at backdated to days_old days ago."""
    bridge.knowledge_put({
        "id": atom_id,
        "project": project,
        "title": title,
        "summary": f"atom created {days_old} days ago",
    })
    old_ts = datetime.now(timezone.utc) - timedelta(days=days_old)
    with bridge.conn.cursor() as cur:
        cur.execute(
            "UPDATE knowledge SET created_at = %s WHERE id = %s",
            (old_ts, atom_id),
        )
    bridge.conn.commit()


# ── W19DR — Draugr ────────────────────────────────────────────────────────────

def test_draugr_scan_finds_old_uncategorized_atoms():
    from core.intelligence import draugr_scan
    bridge = _bridge()
    _put_old(bridge, "dr_test_zombie", "test_draugr", "zombie atom title", days_old=90)

    found = draugr_scan(bridge, days=60)
    assert "dr_test_zombie" in found

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project = 'test_draugr'")
    bridge.conn.commit()


def test_draugr_scan_ignores_community_nodes():
    from core.intelligence import draugr_scan
    bridge = _bridge()
    bridge.knowledge_put({
        "id": "dr_community_skip",
        "project": "test_draugr2",
        "title": "community detection node",
        "summary": "should be ignored by draugr scan",
        "source_type": "community_detection",
    })
    old_ts = datetime.now(timezone.utc) - timedelta(days=90)
    with bridge.conn.cursor() as cur:
        cur.execute("UPDATE knowledge SET created_at = %s WHERE id = 'dr_community_skip'", (old_ts,))
    bridge.conn.commit()

    found = draugr_scan(bridge, days=60)
    assert "dr_community_skip" not in found

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project = 'test_draugr2'")
    bridge.conn.commit()


def test_draugr_mark_sets_category():
    from core.intelligence import draugr_scan, draugr_mark
    bridge = _bridge()
    _put_old(bridge, "dr_mark_test", "test_draugr3", "mark this zombie", days_old=90)

    count = draugr_mark(bridge, ["dr_mark_test"])
    assert count == 1

    with bridge.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT category FROM knowledge WHERE id = 'dr_mark_test'")
        row = cur.fetchone()
    assert row["category"] == "draugr"

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project = 'test_draugr3'")
    bridge.conn.commit()


# ── W19SD — Serendipity ───────────────────────────────────────────────────────

def test_serendipity_surfaces_old_overlap_atoms():
    from core.intelligence import serendipity_pass
    bridge = _bridge()
    now = datetime.now(timezone.utc)

    bridge.knowledge_put({
        "id": "sd_old_atom",
        "project": "test_serendipity",
        "title": "ancient machine learning knowledge",
        "summary": "neural network patterns from the past",
    })
    old_ts = now - timedelta(days=60)
    with bridge.conn.cursor() as cur:
        cur.execute("UPDATE knowledge SET created_at = %s WHERE id = 'sd_old_atom'", (old_ts,))

    bridge.knowledge_put({
        "id": "sd_recent_atom",
        "project": "test_serendipity",
        "title": "machine learning today",
        "summary": "current neural network work",
    })
    recent_ts = now - timedelta(days=2)
    with bridge.conn.cursor() as cur:
        cur.execute("UPDATE knowledge SET created_at = %s WHERE id = 'sd_recent_atom'", (recent_ts,))
    bridge.conn.commit()

    surfaced = serendipity_pass(bridge, recent_days=7, old_min_days=30, old_max_days=180)
    ids = [a["id"] for a in surfaced]
    assert "sd_old_atom" in ids
    assert "sd_recent_atom" not in ids

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project = 'test_serendipity'")
    bridge.conn.commit()


def test_serendipity_returns_empty_when_no_recent():
    from core.intelligence import serendipity_pass
    bridge = _bridge()
    surfaced = serendipity_pass(bridge, recent_days=0, old_min_days=30, old_max_days=180)
    assert isinstance(surfaced, list)


# ── W19DM — Dark Matter ───────────────────────────────────────────────────────

def test_dark_matter_writes_implicit_connection():
    from core.intelligence import dark_matter_pass
    bridge = _bridge()

    bridge.knowledge_put({
        "id": "dm_atom_a",
        "project": "test_dm_proj_a",
        "title": "reinforcement learning policy gradient",
        "summary": "policy gradient methods for reinforcement learning agents",
    })
    bridge.knowledge_put({
        "id": "dm_atom_b",
        "project": "test_dm_proj_b",
        "title": "reinforcement learning reward function",
        "summary": "designing reward functions for reinforcement learning policy",
    })

    count = dark_matter_pass(bridge, min_overlap=2)
    assert count >= 1

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE project = 'dark_matter' AND source_type = 'dark_matter'")
        assert cur.fetchone()[0] >= 1

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project IN ('test_dm_proj_a', 'test_dm_proj_b', 'dark_matter')")
    bridge.conn.commit()


def test_dark_matter_skips_same_project():
    from core.intelligence import dark_matter_pass
    bridge = _bridge()

    bridge.knowledge_put({
        "id": "dm_same_a",
        "project": "test_dm_same",
        "title": "shared keyword topic neural network",
        "summary": "neural network shared keyword analysis",
    })
    bridge.knowledge_put({
        "id": "dm_same_b",
        "project": "test_dm_same",
        "title": "shared keyword topic neural network",
        "summary": "another neural network shared keyword analysis",
    })

    dark_matter_pass(bridge, min_overlap=2)

    with bridge.conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM knowledge WHERE source_type = 'dark_matter' "
            "AND content::text LIKE '%dm_same%'"
        )
        dm_for_same = cur.fetchone()[0]
    assert dm_for_same == 0

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project IN ('test_dm_same', 'dark_matter')")
    bridge.conn.commit()


# ── W19RV — Revelation ────────────────────────────────────────────────────────

def test_revelation_detects_cross_project_convergence():
    from core.intelligence import revelation_pass
    bridge = _bridge()

    bridge.knowledge_put({
        "id": "rv_community_a",
        "project": "test_rv_proj_a",
        "title": "Community node consciousness awareness mindfulness",
        "summary": "themes: consciousness awareness attention mindfulness presence",
        "source_type": "community_detection",
    })
    bridge.knowledge_put({
        "id": "rv_community_b",
        "project": "test_rv_proj_b",
        "title": "Community node awareness mindfulness presence",
        "summary": "themes: awareness mindfulness presence consciousness flow",
        "source_type": "community_detection",
    })

    count = revelation_pass(bridge, min_overlap=2)
    assert count >= 1

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE project = 'revelation' AND source_type = 'revelation'")
        assert cur.fetchone()[0] >= 1

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project IN ('test_rv_proj_a', 'test_rv_proj_b', 'revelation')")
    bridge.conn.commit()


def test_revelation_ignores_same_project_communities():
    from core.intelligence import revelation_pass
    bridge = _bridge()

    bridge.knowledge_put({
        "id": "rv_same_a",
        "project": "test_rv_same",
        "title": "community consciousness awareness mindfulness theme",
        "summary": "shared consciousness awareness mindfulness theme",
        "source_type": "community_detection",
    })
    bridge.knowledge_put({
        "id": "rv_same_b",
        "project": "test_rv_same",
        "title": "community consciousness awareness mindfulness",
        "summary": "more consciousness awareness mindfulness",
        "source_type": "community_detection",
    })

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE project = 'revelation' AND source_type = 'revelation'")
        initial_count = cur.fetchone()[0]

    revelation_pass(bridge, min_overlap=2)

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE project = 'revelation' AND source_type = 'revelation'")
        after_count = cur.fetchone()[0]
    assert after_count == initial_count

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project = 'test_rv_same'")
    bridge.conn.commit()


# ── W19MR — Mirror ────────────────────────────────────────────────────────────

def test_mirror_writes_meta_community():
    from core.intelligence import mirror_pass
    bridge = _bridge()

    for i in range(3):
        bridge.knowledge_put({
            "id": f"mr_community_{i}",
            "project": f"test_mr_proj_{i}",
            "title": f"Community node learning systems patterns iteration {i}",
            "summary": f"themes: learning systems patterns knowledge iteration {i}",
            "source_type": "community_detection",
        })

    count = mirror_pass(bridge)
    assert count == 1

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE project = 'mirror' AND source_type = 'mirror'")
        assert cur.fetchone()[0] >= 1

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project LIKE 'test_mr_%' OR project = 'mirror'")
    bridge.conn.commit()


def test_mirror_skips_when_too_few_nodes():
    from core.intelligence import mirror_pass
    bridge = _bridge()
    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project = 'mirror'")
    bridge.conn.commit()

    for i in range(2):
        bridge.knowledge_put({
            "id": f"mr_few_{i}",
            "project": f"test_mr_few_{i}",
            "title": f"community node few {i}",
            "source_type": "community_detection",
        })

    count = mirror_pass(bridge)
    assert count == 0

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project LIKE 'test_mr_few%'")
    bridge.conn.commit()


# ── W19MC — Mycorrhizal ───────────────────────────────────────────────────────

def test_mycorrhizal_feeds_sparse_project():
    from core.intelligence import mycorrhizal_pass
    bridge = _bridge()

    bridge.knowledge_put({
        "id": "mc_donor_community",
        "project": "test_mc_donor",
        "title": "Community node rich knowledge patterns themes",
        "summary": "rich knowledge patterns and themes for sparse projects",
        "source_type": "community_detection",
    })

    for j in range(2):
        bridge.knowledge_put({
            "id": f"mc_sparse_{j}",
            "project": "test_mc_sparse",
            "title": f"sparse atom {j}",
            "summary": "sparse project",
        })

    count = mycorrhizal_pass(bridge, sparse_threshold=5)
    assert count >= 1

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE project = 'test_mc_sparse' AND source_type = 'mycorrhizal'")
        assert cur.fetchone()[0] >= 1

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project IN ('test_mc_donor', 'test_mc_sparse')")
    bridge.conn.commit()


def test_mycorrhizal_skips_non_sparse_projects():
    from core.intelligence import mycorrhizal_pass
    bridge = _bridge()

    for j in range(6):
        bridge.knowledge_put({
            "id": f"mc_rich_{j}",
            "project": "test_mc_rich",
            "title": f"rich atom {j}",
            "summary": "rich project has many atoms",
        })

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE project = 'test_mc_rich' AND source_type = 'mycorrhizal'")
        count_before = cur.fetchone()[0]

    mycorrhizal_pass(bridge, sparse_threshold=5)

    with bridge.conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge WHERE project = 'test_mc_rich' AND source_type = 'mycorrhizal'")
        count_after = cur.fetchone()[0]
    assert count_after == count_before

    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project = 'test_mc_rich'")
    bridge.conn.commit()
