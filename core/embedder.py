# core/embedder.py
import requests

OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "nomic-embed-text"
TIMEOUT_S = 60


def embed(text: str) -> list[float] | None:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": text},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception:
        return None
