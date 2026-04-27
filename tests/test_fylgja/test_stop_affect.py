from unittest.mock import patch
import willow.fylgja.events.stop as stop_mod


FRICTION_TRACES = [
    {"session_id": "sess-001", "tool": "Edit", "target": "/foo/bar.py", "summary": "edit 1"},
    {"session_id": "sess-001", "tool": "Edit", "target": "/foo/bar.py", "summary": "edit 2"},
    {"session_id": "sess-001", "tool": "Edit", "target": "/foo/bar.py", "summary": "edit 3"},
]
CLEAN_TRACES = [
    {"session_id": "sess-002", "tool": "Edit", "target": "/foo/bar.py", "summary": "edit"},
    {"session_id": "sess-002", "tool": "Write", "target": "/foo/baz.py", "summary": "write"},
]


def test_compute_affect_friction():
    def fake_call(tool, args, timeout=5):
        return FRICTION_TRACES
    with patch("willow.fylgja.events.stop.call", fake_call):
        result = stop_mod._compute_affect("sess-001")
    assert result == "friction"


def test_compute_affect_clean():
    def fake_call(tool, args, timeout=5):
        return CLEAN_TRACES
    with patch("willow.fylgja.events.stop.call", fake_call):
        result = stop_mod._compute_affect("sess-002")
    assert result == "clean"


def test_compute_affect_no_traces():
    def fake_call(tool, args, timeout=5):
        return []
    with patch("willow.fylgja.events.stop.call", fake_call):
        result = stop_mod._compute_affect("sess-003")
    assert result == "neutral"


def test_write_failure_atom_calls_store_put():
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {"ok": True}
    with patch("willow.fylgja.events.stop.call", fake_call):
        stop_mod._write_failure_atom("sess-001", FRICTION_TRACES)
    assert any(t == "store_put" for t, _ in calls)
    record = next(a["record"] for t, a in calls if t == "store_put")
    assert record["type"] == "failure"
    assert record["session_id"] == "sess-001"
    assert record["resolved"] is False


def test_write_reflection_atom_friction_calls_yggdrasil():
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {"ok": True}
    def fake_ygg(prompt, timeout=4):
        return {"summary": "Don't reuse the same file path twice.", "importance": 7}

    with patch("willow.fylgja.events.stop.call", fake_call), \
         patch("willow.fylgja.events.stop._ygg_structured", fake_ygg):
        stop_mod._write_reflection_atom("sess-001", "friction", FRICTION_TRACES)

    store_puts = [(t, a) for t, a in calls if t == "store_put"]
    assert len(store_puts) == 1
    record = store_puts[0][1]["record"]
    assert record["type"] == "reflection"
    assert record["importance"] == 7
    assert "next_review" in record


def test_write_reflection_atom_clean_writes_pending():
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {"ok": True}

    with patch("willow.fylgja.events.stop.call", fake_call):
        stop_mod._write_reflection_atom("sess-002", "clean", CLEAN_TRACES)

    store_puts = [(t, a) for t, a in calls if t == "store_put"]
    assert len(store_puts) == 1
    assert store_puts[0][1]["record"]["type"] == "reflection_pending"


def test_write_reflection_atom_friction_degrades_on_ygg_failure():
    calls = []
    def fake_call(tool, args, timeout=5):
        calls.append((tool, args))
        return {"ok": True}
    def fake_ygg(prompt, timeout=4):
        return {"summary": None, "importance": 0}

    with patch("willow.fylgja.events.stop.call", fake_call), \
         patch("willow.fylgja.events.stop._ygg_structured", fake_ygg):
        stop_mod._write_reflection_atom("sess-001", "friction", FRICTION_TRACES)

    store_puts = [(t, a) for t, a in calls if t == "store_put"]
    assert len(store_puts) == 1
    assert store_puts[0][1]["record"]["type"] == "reflection_pending"


def test_compute_affect_call_failure_returns_neutral():
    def fake_call(tool, args, timeout=5):
        raise RuntimeError("mcp down")
    with patch("willow.fylgja.events.stop.call", fake_call):
        result = stop_mod._compute_affect("sess-001")
    assert result == "neutral"
