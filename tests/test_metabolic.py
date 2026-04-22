"""Tests for metabolic.py — Norn pass runner."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_norn_pass_returns_report():
    from core.metabolic import norn_pass
    report = norn_pass(dry_run=True)
    assert "composted" in report
    assert "communities" in report
    assert "heartbeat" in report


def test_heartbeat_returns_float():
    from core.metabolic import measure_heartbeat
    score = measure_heartbeat()
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_compost_pass_dry_run_returns_count():
    from core.metabolic import compost_pass
    count = compost_pass(dry_run=True)
    assert isinstance(count, int)
    assert count >= 0


def test_community_pass_dry_run_returns_count():
    from core.metabolic import community_pass
    count = community_pass(dry_run=True)
    assert isinstance(count, int)
    assert count >= 0


def test_norn_pass_squeakdog_field():
    from core.metabolic import norn_pass
    report = norn_pass(dry_run=True)
    assert "squeakdog" in report
    assert isinstance(report["squeakdog"], bool)
