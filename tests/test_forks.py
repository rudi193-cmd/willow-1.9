"""tests/test_forks.py — Fork CRUD tests."""
import pytest
from core.pg_bridge import PgBridge
from willow.forks import (
    fork_create, fork_join, fork_log, fork_merge,
    fork_delete, fork_status, fork_list,
)


@pytest.fixture
def bridge():
    b = PgBridge()
    yield b
    b.conn.close()


def _cleanup(bridge, fork_id):
    cur = bridge.conn.cursor()
    cur.execute("DELETE FROM forks WHERE id = %s", (fork_id,))
    bridge.conn.commit()


def test_fork_create(bridge):
    f = fork_create(bridge, title="test fork", created_by="hanuman", topic="test")
    assert f["fork_id"].startswith("FORK-")
    assert f["status"] == "open"
    _cleanup(bridge, f["fork_id"])


def test_fork_join(bridge):
    f = fork_create(bridge, title="join test", created_by="hanuman", topic="test")
    result = fork_join(bridge, f["fork_id"], "kart")
    assert "kart" in result["participants"]
    _cleanup(bridge, f["fork_id"])


def test_fork_log(bridge):
    f = fork_create(bridge, title="log test", created_by="hanuman", topic="test")
    result = fork_log(bridge, f["fork_id"], "git", "branch", "session/2026-04-24-test")
    assert result["logged"] is True
    _cleanup(bridge, f["fork_id"])


def test_fork_merge(bridge):
    f = fork_create(bridge, title="merge test", created_by="hanuman", topic="test")
    result = fork_merge(bridge, f["fork_id"], outcome_note="test merge")
    assert result["merged"] is True
    status = fork_status(bridge, f["fork_id"])
    assert status["status"] == "merged"
    _cleanup(bridge, f["fork_id"])


def test_fork_delete(bridge):
    f = fork_create(bridge, title="delete test", created_by="hanuman", topic="test")
    result = fork_delete(bridge, f["fork_id"], reason="test cleanup")
    assert result["deleted"] is True
    status = fork_status(bridge, f["fork_id"])
    assert status["status"] == "deleted"
    _cleanup(bridge, f["fork_id"])


def test_fork_list_open(bridge):
    f = fork_create(bridge, title="list test", created_by="hanuman", topic="test")
    forks = fork_list(bridge, status="open")
    ids = [x["fork_id"] for x in forks]
    assert f["fork_id"] in ids
    _cleanup(bridge, f["fork_id"])


def test_fork_status_not_found(bridge):
    result = fork_status(bridge, "FORK-DOESNOTEXIST")
    assert result is None
