# core/secret_prefixes.py — Single source of truth for API key prefix detection.
# Both the dashboard (safe-app-willow-grove) and the orchestrator (Ratatosk/Hanz)
# import from here. Append new entries as providers are added — do not duplicate.
# b17: SECPFX  ΔΣ=42

SECRET_PREFIXES: dict[str, str] = {
    "sk-ant-":       "anthropic_api_key",
    "gsk_":          "groq_api_key",
    "csk-":          "cerebras_api_key",
    "AIzaSy":        "gemini_api_key",
    "sk_sn-":        "sambanova_api_key",
    # More-specific prefixes must come before less-specific ones (sk-proj- before sk-)
    "sk-proj-":      "openai_project_key",
    "sk-":           "openai_api_key",
    "AKIA":          "aws_access_key",
    "ghp_":          "github_pat",
    "github_pat_":   "github_fine_grained_pat",
    "hf_":           "huggingface_token",
    "xai-":          "xai_api_key",
}


def detect_secret(raw: str) -> tuple[str, str] | None:
    """Return (canonical_name, provider_label) if raw matches a known key prefix.

    Requires the string to extend at least 8 chars past the prefix to avoid
    false-positives on prefix-only strings.
    """
    for prefix, name in SECRET_PREFIXES.items():
        if raw.startswith(prefix) and len(raw) > len(prefix) + 8:
            label = name.replace("_api_key", "").title()
            return name, label
    return None


def redact(text: str) -> str:
    """Replace any detected key in text with a truncated ellipsis form.

    Used before persisting chat transcripts or log lines.
    Preserves the first len(prefix)+4 chars so the key remains identifiable
    in the log without being usable.
    """
    for prefix in SECRET_PREFIXES:
        start = 0
        while True:
            idx = text.find(prefix, start)
            if idx == -1:
                break
            end = idx + len(prefix) + 8
            while end < len(text) and not text[end].isspace():
                end += 1
            if end - idx > len(prefix) + 8:
                visible = text[idx:idx + len(prefix) + 4]
                text = text[:idx] + visible + "…" + text[end:]
            start = idx + 1
    return text
