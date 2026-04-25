"""Tests for core/seed_kb.py — idempotent KB seeding."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Minimal mock bridge ───────────────────────────────────────────────────────

class MockBridge:
    """Minimal in-memory bridge that satisfies seed_kb's interface."""

    def __init__(self):
        # title -> record
        self._atoms: dict[str, dict] = {}

    def knowledge_put(self, record: dict) -> str:
        self._atoms[record["title"]] = record
        return record["id"]

    def knowledge_search(self, query: str, limit: int = 20) -> list:
        """Return atoms whose title exactly matches query (case-insensitive)."""
        q = query.strip().lower()
        return [v for v in self._atoms.values()
                if (v.get("title") or "").strip().lower() == q]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_seed_kb_writes_atoms():
    """seed_kb writes at least one atom on a fresh bridge."""
    from core.seed_kb import seed_kb
    bridge = MockBridge()
    count = seed_kb(bridge, skip_existing=False)
    assert count > 0, "seed_kb should write at least one atom"


def test_seed_kb_skip_existing():
    """seed_kb with skip_existing=True writes 0 atoms when KB is already seeded."""
    from core.seed_kb import seed_kb
    bridge = MockBridge()

    # First pass — populate everything
    first_count = seed_kb(bridge, skip_existing=False)
    assert first_count > 0

    # Second pass with skip_existing — should write nothing
    second_count = seed_kb(bridge, skip_existing=True)
    assert second_count == 0, (
        f"Expected 0 atoms written on second pass with skip_existing=True, "
        f"got {second_count}"
    )


def test_seed_kb_atoms_have_required_fields():
    """Every written atom has title, summary, source_type=seed, project=willow."""
    from core.seed_kb import seed_kb
    bridge = MockBridge()
    seed_kb(bridge, skip_existing=False)

    for title, atom in bridge._atoms.items():
        assert atom.get("title"), f"Atom missing title: {atom}"
        assert atom.get("summary"), f"Atom '{title}' missing summary"
        assert atom.get("source_type") == "seed", (
            f"Atom '{title}' source_type={atom.get('source_type')!r}, expected 'seed'"
        )
        assert atom.get("project") == "willow", (
            f"Atom '{title}' project={atom.get('project')!r}, expected 'willow'"
        )


def test_seed_kb_includes_architecture_atoms():
    """Architecture atoms are present and categorised correctly."""
    from core.seed_kb import seed_kb
    bridge = MockBridge()
    seed_kb(bridge, skip_existing=False)

    arch_atoms = [a for a in bridge._atoms.values() if a.get("category") == "architecture"]
    assert len(arch_atoms) > 0, "Expected at least one architecture atom"

    titles = [a["title"] for a in arch_atoms]
    assert any("Postgres" in t for t in titles), (
        "Expected a Postgres architecture atom"
    )


def test_seed_kb_includes_skill_atoms():
    """Skill atoms are present for at least one fylgja skill file."""
    from core.seed_kb import seed_kb
    bridge = MockBridge()
    seed_kb(bridge, skip_existing=False)

    skill_atoms = [a for a in bridge._atoms.values() if a.get("category") == "skill"]
    assert len(skill_atoms) > 0, "Expected at least one skill atom"


def test_seed_kb_includes_command_atoms():
    """CLI command atoms are present."""
    from core.seed_kb import seed_kb
    bridge = MockBridge()
    seed_kb(bridge, skip_existing=False)

    cmd_atoms = [a for a in bridge._atoms.values() if a.get("category") == "command"]
    assert len(cmd_atoms) > 0, "Expected at least one command atom"

    titles = [a["title"] for a in cmd_atoms]
    assert any("willow status" in t for t in titles), (
        "Expected 'willow status' command atom"
    )


def test_seed_kb_skip_false_rewrites():
    """skip_existing=False writes all atoms even when bridge already has them."""
    from core.seed_kb import seed_kb
    bridge = MockBridge()

    first_count = seed_kb(bridge, skip_existing=False)
    second_count = seed_kb(bridge, skip_existing=False)
    assert second_count == first_count, (
        "skip_existing=False should write the same count on every call"
    )
