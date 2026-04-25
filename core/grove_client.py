#!/usr/bin/env python3
"""
grove_client.py — Send a signed command to a remote Willow Grove server.
b17: GRCL1 ΔΣ=42

Usage:
    python3 -m core.grove_client <host:port> <command> [--token path]

Examples:
    python3 -m core.grove_client 192.168.12.189:7777 "status-all"
    python3 -m core.grove_client 192.168.12.189:7777 "health daily"
"""
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TOKEN_PATH = Path.home() / ".willow" / "grove_token"


def load_token(path: Path = TOKEN_PATH) -> str:
    if not path.exists():
        print(f"Error: no grove token at {path}", file=sys.stderr)
        print("Run 'willow grove pair' to set up a token, or copy the token from the server.", file=sys.stderr)
        sys.exit(1)
    return path.read_text().strip()


def sign(body: bytes, token: str) -> str:
    return hmac.new(token.encode(), body, hashlib.sha256).hexdigest()


def send_command(host_port: str, cmd: str, token: str, timeout: int = 30) -> dict:
    if not host_port.startswith("http"):
        host_port = f"http://{host_port}"
    url = f"{host_port.rstrip('/')}/command"

    payload = json.dumps({"cmd": cmd}).encode()
    sig = sign(payload, token)

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type":  "application/json",
            "X-Grove-Sig":   sig,
            "Content-Length": str(len(payload)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except Exception:
            return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <host:port> <command>")
        sys.exit(1)

    host_port = sys.argv[1]
    cmd = " ".join(sys.argv[2:])
    token = load_token()

    result = send_command(host_port, cmd, token)

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(result.get("output", ""))
    sys.exit(result.get("exit_code", 0))


if __name__ == "__main__":
    main()
