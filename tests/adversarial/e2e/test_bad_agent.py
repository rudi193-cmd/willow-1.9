# tests/adversarial/e2e/test_bad_agent.py
"""Bad agent behavior — missing app_id, empty app_id, malformed JSON-RPC.

After each bad call, a valid call is sent to confirm the server has not
entered an error state or crashed (no state corruption).
"""
import pytest


def _call(send, recv, proc, call_id: int, params: dict) -> dict | None:
    send(proc, {"jsonrpc": "2.0", "id": call_id, "method": "tools/call", "params": params})
    return recv(proc, timeout=8.0)


def _alive_check(send, recv, proc, call_id: int) -> bool:
    """Send a valid call and verify server responds."""
    if proc.poll() is not None:
        return False
    resp = _call(send, recv, proc, call_id, {
        "name": "store_list",
        "arguments": {"app_id": "recovery_check_app", "collection": "adv/test"},
    })
    return resp is not None and "id" in resp and resp["id"] == call_id


def test_missing_app_id(server_process):
    """Tool call with no app_id parameter — server must respond (not crash)."""
    proc, send, recv = server_process
    resp = _call(send, recv, proc, 400, {
        "name": "store_list",
        "arguments": {"collection": "adv/test"},  # app_id omitted
    })
    assert resp is not None, "Server did not respond to missing app_id call"
    assert proc.poll() is None, "Server crashed on missing app_id"
    assert _alive_check(send, recv, proc, 401)


def test_empty_app_id(server_process):
    """Tool call with app_id='' — server must respond (not crash)."""
    proc, send, recv = server_process
    resp = _call(send, recv, proc, 410, {
        "name": "store_list",
        "arguments": {"app_id": "", "collection": "adv/test"},
    })
    assert resp is not None
    assert proc.poll() is None, "Server crashed on empty app_id"
    assert _alive_check(send, recv, proc, 411)


def test_malformed_json_rpc(server_process):
    """Raw garbage on stdin — server must survive (not crash, not deadlock)."""
    proc, send, recv = server_process
    proc.stdin.write(b"{ this is not valid json at all !!!\n")
    proc.stdin.flush()
    # Server may or may not respond to garbage — what matters is it stays alive
    _ = recv(proc, timeout=3.0)
    assert proc.poll() is None, "Server crashed on malformed JSON-RPC input"
    assert _alive_check(send, recv, proc, 421)


def test_valid_call_after_bad_calls(server_process):
    """A clean call after all the bad ones must succeed — no state corruption."""
    proc, send, recv = server_process
    resp = _call(send, recv, proc, 500, {
        "name": "store_list",
        "arguments": {"app_id": "clean_agent_app", "collection": "adv/test"},
    })
    assert resp is not None
    assert resp.get("id") == 500, f"Response id mismatch: {resp}"
    assert proc.poll() is None
