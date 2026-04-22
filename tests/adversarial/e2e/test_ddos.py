# tests/adversarial/e2e/test_ddos.py
"""DDoS simulation — Gleipnir must stop runaway agents at the wire.

Sends tool calls over the live MCP stdio channel and verifies that:
  1. Sequential floods of 70+ calls trigger the hard limit (deny responses)
  2. The server process survives a flood (stays alive, keeps responding)

The recovery test (waiting 60s for window reset) is marked manual-only.
"""
import pytest


def _tool_call(send, recv, proc, call_id: int, app_id: str = "ddos_test_app") -> dict | None:
    send(proc, {
        "jsonrpc": "2.0",
        "id": call_id,
        "method": "tools/call",
        "params": {
            "name": "store_list",
            "arguments": {"app_id": app_id, "collection": "adv/test"},
        },
    })
    return recv(proc, timeout=8.0)


def _response_text(resp: dict | None) -> str:
    if not resp:
        return ""
    content = resp.get("result", {}).get("content", [])
    return content[0].get("text", "") if content else ""


def test_sequential_flood_triggers_hard_limit(server_process):
    """70 sequential calls must produce at least one denial from Gleipnir.
    Gleipnir default: soft=30, hard=60, window=60s.
    Calls 1-30: allowed no warning. Calls 31-60: allowed with warning. Call 61+: denied.
    """
    proc, send, recv = server_process
    denied = 0
    for i in range(70):
        resp = _tool_call(send, recv, proc, call_id=100 + i)
        text = _response_text(resp)
        if "Rate limit exceeded" in text or "Gleipnir holds" in text:
            denied += 1
    assert denied >= 1, (
        f"Expected Gleipnir to deny at least 1 call after 60, got 0 denials in 70 calls. "
        f"Check that Gleipnir is wired into sap_mcp.py tool dispatch."
    )


def test_server_survives_sequential_flood(server_process):
    """After 70 rapid-fire calls, the server process must still be alive and responding."""
    proc, send, recv = server_process
    for i in range(70):
        _tool_call(send, recv, proc, call_id=200 + i)
    assert proc.poll() is None, "Server process died during flood"
    # Confirm server still responds
    resp = _tool_call(send, recv, proc, call_id=999, app_id="post_flood_check_app")
    assert resp is not None, "Server did not respond after flood"


@pytest.mark.skip(reason="Requires waiting 60s for Gleipnir window reset — run manually with: pytest -k test_recovery -s")
def test_recovery_after_window(server_process):
    """After window expires (60s), calls from the flooded app_id are allowed again."""
    import time
    proc, send, recv = server_process
    for i in range(65):
        _tool_call(send, recv, proc, call_id=300 + i)
    time.sleep(62)  # wait for 60s window to expire
    resp = _tool_call(send, recv, proc, call_id=400, app_id="ddos_test_app")
    text = _response_text(resp)
    assert "Rate limit exceeded" not in text
    assert "Gleipnir holds" not in text
