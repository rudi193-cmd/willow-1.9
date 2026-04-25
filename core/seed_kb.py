#!/usr/bin/env python3
"""
seed_kb.py — Populate KB with neutral starter atoms on first install.
b17: SKBD1  ΔΣ=42

Writes skill, command, and architecture atoms to the knowledge table via PgBridge.
Safe to run multiple times — skip_existing=True (default) skips already-present atoms.
All atoms use domain="willow", source_type="seed".
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.pg_bridge import PgBridge

WILLOW_ROOT = Path(__file__).parent.parent

# ── Architecture atoms ────────────────────────────────────────────────────────

_ARCH_ATOMS = [
    (
        "SOIL local store",
        "SQLite-backed key/value + FTS, collections at ~/.willow/store/",
    ),
    (
        "Postgres knowledge base",
        "Typed atoms with edges, semantic + FTS search, willow_19 DB",
    ),
    (
        "Kart task queue",
        "Sandboxed task executor for shell commands and Python scripts",
    ),
    (
        "SAP authorization",
        "SAFE Authorization Protocol, filesystem-based identity gate",
    ),
    (
        "Fylgja skills",
        "LLM-agnostic behavioral skills, script-backed, any API key",
    ),
    (
        "Ollama inference",
        "Local-first LLM inference, default provider, no API key required",
    ),
    (
        "LiteLLM gateway",
        "Unified provider abstraction at localhost:4000, cloud keys optional",
    ),
    (
        "Grove dashboard",
        "Terminal UI for system status, provider management, skill invocation",
    ),
]

# ── CLI command descriptions ──────────────────────────────────────────────────

_CMD_DESCRIPTIONS: dict[str, str] = {
    "start":        "Start SAP MCP server (stdio) — default command",
    "status":       "Check Postgres connectivity, metabolic socket, and installed version",
    "metabolic":    "Run Norn metabolic pass immediately",
    "update":       "Check for updates from GitHub and apply if a newer version is available",
    "export":       "Dump user store data to ~/.willow/export.json",
    "purge":        "Delete all KB atoms for a named project namespace",
    "ledger":       "Display FRANK integrity ledger with optional project filter",
    "backup":       "Create a versioned backup of ~/.willow/ and Postgres data",
    "restore":      "Restore ~/.willow/ and Postgres from a backup directory",
    "nuke":         "Wipe ~/.willow/ entirely — irreversible, requires confirmation",
    "valhalla":     "Collect DPO training pairs from KB to ~/.willow/valhalla/",
    "verify":       "Verify GPG signatures on all SAFE application manifests",
    "start-all":    "Start all Willow systemd user services",
    "stop-all":     "Stop all Willow systemd user services",
    "status-all":   "Show status of all Willow services and Postgres",
    "restart":      "Stop then start all Willow services",
    "check-updates": "Check GitHub for newer releases and queue a Grove alert if found",
    "grove":        "Grove contact management — add contacts by address and public key",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_frontmatter(path: Path) -> dict[str, str]:
    """Extract YAML-ish key: value pairs from a --- ... --- frontmatter block."""
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return result
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


def _atom_exists(bridge: "PgBridge", title: str) -> bool:
    """Return True if an atom with this exact title already exists."""
    results = bridge.knowledge_search(title, limit=1)
    for row in results:
        if (row.get("title") or "").strip().lower() == title.strip().lower():
            return True
    return False


def _put(bridge: "PgBridge", title: str, summary: str, category: str,
         tags: list[str], extra_content: dict | None = None) -> None:
    atom_id = uuid.uuid4().hex[:8].upper()
    content: dict = {"tags": tags}
    if extra_content:
        content.update(extra_content)
    bridge.knowledge_put({
        "id":          atom_id,
        "project":     "willow",
        "title":       title,
        "summary":     summary,
        "source_type": "seed",
        "category":    category,
        "content":     content,
    })


# ── Public API ────────────────────────────────────────────────────────────────

def seed_kb(bridge: "PgBridge", skip_existing: bool = True) -> int:
    """
    Write seed atoms to the KB.

    Returns the number of atoms actually written (skipped atoms not counted).
    All atoms use domain/project="willow" and source_type="seed".
    """
    written = 0

    # 1. Skill atoms — one per fylgja skill file
    skills_dir = WILLOW_ROOT / "willow" / "fylgja" / "skills"
    if skills_dir.is_dir():
        for skill_path in sorted(skills_dir.glob("*.md")):
            fm = _parse_frontmatter(skill_path)
            name = fm.get("name") or skill_path.stem
            description = fm.get("description") or f"Fylgja skill: {name}"
            title = name  # stored as bare name, e.g. "brainstorming"
            if skip_existing and _atom_exists(bridge, title):
                continue
            _put(
                bridge,
                title=title,
                summary=description,
                category="skill",
                tags=["skill", "fylgja"],
                extra_content={"path": f"willow/fylgja/skills/{skill_path.name}"},
            )
            written += 1

    # 2. CLI command atoms — one per willow.sh subcommand
    for cmd, description in _CMD_DESCRIPTIONS.items():
        title = f"willow {cmd}"
        if skip_existing and _atom_exists(bridge, title):
            continue
        _put(
            bridge,
            title=title,
            summary=description,
            category="command",
            tags=["cli", "willow.sh"],
        )
        written += 1

    # 3. Architecture atoms
    for arch_title, arch_summary in _ARCH_ATOMS:
        if skip_existing and _atom_exists(bridge, arch_title):
            continue
        _put(
            bridge,
            title=arch_title,
            summary=arch_summary,
            category="architecture",
            tags=["architecture", "willow"],
        )
        written += 1

    return written
