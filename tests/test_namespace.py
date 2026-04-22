"""Tests for W19NS — namespace scoping."""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pg_bridge import PgBridge


@pytest.fixture
def pg():
    bridge = PgBridge()
    with bridge.conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge WHERE project IN ('proj_a', 'proj_b', 'global') AND id LIKE 'ns_test_%'")
    bridge.conn.commit()
    return bridge


def test_put_uses_project(pg):
    pg.knowledge_put({"id": "ns_test_1", "project": "proj_a",
                       "title": "Alpha secret", "summary": "only in proj_a"})
    results = pg.knowledge_search("Alpha secret", project="proj_a")
    assert len(results) == 1


def test_search_scoped_to_project(pg):
    pg.knowledge_put({"id": "ns_test_2", "project": "proj_a",
                       "title": "proj_a doc", "summary": "belongs to a"})
    pg.knowledge_put({"id": "ns_test_3", "project": "proj_b",
                       "title": "proj_b doc", "summary": "belongs to b"})
    results_a = pg.knowledge_search("doc", project="proj_a")
    assert all(r["project"] == "proj_a" for r in results_a)


def test_search_without_project_returns_only_that_project(pg):
    pg.knowledge_put({"id": "ns_test_4", "project": "global",
                       "title": "global doc", "summary": "in global"})
    pg.knowledge_put({"id": "ns_test_5", "project": "proj_a",
                       "title": "proj_a doc", "summary": "in proj_a"})
    results = pg.knowledge_search("doc", project="global")
    assert all(r["project"] == "global" for r in results)


def test_default_project_is_global(pg):
    pg.knowledge_put({"id": "ns_test_6", "title": "no project set",
                       "summary": "should default to global"})
    with pg.conn.cursor() as cur:
        cur.execute("SELECT project FROM knowledge WHERE id = 'ns_test_6'")
        row = cur.fetchone()
    assert row[0] == "global"
