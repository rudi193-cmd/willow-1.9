#!/usr/bin/env python3
"""
ratatoskr.py — W19RT: Cross-project connect protocol.
b17: RAT19  ΔΣ=42

The squirrel that carries messages between projects. He distorts intentionally.

Without connect declaration: only community_detection atoms cross the boundary.
With connect declared in manifest: full access (still scoped — no global bleed).
"""
import json
import os
from pathlib import Path
from typing import Optional

_SAFE_ROOT = Path(os.environ.get("WILLOW_SAFE_ROOT",
                                  str(Path.home() / "SAFE" / "Applications")))


def get_connected_projects(app_id: str, safe_root: Optional[Path] = None) -> list:
    """Read connect declarations from app_id's SAFE manifest."""
    root = safe_root or _SAFE_ROOT
    manifest_path = root / app_id / "safe-app-manifest.json"
    if not manifest_path.exists():
        return []
    try:
        return list(json.loads(manifest_path.read_text()).get("connect", []))
    except (json.JSONDecodeError, OSError):
        return []


def is_connected(app_id: str, target_project: str,
                 safe_root: Optional[Path] = None) -> bool:
    """Return True if app_id has declared a connect to target_project."""
    return target_project in get_connected_projects(app_id, safe_root)


def filter_for_cross_project(records: list, full_access: bool = False) -> list:
    """
    Apply Ratatoskr degradation to cross-project results.
    Without full_access: only community_detection atoms pass through.
    With full_access (connect declared): all records pass through.
    """
    if full_access:
        return records
    return [r for r in records if r.get("source_type") == "community_detection"]


def cross_project_search(bridge, query: str, source_project: str,
                          target_project: str, app_id: str,
                          safe_root: Optional[Path] = None) -> list:
    """Search target_project's KB with Ratatoskr degradation applied."""
    full_access = is_connected(app_id, target_project, safe_root)
    results = bridge.knowledge_search(query, project=target_project,
                                      include_invalid=False)
    return filter_for_cross_project(results, full_access=full_access)
