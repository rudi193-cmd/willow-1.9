"""
SAP Professor Client — The Conf Call Wire
b17: NL619
ΔΣ=42

Replaces the Pigeon HTTP bus for professor invocations with a direct
portless SAP call. No HTTP server required. No exposed port.

Previously:
    chat_engine.py → Pigeon drop → http://localhost:8420 → Willow → LLM

Now (SAP path):
    professor_client.py → gate.authorized("UTETY") → context.assemble() → Ollama direct

Usage:

    from sap.clients.professor_client import ProfessorClient

    # Single professor
    client = ProfessorClient("Oakenscroll")
    response = client.ask("What does ΔΣ=42 mean?")

    # Conf call — multiple professors on one topic
    from sap.clients.professor_client import conf_call
    responses = conf_call(["Oakenscroll", "Riggs", "Consus"], "Is ΔE=0 achievable?")
"""

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

from sap.core.gate import authorized
from sap.core.context import assemble
from sap.core.deliver import to_string

logger = logging.getLogger("sap.clients.professor")

# Canonical paths
UTETY_APP_ID = "utety-chat"  # matches SAFE/Applications/utety-chat/
UTETY_CHAT_ROOT = Path(os.environ.get(
    "WILLOW_UTETY_ROOT",
    str(Path(__file__).parent.parent.parent.parent / "safe-app-utety-chat"),
))
PERSONAS_PATH = UTETY_CHAT_ROOT / "personas.py"
PROFESSOR_DATA_ROOT = UTETY_CHAT_ROOT / "data" / "professors"

DEFAULT_MODEL = "qwen2.5:3b"

# KB categories each professor draws from.
PROFESSOR_DOMAINS: dict[str, list[str]] = {
    "Oakenscroll": ["governance", "architecture", "analysis", "core", "code"],
    "Riggs":       ["architecture", "code", "system-state", "analysis"],
    "Hanz":        ["code", "training", "document", "conversation"],
    "Nova":        ["narrative", "analysis", "user_cognition"],
    "Ada":         ["architecture", "system-state", "governance", "core"],
    "Jeles":       ["genealogy", "reference", "documents", "general"],
    "Alexis":      ["personal", "general"],
    "Ofshield":    ["personal", "user_cognition", "narrative"],
    "Shiva":       ["architecture", "system-state", "code", "core", "governance"],
    "Gerald":      ["governance", "general"],
    "Pigeon":      ["architecture", "system-state"],
    "Binder":      ["reference", "genealogy", "general"],
    "Mitra":       ["general"],
    "Consus":      ["governance", "architecture"],
    "Jane":        ["general", "narrative"],
    "Steve":       ["general"],
    "Willow":      [],  # Willow IS the campus — no domain filter, no skip_cache
    "Kart":        ["architecture", "system-state", "code"],
}

# Professors with their own SAFE Application folder.
PROFESSOR_SAFE_IDS: dict[str, str] = {
    "Jeles":       "AskJeles",
    "Hanz":        "FieldNotes",
    "Ofshield":    "Ofshield",
    "Shiva":       "Shiva",
    "Pigeon":      "Pigeon",
    "Binder":      "Binder",
    "Oakenscroll": "Oakenscroll",
    "Riggs":       "Riggs",
    "Nova":        "Nova",
    "Ada":         "Ada",
    "Alexis":      "Alexis",
    "Gerald":      "Gerald",
    "Mitra":       "Mitra",
    "Consus":      "Consus",
    "Jane":        "Jane",
    "Steve":       "Steve",
    "Kart":        "Kart",
}

PROFESSOR_MODELS = {
    "Oakenscroll": DEFAULT_MODEL,
    "Riggs":       DEFAULT_MODEL,
    "Hanz":        DEFAULT_MODEL,
    "Nova":        DEFAULT_MODEL,
    "Ada":         DEFAULT_MODEL,
    "Alexis":      DEFAULT_MODEL,
    "Ofshield":    DEFAULT_MODEL,
    "Gerald":      DEFAULT_MODEL,
    "Kart":        DEFAULT_MODEL,
    "Mitra":       DEFAULT_MODEL,
    "Consus":      DEFAULT_MODEL,
    "Shiva":       DEFAULT_MODEL,
    "Steve":       DEFAULT_MODEL,
    "Pigeon":      DEFAULT_MODEL,
    "Binder":      DEFAULT_MODEL,
    "Jeles":       DEFAULT_MODEL,
    "Willow":      DEFAULT_MODEL,
}

# Credentials live at the willow-1.7 root
CREDENTIALS_PATH = Path(__file__).parent.parent.parent / "credentials.json"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_DEFAULT_MODEL = "llama-3.1-8b-instant"
CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_DEFAULT_MODEL = "llama3.1-8b"
SAMBANOVA_API_URL = "https://api.sambanova.ai/v1/chat/completions"
SAMBANOVA_DEFAULT_MODEL = "Meta-Llama-3.1-8B-Instruct"


def _load_personas() -> dict:
    """Load PERSONAS dict from utety-chat/personas.py at runtime."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("utety_personas", PERSONAS_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, "PERSONAS", {})
    except Exception as e:
        logger.warning("Could not load personas.py: %s", e)
        return {}


def _load_professor_db_context(name: str) -> str:
    """Load professor-specific context from their local SQLite seed DB."""
    folder = name.lower()
    db_path = PROFESSOR_DATA_ROOT / folder / f"{folder}.db"
    if not db_path.exists():
        return ""

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        lines = []

        papers = cur.execute(
            "SELECT title, domain, status FROM papers ORDER BY rowid DESC LIMIT 5"
        ).fetchall()
        if papers:
            lines.append(f"[{name} PAPERS]")
            for p in papers:
                lines.append(f"  - {p['title']} ({p['domain']}, {p['status']})")

        eqs = cur.execute(
            "SELECT label, plain FROM equations WHERE consus_verified=1 LIMIT 5"
        ).fetchall()
        if eqs:
            lines.append(f"[{name} VERIFIED EQUATIONS]")
            for e in eqs:
                lines.append(f"  - {e['label']}: {e['plain']}")

        conn.close()
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Professor DB read failed for %s: %s", name, e)
        return ""


def _load_creds() -> dict:
    try:
        return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not load credentials: %s", e)
        return {}


def _call_openai_compat(url: str, model: str, key: str,
                        system_prompt: str, user_message: str,
                        provider: str) -> Optional[str]:
    """Generic OpenAI-compatible chat completion call."""
    import requests as _req
    try:
        r = _req.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "max_tokens": 2048,
            },
            timeout=60,
        )
        if r.ok:
            content = r.json()["choices"][0]["message"]["content"]
            logger.info("Fleet response via %s (%s)", provider, model)
            return content
        elif r.status_code == 429:
            logger.warning("%s key rate-limited", provider)
            return "RATE_LIMITED"
        else:
            logger.error("%s error %s: %s", provider, r.status_code, r.text[:200])
            return None
    except Exception as e:
        logger.warning("%s call failed: %s", provider, e)
        return None


def _ask_fleet(system_prompt: str, user_message: str) -> Optional[str]:
    """Route through free fleet when Ollama is unavailable."""
    creds = _load_creds()

    for k in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"):
        key = creds.get(k, "")
        if not key or not key.startswith("gsk_"):
            continue
        result = _call_openai_compat(
            GROQ_API_URL, GROQ_DEFAULT_MODEL, key,
            system_prompt, user_message, "Groq"
        )
        if result and result != "RATE_LIMITED":
            return result

    logger.warning("All Groq keys exhausted — falling back to Cerebras")

    for k in ("CEREBRAS_API_KEY", "CEREBRAS_API_KEY_2", "CEREBRAS_API_KEY_3"):
        key = creds.get(k, "")
        if not key or not key.startswith("csk-"):
            continue
        result = _call_openai_compat(
            CEREBRAS_API_URL, CEREBRAS_DEFAULT_MODEL, key,
            system_prompt, user_message, "Cerebras"
        )
        if result and result != "RATE_LIMITED":
            return result

    logger.warning("All Cerebras keys exhausted — falling back to SambaNova")

    for k in ("SAMBANOVA_API_KEY", "SAMBANOVA_API_KEY_2", "SAMBANOVA_API_KEY_3"):
        key = creds.get(k, "")
        if not key:
            continue
        result = _call_openai_compat(
            SAMBANOVA_API_URL, SAMBANOVA_DEFAULT_MODEL, key,
            system_prompt, user_message, "SambaNova"
        )
        if result and result != "RATE_LIMITED":
            return result

    logger.error("All fleet providers exhausted (Groq, Cerebras, SambaNova)")
    return None


def _ollama_options() -> dict:
    import os
    threads = int(os.environ.get("SAP_OLLAMA_THREADS", "4"))
    return {"num_thread": threads}


def _ask_ollama(model: str, system_prompt: str, user_message: str) -> Optional[str]:
    """Call Ollama directly. Falls back to free fleet if unavailable."""
    options = _ollama_options()

    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434", timeout=300)
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options=options,
        )
        return response["message"]["content"]
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Ollama library call failed (%s) — trying HTTP", e)

    try:
        import requests
        r = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "options": options,
                "stream": False,
            },
            timeout=(5, 300),
        )
        if r.ok:
            return r.json()["message"]["content"]
        logger.warning("Ollama HTTP error %s — falling back to fleet", r.status_code)
    except Exception as e:
        logger.warning("Ollama HTTP failed (%s) — falling back to fleet", e)

    return _ask_fleet(system_prompt, user_message)


class ProfessorClient:
    """SAP-authorized interface to a single UTETY professor."""

    def __init__(self, professor_name: str):
        if not authorized(UTETY_APP_ID):
            raise PermissionError(
                f"UTETY is not SAP-authorized. "
                f"Seed SAFE/Applications/UTETY/ to grant access."
            )

        self.name = professor_name
        self.model = PROFESSOR_MODELS.get(professor_name, DEFAULT_MODEL)

        personas = _load_personas()
        self.persona_prompt = personas.get(professor_name, "")
        if not self.persona_prompt:
            logger.warning("No persona found for %s — using name only", professor_name)
            self.persona_prompt = f"You are Professor {professor_name} of UTETY."

        self.db_context = _load_professor_db_context(professor_name)

    def _build_system_prompt(self, sap_context: str = "") -> str:
        parts = [self.persona_prompt]
        if self.db_context:
            parts.append(self.db_context)
        if sap_context:
            parts.append(sap_context)
        return "\n\n".join(parts)

    def ask(self, question: str, sap_query: str = "") -> Optional[str]:
        """Ask this professor a question."""
        is_campus = self.name == "Willow"
        domain = PROFESSOR_DOMAINS.get(self.name, [])
        cache_id = PROFESSOR_SAFE_IDS.get(self.name)

        ctx = assemble(
            UTETY_APP_ID,
            query=sap_query or question,
            max_chars=1500,
            skip_cache=not is_campus,
            category_filter=domain if domain else None,
            cache_app_id=cache_id,
        )
        sap_context = to_string(ctx) if ctx else ""
        system_prompt = self._build_system_prompt(sap_context)
        return _ask_ollama(self.model, system_prompt, question)


def conf_call(
    professors: list[str],
    topic: str,
    facilitator: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """
    Run a multi-professor conversation on a topic.
    Returns {professor_name: response_text}.
    facilitator speaks last with all other responses as context.
    """
    if not authorized(UTETY_APP_ID):
        raise PermissionError("UTETY not SAP-authorized.")

    results: dict[str, Optional[str]] = {}
    panel = [p for p in professors if p != facilitator]

    for name in panel:
        try:
            client = ProfessorClient(name)
            results[name] = client.ask(topic)
        except Exception as e:
            logger.error("conf_call: %s failed: %s", name, e)
            results[name] = None

    if facilitator and facilitator in professors:
        panel_summary = "\n\n".join(
            f"[{k}]: {v}" for k, v in results.items() if v
        )
        facilitator_topic = (
            f"{topic}\n\n"
            f"Other faculty have responded:\n{panel_summary}\n\n"
            f"Please synthesize or respond."
        )
        try:
            client = ProfessorClient(facilitator)
            results[facilitator] = client.ask(facilitator_topic)
        except Exception as e:
            logger.error("conf_call facilitator %s failed: %s", facilitator, e)
            results[facilitator] = None

    return results
