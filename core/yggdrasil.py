"""core/yggdrasil.py — Local ollama wrapper for structured LLM responses.
b17: YGGW1  ΔΣ=42
"""
import json
import os
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
YGGDRASIL_MODEL = os.environ.get("WILLOW_YGGDRASIL_MODEL", "yggdrasil:v9")


def ask(prompt: str, timeout: int = 30) -> str | None:
    """Call local yggdrasil model. Returns stripped response or None on failure."""
    data = json.dumps({
        "model": YGGDRASIL_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            return result.get("message", {}).get("content", "").strip() or None
    except Exception:
        return None


def ask_structured(prompt: str, timeout: int = 30) -> dict:
    """Call yggdrasil expecting SUMMARY: <text> | IMPORTANCE: <1-10> format.

    Returns {"summary": str | None, "importance": int}.
    Falls back to first line of raw response if format not found.
    """
    raw = ask(prompt, timeout=timeout)
    if not raw:
        return {"summary": None, "importance": 5}

    summary, importance = None, 5
    for part in raw.replace("|", "\n").splitlines():
        part = part.strip()
        if part.upper().startswith("SUMMARY:"):
            summary = part.split(":", 1)[1].strip()
        elif part.upper().startswith("IMPORTANCE:"):
            try:
                importance = int(part.split(":", 1)[1].strip().split()[0])
            except (ValueError, IndexError):
                pass

    if not summary:
        lines = raw.strip().splitlines()
        summary = lines[0][:200] if lines else None

    return {"summary": summary, "importance": max(1, min(10, importance))}
