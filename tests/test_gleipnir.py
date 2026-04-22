"""Tests for W19GL — Gleipnir: behavioral rate limiting."""
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_check_allows_first_call():
    from core.gleipnir import Gleipnir
    g = Gleipnir(soft_limit=10, hard_limit=20)
    allowed, reason = g.check("app_a", "store_put")
    assert allowed is True


def test_check_warns_at_soft_limit():
    from core.gleipnir import Gleipnir
    g = Gleipnir(soft_limit=3, hard_limit=10)
    for _ in range(3):
        g.check("app_a", "store_put")
    allowed, reason = g.check("app_a", "store_put")
    assert allowed is True
    assert "Warning" in reason or "warning" in reason.lower()


def test_check_denies_at_hard_limit():
    from core.gleipnir import Gleipnir
    g = Gleipnir(soft_limit=2, hard_limit=5)
    for _ in range(5):
        g.check("app_b", "store_put")
    allowed, reason = g.check("app_b", "store_put")
    assert allowed is False
    assert len(reason) > 0


def test_check_resets_after_window(monkeypatch):
    from core.gleipnir import Gleipnir
    g = Gleipnir(soft_limit=2, hard_limit=3, window_seconds=1)
    for _ in range(3):
        g.check("app_c", "tool")
    allowed_before, _ = g.check("app_c", "tool")
    assert allowed_before is False
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 2.0)
    allowed_after, _ = g.check("app_c", "tool")
    assert allowed_after is True


def test_different_apps_have_independent_limits():
    from core.gleipnir import Gleipnir
    g = Gleipnir(soft_limit=2, hard_limit=3)
    for _ in range(3):
        g.check("app_d", "tool")
    allowed_d, _ = g.check("app_d", "tool")
    allowed_e, _ = g.check("app_e", "tool")
    assert allowed_d is False
    assert allowed_e is True


def test_get_stats_returns_call_count():
    from core.gleipnir import Gleipnir
    g = Gleipnir(soft_limit=10, hard_limit=20)
    g.check("app_f", "tool")
    g.check("app_f", "tool")
    stats = g.stats("app_f")
    assert stats["recent_calls"] >= 2
