import core.willow_store as ws


def _make_store(tmp_path):
    return ws.WillowStore(root=str(tmp_path))


def test_put_writes_hebbian_edge_for_same_domain(tmp_path):
    store = _make_store(tmp_path)
    store.put("hanuman/atoms/store", {
        "id": "existing-a1",
        "type": "reflection",
        "domain": "pg_bridge",
    })
    store.put("hanuman/atoms/store", {
        "id": "new-a2",
        "type": "reflection",
        "domain": "pg_bridge",
    })
    edges = store.list("hanuman/atoms/edges")
    assert any(
        e.get("source_id") in ("existing-a1", "new-a2")
        for e in edges
    )


def test_put_no_edge_for_different_domain(tmp_path):
    store = _make_store(tmp_path)
    store.put("hanuman/atoms/store", {
        "id": "a1", "type": "reflection", "domain": "pg_bridge",
    })
    store.put("hanuman/atoms/store", {
        "id": "a2", "type": "reflection", "domain": "willow_store",
    })
    edges = store.list("hanuman/atoms/edges")
    assert len(edges) == 0


def test_put_no_edge_for_non_atom_collection(tmp_path):
    store = _make_store(tmp_path)
    store.put("hanuman/sessions/store", {
        "id": "s1", "domain": "pg_bridge",
    })
    store.put("hanuman/sessions/store", {
        "id": "s2", "domain": "pg_bridge",
    })
    edges = store.list("hanuman/atoms/edges")
    assert len(edges) == 0


def test_increment_edge_weight(tmp_path):
    store = _make_store(tmp_path)
    store.put("hanuman/atoms/edges", {
        "id": "edge-a1-a2",
        "source_id": "a1",
        "target_id": "a2",
        "weight": 0.1,
        "co_activations": 0,
    })
    store._increment_edge_weight("a1", "a2")
    edges = store.list("hanuman/atoms/edges")
    edge = next((e for e in edges if e.get("id") == "edge-a1-a2"), None)
    assert edge is not None
    assert edge["weight"] > 0.1
    assert edge["co_activations"] == 1


def test_increment_edge_weight_bidirectional(tmp_path):
    store = _make_store(tmp_path)
    store.put("hanuman/atoms/edges", {
        "id": "edge-b1-b2",
        "source_id": "b1",
        "target_id": "b2",
        "weight": 0.1,
        "co_activations": 0,
    })
    # Increment with reversed order — should still find the edge
    store._increment_edge_weight("b2", "b1")
    edges = store.list("hanuman/atoms/edges")
    edge = next((e for e in edges if e.get("id") == "edge-b1-b2"), None)
    assert edge is not None
    assert edge["co_activations"] == 1
