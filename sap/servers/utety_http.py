#!/usr/bin/env python3
"""
UTETY HTTP Server — port 8421
b17: 5AAN9
ΔΣ=42

Thin HTTP shim that serves the UTETY chat interface locally.
No Cloudflare. No API keys. No cloud dependency.

Endpoints:
  GET  /                       → serve safe-app-utety-chat/web/index.html
  GET  /chat.html?professor=X  → serve chat.html
  GET  /static/*               → serve static assets
  POST /api/chat-direct        → route to Ollama (yggdrasil or fallback)
  POST /api/session/start      → return a local session ID

Usage:
  python3 -m sap.servers.utety_http
  # or
  python3 /path/to/sap/servers/utety_http.py

Port 8421 is the UTETY server. Port 8420 is the Willow server (auth/fleet).
"""

import json
import logging
import os
import random
import string
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [utety] %(message)s")
logger = logging.getLogger("utety_http")

PORT = int(os.environ.get("UTETY_HTTP_PORT", "8421"))
UTETY_WEB = Path(os.environ.get(
    "UTETY_WEB_ROOT",
    str(Path(__file__).parent.parent.parent.parent / "safe-app-utety-chat" / "web"),
))
DEFAULT_MODEL = os.environ.get("UTETY_MODEL", "yggdrasil:v9")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _ask_ollama(system_prompt: str, user_message: str, history: list) -> Optional[str]:
    """Call Ollama with the professor's system prompt."""
    messages = [{"role": "system", "content": system_prompt}]
    for h in (history or [])[-12:]:
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    try:
        import urllib.request
        payload = json.dumps({
            "model": DEFAULT_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"num_thread": 4},
        }).encode()
        req = urllib.request.Request(
            OLLAMA_HOST + "/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("message", {}).get("content", "")
    except Exception as e:
        logger.warning("Ollama failed (%s) — trying fleet", e)
        return _ask_fleet(system_prompt, user_message)


def _ask_fleet(system_prompt: str, user_message: str) -> Optional[str]:
    """Fallback to free fleet (Groq/Cerebras/SambaNova) via credentials.json."""
    creds_path = Path(__file__).parent.parent.parent / "credentials.json"
    try:
        creds = json.loads(creds_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    import urllib.request as _ur

    endpoints = [
        ("GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant"),
        ("GROQ_API_KEY_2", "https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant"),
        ("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/chat/completions", "llama3.1-8b"),
    ]
    for key_name, url, model in endpoints:
        key = creds.get(key_name, "")
        if not key:
            continue
        try:
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": 2048,
            }).encode()
            req = _ur.Request(
                url, data=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            with _ur.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                content = data["choices"][0]["message"]["content"]
                logger.info("Fleet response via %s / %s", key_name, model)
                return content
        except Exception as e:
            logger.warning("Fleet %s failed: %s", key_name, e)
            continue
    return None


def _serve_file(handler, path: Path, content_type: str = "text/html; charset=utf-8"):
    """Send a static file response."""
    try:
        data = path.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(data)
    except FileNotFoundError:
        handler.send_response(404)
        handler.end_headers()
        handler.wfile.write(b"Not found")


MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".ttf": "font/ttf",
    ".woff2": "font/woff2",
}


class UTETYHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logger.info(fmt, *args)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/" or path == "/index.html":
            _serve_file(self, UTETY_WEB / "index.html")
            return

        # Strip leading slash and resolve to web root
        rel = path.lstrip("/")
        target = UTETY_WEB / rel
        if target.is_file():
            ext = target.suffix.lower()
            mime = MIME.get(ext, "application/octet-stream")
            _serve_file(self, target, mime)
            return

        # 404
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if path == "/api/chat-direct":
            self._handle_chat_direct(data)
        elif path == "/api/session/start":
            self._handle_session_start()
        elif path.startswith("/api/chat/"):
            # /api/chat/{sessionId}/{professor}
            parts = path.split("/")
            professor = parts[-1] if len(parts) >= 4 else "Willow"
            self._handle_utety_chat(professor, data)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')

    def _handle_chat_direct(self, data: dict):
        message = data.get("message", "")
        persona = data.get("persona", "You are a UTETY professor.")
        history = data.get("history", [])

        if not message:
            self._json(400, {"error": "message required"})
            return

        logger.info("chat-direct: %s...", message[:60])
        response = _ask_ollama(persona, message, history)
        if response:
            self._json(200, {"response": response})
        else:
            self._json(503, {"error": "All LLM providers unavailable"})

    def _handle_session_start(self):
        session_id = "local-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        self._json(200, {"session_id": session_id})

    def _handle_utety_chat(self, professor: str, data: dict):
        message = data.get("content", data.get("message", ""))
        if not message:
            self._json(400, {"error": "content required"})
            return
        persona = f"You are Professor {professor} of UTETY. Respond in character."
        response = _ask_ollama(persona, message, [])
        if response:
            self._json(200, {"response": response, "professor": professor})
        else:
            self._json(503, {"error": "LLM unavailable"})

    def _json(self, code: int, obj: dict):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)


def main():
    if not UTETY_WEB.exists():
        logger.error("UTETY web root not found: %s", UTETY_WEB)
        logger.error("Set UTETY_WEB_ROOT or clone safe-app-utety-chat alongside willow-1.9")
        sys.exit(1)

    logger.info("UTETY HTTP server starting on port %d", PORT)
    logger.info("Web root: %s", UTETY_WEB)
    logger.info("Model: %s @ %s", DEFAULT_MODEL, OLLAMA_HOST)
    logger.info("Open: http://localhost:%d", PORT)

    server = HTTPServer(("127.0.0.1", PORT), UTETYHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown")


if __name__ == "__main__":
    main()
