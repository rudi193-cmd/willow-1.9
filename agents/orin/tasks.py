"""
agents/orin/tasks.py — Task type handlers for the orin (mistral:7b) sub-agent.

Each handler receives plain-text content and returns a structured dict.
All JSON parsing is best-effort: falls back to raw text on parse failure.

Task types:
  summarize  — bullet-point summary of atoms/documents
  classify   — assign text to one of a given category list
  extract    — pull KB-ready atoms out of a document
  tension    — detect contradiction between two atom summaries
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("orin.tasks")

MODEL = "mistral:7b"


# ── JSON extraction helpers ───────────────────────────────────────────────────

def _parse_json(text: str) -> dict | list | None:
    """Try json.loads on full response, then on first JSON block found."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = re.search(r"(\{[\s\S]+\}|\[[\s\S]+\])", text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


# ── Task handlers ─────────────────────────────────────────────────────────────

def summarize(content: str, context: str = "") -> dict:
    """Return a bullet-point summary and a one-line abstract."""
    from sap.clients.professor_client import _ask_ollama
    system = (
        "You are a concise knowledge summarizer. "
        "Respond ONLY with valid JSON, no prose before or after. "
        'Format: {"bullets": ["...", "..."], "one_line": "..."}'
    )
    user = f"Summarize the following into 3-5 key bullet points:\n\n{content}"
    if context:
        user = f"Context:\n{context}\n\n{user}"
    raw = _ask_ollama(MODEL, system, user) or ""
    parsed = _parse_json(raw)
    if isinstance(parsed, dict) and "bullets" in parsed:
        return {"task": "summarize", "result": parsed, "raw": raw}
    bullets = [line.lstrip("-•* ").strip()
               for line in raw.splitlines() if line.strip().startswith(("-", "•", "*", "-"))]
    return {"task": "summarize",
            "result": {"bullets": bullets or [raw[:300]], "one_line": raw.split("\n")[0][:120]},
            "raw": raw}


def classify(content: str, categories: list[str], context: str = "") -> dict:
    """Assign content to one of the provided categories with a confidence score."""
    from sap.clients.professor_client import _ask_ollama
    cats = ", ".join(f'"{c}"' for c in categories)
    system = (
        "You are a precise classifier. "
        "Respond ONLY with valid JSON, no prose. "
        f'Format: {{"category": <one of [{cats}]>, "confidence": <0.0-1.0>, "reason": "..."}}'
    )
    user = f"Classify the following text.\nCategories: [{cats}]\n\nText:\n{content}"
    if context:
        user = f"Context:\n{context}\n\n{user}"
    raw = _ask_ollama(MODEL, system, user) or ""
    parsed = _parse_json(raw)
    if isinstance(parsed, dict) and "category" in parsed:
        return {"task": "classify", "result": parsed, "raw": raw}
    # Fallback: find a mentioned category
    for cat in categories:
        if cat.lower() in raw.lower():
            return {"task": "classify",
                    "result": {"category": cat, "confidence": 0.5, "reason": raw[:200]},
                    "raw": raw}
    return {"task": "classify",
            "result": {"category": categories[0] if categories else "unknown",
                       "confidence": 0.1, "reason": "parse_failed"},
            "raw": raw, "parse_error": True}


def extract(content: str, context: str = "") -> dict:
    """Extract KB-ready atoms from a document. Returns list of {title, summary, category}."""
    from sap.clients.professor_client import _ask_ollama
    system = (
        "You are a knowledge extraction engine. "
        "Extract factual, self-contained knowledge atoms from the provided text. "
        "Respond ONLY with a valid JSON array, no prose. "
        'Each element: {"title": "...", "summary": "...", "category": "general|code|governance|architecture"}'
    )
    user = (
        "Extract up to 5 knowledge atoms from the following. "
        "Each atom must be self-contained and factual:\n\n"
        f"{content[:4000]}"
    )
    if context:
        user = f"Context:\n{context}\n\n{user}"
    raw = _ask_ollama(MODEL, system, user) or ""
    parsed = _parse_json(raw)
    atoms = []
    if isinstance(parsed, list):
        atoms = [a for a in parsed if isinstance(a, dict) and "title" in a and "summary" in a]
    elif isinstance(parsed, dict) and "atoms" in parsed:
        atoms = parsed["atoms"]
    return {"task": "extract", "result": {"atoms": atoms, "count": len(atoms)}, "raw": raw}


def tension(atom_a: str, atom_b: str) -> dict:
    """Detect contradiction between two atom summaries."""
    from sap.clients.professor_client import _ask_ollama
    system = (
        "You detect logical contradictions between knowledge claims. "
        "Respond ONLY with valid JSON, no prose. "
        'Format: {"conflict": true|false, "score": <0.0-1.0>, "reason": "..."}'
    )
    user = (
        f"Do these two claims contradict each other?\n\n"
        f"Claim A: {atom_a}\n\n"
        f"Claim B: {atom_b}"
    )
    raw = _ask_ollama(MODEL, system, user) or ""
    parsed = _parse_json(raw)
    if isinstance(parsed, dict) and "conflict" in parsed:
        return {"task": "tension", "result": parsed, "raw": raw}
    conflict_hint = any(w in raw.lower() for w in ("contradict", "conflict", "inconsistent", "opposite"))
    return {"task": "tension",
            "result": {"conflict": conflict_hint, "score": 0.5, "reason": raw[:300]},
            "raw": raw, "parse_error": True}


# ── Dispatcher ────────────────────────────────────────────────────────────────

HANDLERS = {
    "summarize": lambda payload: summarize(
        payload.get("content", ""), payload.get("context", "")
    ),
    "classify": lambda payload: classify(
        payload.get("content", ""),
        payload.get("categories", ["general"]),
        payload.get("context", ""),
    ),
    "extract": lambda payload: extract(
        payload.get("content", ""), payload.get("context", "")
    ),
    "tension": lambda payload: tension(
        payload.get("atom_a", ""), payload.get("atom_b", "")
    ),
}


def run(task_type: str, payload: dict) -> dict:
    """Dispatch to the right handler. Returns result dict with task_type key."""
    handler = HANDLERS.get(task_type)
    if not handler:
        return {"error": f"unknown task_type: {task_type!r}",
                "valid": list(HANDLERS)}
    try:
        return handler(payload)
    except Exception as e:
        logger.exception("orin task %s failed", task_type)
        return {"error": str(e), "task": task_type}
