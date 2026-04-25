#!/usr/bin/env python3
"""
grove_serve.py — Willow Grove command server. b17: GRSV1 ΔΣ=42

Listens on LAN for signed command requests from trusted Willow nodes.
No third-party services. No Discord. Just your network.

Usage:
    python3 -m core.grove_serve [--port 7777] [--host 0.0.0.0]

Auth: HMAC-SHA256 of the request body, signed with the shared grove token.
Token lives at ~/.willow/grove_token (generated on first run, share with
trusted nodes via `willow grove pair`).
"""
import hashlib
import hmac
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

# Ensure willow-1.9 root is on path when invoked via -m
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_PORT = int(os.environ.get("WILLOW_GROVE_PORT", "7777"))
WILLOW_ROOT  = Path(os.environ.get("WILLOW_ROOT", Path(__file__).parent.parent))
TOKEN_PATH   = Path.home() / ".willow" / "grove_token"

# Commands the serve endpoint will run. Allowlist — nothing else executes.
ALLOWED_COMMANDS = {
    "logs",
    "status",
    "status-all",
    "health",
    "health daily",
    "health weekly",
    "providers list",
    "sentinel",
    "ledger",
    "version",
    "whoami",
}


def load_or_create_token() -> str:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    token = secrets.token_hex(32)
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token + "\n")
    TOKEN_PATH.chmod(0o600)
    print(f"[grove-serve] Generated grove token → {TOKEN_PATH}", flush=True)
    print(f"[grove-serve] Share this token with trusted nodes:", flush=True)
    print(f"  {token}", flush=True)
    return token


_TOKEN: str = ""


def _valid_sig(body: bytes, sig: str) -> bool:
    expected = hmac.new(_TOKEN.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _run_command(cmd: str) -> tuple[str, int]:
    """Run a willow.sh subcommand and return (output, exit_code)."""
    willow_sh = WILLOW_ROOT / "willow.sh"
    parts = cmd.strip().split()

    # Validate against allowlist
    cmd_key = " ".join(parts[:2]) if len(parts) > 1 else parts[0]
    if cmd_key not in ALLOWED_COMMANDS and parts[0] not in ALLOWED_COMMANDS:
        return f"Command not allowed: {cmd}", 403

    try:
        result = subprocess.run(
            ["bash", str(willow_sh)] + parts,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "WILLOW_ROOT": str(WILLOW_ROOT)},
        )
        output = result.stdout + result.stderr
        return output.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "Command timed out (30s)", 1
    except Exception as e:
        return f"Error: {e}", 1


class GroveHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[grove-serve] {self.address_string()} {fmt % args}", flush=True)

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "grove-serve"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/command":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        sig  = self.headers.get("X-Grove-Sig", "")

        if not _valid_sig(body, sig):
            self._send_json(401, {"error": "invalid signature"})
            return

        try:
            payload = json.loads(body)
            cmd = payload.get("cmd", "").strip()
        except Exception:
            self._send_json(400, {"error": "invalid JSON"})
            return

        if not cmd:
            self._send_json(400, {"error": "cmd is required"})
            return

        output, exit_code = _run_command(cmd)
        self._send_json(200, {"output": output, "exit_code": exit_code, "cmd": cmd})


def serve(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
    global _TOKEN
    _TOKEN = load_or_create_token()

    server = http.server.HTTPServer((host, port), GroveHandler)
    print(f"[grove-serve] Listening on {host}:{port}", flush=True)
    print(f"[grove-serve] Token: {TOKEN_PATH}", flush=True)
    print(f"[grove-serve] Allowed commands: {sorted(ALLOWED_COMMANDS)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[grove-serve] Stopped.", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Willow Grove command server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    serve(args.host, args.port)
