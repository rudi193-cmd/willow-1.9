"""tests/test_grove_coordination.py"""
import pytest
from core.willow_store import WillowStore
from willow.grove_coordination import (
    outbox_queue, outbox_drain, node_announce, node_list, alert_pending
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path))
    return WillowStore()


def test_outbox_queue_and_drain(store):
    msg_id = outbox_queue(store, "felix@laptop:8550", "ALERT", {"type": "test"})
    assert msg_id
    msgs = outbox_drain(store, "felix@laptop:8550")
    assert len(msgs) == 1
    assert msgs[0]["type"] == "ALERT"
    # Second drain returns nothing (already delivered)
    assert outbox_drain(store, "felix@laptop:8550") == []


def test_node_announce_and_list(store):
    node_announce(store, "felix@laptop:8550", "Felix", "1.9.0")
    nodes = node_list(store)
    addrs = [n["addr"] for n in nodes]
    assert "felix@laptop:8550" in addrs


def test_node_has_2_0_stub(store):
    node_announce(store, "test@host:8550", "Test", "1.9.0")
    nodes = node_list(store)
    node = next(n for n in nodes if n["addr"] == "test@host:8550")
    assert "2.0_stub" in node
    assert node["2.0_stub"]["hns_opt_in"] is None
