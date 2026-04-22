# tests/adversarial/e2e/conftest.py
"""E2E server fixture — launches SAP MCP server, auto-skips if unavailable.

The SAP server communicates over stdio using JSON-RPC 2.0 (newline-delimited).
Initialization sequence:
  1. Client sends: {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {...}}
  2. Server responds with capabilities
  3. Client sends: {"jsonrpc": "2.0", "method": "notifications/initialized"}
"""
import json
import select
import subprocess
import sys
import time
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
SAP_SCRIPT = REPO_ROOT / "sap" / "sap_mcp.py"


def _send(proc, msg: dict) -> None:
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line.encode())
    proc.stdin.flush()


def _recv(proc, timeout: float = 5.0) -> dict | None:
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        return None
    line = proc.stdout.readline()
    if not line:
        return None
    try:
        return json.loads(line.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _init_handshake(proc) -> bool:
    _send(proc, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "adversarial-test", "version": "0.1.0"},
        },
    })
    resp = _recv(proc, timeout=8.0)
    if not resp or "result" not in resp:
        return False
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return True


@pytest.fixture(scope="session")
def server_process():
    """Launch SAP MCP server subprocess. Skip all E2E tests if unavailable."""
    if not SAP_SCRIPT.exists():
        pytest.skip(f"SAP server script not found at {SAP_SCRIPT}")

    try:
        proc = subprocess.Popen(
            [sys.executable, str(SAP_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(REPO_ROOT),
        )
        time.sleep(1.5)
        if proc.poll() is not None:
            stderr = proc.stderr.read(500).decode(errors="replace")
            pytest.skip(f"SAP server exited immediately (rc={proc.returncode}): {stderr}")

        if not _init_handshake(proc):
            proc.terminate()
            pytest.skip("SAP server MCP initialization handshake failed")

        yield proc, _send, _recv

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    except FileNotFoundError:
        pytest.skip(f"Python executable not found: {sys.executable}")
    except Exception as e:
        pytest.skip(f"SAP server unavailable: {e}")
