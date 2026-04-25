# willow/skills.py — Willow Skills registry. b17: SKLS1  ΔΣ=42
from __future__ import annotations
from core.willow_store import WillowStore

_COLLECTION = "willow/skills"


def skill_put(
    store: WillowStore,
    name: str,
    domain: str,
    content: str,
    trigger: str,
    auto_load: bool = True,
    model_agnostic: bool = True,
) -> str:
    """Store or update a skill. Returns skill ID (= name)."""
    store.put(_COLLECTION, {
        "id": name,
        "name": name,
        "domain": domain,
        "content": content,
        "trigger": trigger,
        "auto_load": auto_load,
        "model_agnostic": model_agnostic,
    })
    return name


def skill_load(
    store: WillowStore,
    context: str,
    max_skills: int = 3,
) -> list[dict]:
    """Return up to max_skills auto-loadable skills relevant to context."""
    all_skills = store.list(_COLLECTION)
    context_words = set(context.lower().split())

    scored = []
    for record in all_skills:
        data = record.get("data", record)
        if not data.get("auto_load", False):
            continue
        trigger_words = set(data.get("trigger", "").lower().split())
        score = len(context_words & trigger_words)
        if score > 0:
            scored.append((score, data))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:max_skills]]


def skill_list(
    store: WillowStore,
    domain: str | None = None,
) -> list[dict]:
    """List all skills, optionally filtered by domain."""
    all_skills = store.list(_COLLECTION)
    result = []
    for record in all_skills:
        data = record.get("data", record)
        if domain and data.get("domain") != domain:
            continue
        result.append(data)
    return result
