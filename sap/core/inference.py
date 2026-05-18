# b17: 91C1E  ΔΣ=42
"""
sap/core/inference.py
Credential loading and cloud/local inference backends for the Willow MCP server.

Hot-reloadable via willow_reload(target="inference") — all state is reconstructed
on import; no module-level I/O, no persistent connections.
"""
import json
import os
import pathlib
import urllib.request

# ── Cloud agent routing ────────────────────────────────────────────────────────

CLOUD_AGENTS: set[str] = {"ganas2"}
CLOUD_MODEL = "meta-llama/llama-3.1-8b-instruct"
CLOUD_URL   = "https://api.novita.ai/v3/openai/chat/completions"

OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openai/gpt-4o-mini"

CODEX_AGENTS: set[str] = {"ganas4"}
CODEX_MODEL = "claude-haiku-4-5-20251001"
CODEX_URL   = "https://api.anthropic.com/v1/messages"
CODEX_REPO  = __import__("os").environ.get("WILLOW_NEST_ROOT", str(__import__("pathlib").Path.home() / "github" / "willow-nest"))

# ── Image generation ───────────────────────────────────────────────────────────

NOVITA_IMG_MODEL = "revAnimated_v122.safetensors"
NOVITA_IMG_URL   = "https://api.novita.ai/v3/async/txt2img"
NOVITA_POLL_URL  = "https://api.novita.ai/v3/async/task-result"

ASPECT_TO_WH: dict[str, tuple[int, int]] = {
    "1:1": (512, 512), "16:9": (768, 432), "9:16": (432, 768),
    "4:3": (640, 480), "3:4": (480, 640),
}


# ── Credential loading ─────────────────────────────────────────────────────────

def load_credential(key: str) -> str | None:
    # Primary: Fernet vault (encrypted SQLite)
    try:
        from cryptography.fernet import Fernet
        import sqlite3 as _sqlite3
        _mk = pathlib.Path("~/.willow/secrets/.willow_master.key").expanduser().read_bytes().strip()
        _f  = Fernet(_mk)
        _db = _sqlite3.connect(str(pathlib.Path("~/.willow/secrets/.willow_creds.db").expanduser()))
        row = _db.execute("SELECT value_enc FROM credentials WHERE name=?", (key,)).fetchone()
        _db.close()
        if row:
            val = _f.decrypt(row[0]).decode()
            if val and "HERE" not in val:
                return val
    except Exception:
        pass
    # Fallback: credentials.json (plaintext)
    try:
        with open(os.path.expanduser("~/.willow/secrets/credentials.json")) as fh:
            val = json.load(fh).get(key)
            if val:
                return val
    except Exception:
        pass
    return os.environ.get(key)


# ── Chat backends ──────────────────────────────────────────────────────────────

def chat_groq(agent: str, message: str) -> str | None:
    try:
        api_key = load_credential("NOVITA_API_KEY")
        if not api_key:
            return None
        data = json.dumps({
            "model": CLOUD_MODEL,
            "messages": [
                {"role": "system", "content": (
                    f"You are {agent}, a fast cloud AI agent in Sean Campbell's fleet. "
                    "Be direct, concise, and honest."
                )},
                {"role": "user", "content": message},
            ],
            "temperature": 0.7,
        }).encode()
        req = urllib.request.Request(
            CLOUD_URL, data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception:
        return None


def chat_openrouter(agent: str, message: str) -> str | None:
    try:
        api_key = load_credential("OPENROUTER_API_KEY")
        if not api_key:
            return None
        data = json.dumps({
            "model": OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": (
                    f"You are {agent}, a fast cloud AI agent in Sean Campbell's fleet. "
                    "Be direct, concise, and honest."
                )},
                {"role": "user", "content": message},
            ],
            "temperature": 0.7,
        }).encode()
        req = urllib.request.Request(
            OPENROUTER_URL, data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://willow.local",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception:
        return None


def chat_codex(agent: str, message: str) -> str | None:
    try:
        api_key = load_credential("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        if agent in CODEX_AGENTS:
            system = (
                f"You are {agent}, a code-focused AI agent in Sean Campbell's fleet. "
                f"You have deep knowledge of the willow-nest repo at {CODEX_REPO}. "
                "You write clean, minimal Python. No fluff, no over-engineering."
            )
        else:
            system = (
                f"You are {agent}, an AI agent in Sean Campbell's sovereign fleet. "
                "You are the general coordinator — direct, honest, minimal. "
                "Answer clearly and concisely."
            )
        data = json.dumps({
            "model": CODEX_MODEL,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": message}],
        }).encode()
        req = urllib.request.Request(
            CODEX_URL, data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["content"][0]["text"]
    except Exception:
        return None


def chat_ollama(agent: str, message: str) -> str | None:
    try:
        data = json.dumps({
            "model": os.environ.get("WILLOW_OLLAMA_MODEL", "qwen2.5:3b"),
            "messages": [
                {"role": "system", "content": (
                    f"You are {agent}, a local AI coordinator for Sean Campbell's personal fleet. "
                    "You have access to a knowledge base, task queue, and agent network. "
                    "Be direct, concise, and honest. You run locally — no cloud, no external services. "
                    "When you don't know something, say so."
                )},
                {"role": "user", "content": message},
            ],
            "stream": True,
        }).encode()
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat"
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        chunks = []
        # Stream with a per-chunk timeout; CPU inference is ~5s/token so allow 300s total
        with urllib.request.urlopen(req, timeout=300) as resp:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        chunks.append(token)
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
        return "".join(chunks) if chunks else None
    except Exception:
        return None


# ── Image generation ───────────────────────────────────────────────────────────

def imagine_novita(prompt: str, output_path: str | None, aspect_ratio: str = "1:1") -> dict:
    try:
        import datetime
        import time
        api_key = load_credential("NOVITA_API_KEY")
        if not api_key:
            return {"error": "NOVITA_API_KEY not found in credentials"}
        w, h = ASPECT_TO_WH.get(aspect_ratio, (512, 512))
        data = json.dumps({
            "extra": {"response_image_type": "png"},
            "request": {
                "model_name": NOVITA_IMG_MODEL,
                "prompt": prompt,
                "width": w, "height": h,
                "image_num": 1, "steps": 20,
                "guidance_scale": 7.0,
                "sampler_name": "Euler a",
            }
        }).encode()
        req = urllib.request.Request(
            NOVITA_IMG_URL, data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            task_id = json.loads(r.read()).get("task_id")
        if not task_id:
            return {"error": "No task_id returned from Novita"}
        for _ in range(40):
            time.sleep(3)
            poll = urllib.request.Request(
                f"{NOVITA_POLL_URL}?task_id={task_id}",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            with urllib.request.urlopen(poll, timeout=10) as r:
                result = json.loads(r.read())
            status = result.get("task", {}).get("status", "")
            if "SUCCEED" in status:
                img_url = result["images"][0]["image_url"]
                with urllib.request.urlopen(urllib.request.Request(img_url), timeout=15) as ir:
                    img_bytes = ir.read()
                if output_path:
                    save_path = pathlib.Path(output_path).expanduser()
                else:
                    out_dir = pathlib.Path.home() / "Pictures" / "willow-gen"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_path = out_dir / f"willow_gen_{ts}.png"
                save_path.write_bytes(img_bytes)
                return {"path": str(save_path), "prompt": prompt, "aspect_ratio": aspect_ratio}
            elif "FAILED" in status or "ERROR" in status:
                return {"error": f"Novita task failed: {status}"}
        return {"error": "Novita image generation timed out"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
