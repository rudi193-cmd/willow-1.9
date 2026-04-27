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


def test_compute_affect_call_failure_returns_neutral():
    def fake_call(tool, args, timeout=5):
        raise RuntimeError("mcp down")
    with patch("willow.fylgja.events.stop.call", fake_call):
        result = stop_mod._compute_affect("sess-001")
    assert result == "neutral"
