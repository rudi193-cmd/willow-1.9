# tests/adversarial/test_rate_limiting.py
"""Gleipnir rate limiting — hard/soft limits, window expiry, app_id isolation.
Each test uses a fresh Gleipnir instance to avoid cross-test state pollution.
"""
import time
import pytest
from core.gleipnir import Gleipnir


def test_under_soft_limit_allowed():
    """29 calls — all allowed, no warning."""
    g = Gleipnir(soft_limit=30, hard_limit=60, window_seconds=60.0)
    for i in range(29):
        allowed, reason = g.check("adv_app", "store_list")
        assert allowed is True, f"Call {i + 1} should be allowed"
        assert reason == "", f"Call {i + 1} should have no warning, got: {reason!r}"


def test_at_soft_limit_warns():
    """31st call (past soft_limit=30) — allowed but with non-empty warning."""
    g = Gleipnir(soft_limit=30, hard_limit=60, window_seconds=60.0)
    for _ in range(30):
        g.check("adv_app_warn", "store_list")
    allowed, reason = g.check("adv_app_warn", "store_list")  # 31st
    assert allowed is True
    assert reason != "", f"Expected soft warning, got empty reason"


def test_over_hard_limit_denied():
    """61st call (past hard_limit=60) — denied with non-empty reason."""
    g = Gleipnir(soft_limit=30, hard_limit=60, window_seconds=60.0)
    for _ in range(60):
        g.check("adv_app_hard", "store_list")
    allowed, reason = g.check("adv_app_hard", "store_list")  # 61st
    assert allowed is False
    assert reason != "", f"Expected denial reason, got empty string"


def test_window_expiry_resets_count():
    """After window expires, call count resets — first new call is allowed with no warning."""
    g = Gleipnir(soft_limit=5, hard_limit=10, window_seconds=0.1)
    for _ in range(10):
        g.check("adv_app_exp", "store_list")
    # Verify we're at hard limit
    allowed, _ = g.check("adv_app_exp", "store_list")
    assert allowed is False
    # Wait for window to expire
    time.sleep(0.15)
    allowed, reason = g.check("adv_app_exp", "store_list")
    assert allowed is True
    assert reason == "", f"Window expired — expected no warning, got: {reason!r}"


def test_two_app_ids_isolated():
    """app_a at hard limit does not block app_b."""
    g = Gleipnir(soft_limit=30, hard_limit=60, window_seconds=60.0)
    for _ in range(61):
        g.check("adv_app_a_iso", "store_list")
    # app_a is blocked
    allowed_a, _ = g.check("adv_app_a_iso", "store_list")
    assert allowed_a is False
    # app_b has made 0 calls — should be allowed
    allowed_b, reason_b = g.check("adv_app_b_iso", "store_list")
    assert allowed_b is True
    assert reason_b == ""


def test_stats_returns_correct_count():
    """stats() reflects the exact number of recent calls."""
    g = Gleipnir(soft_limit=30, hard_limit=60, window_seconds=60.0)
    for _ in range(10):
        g.check("adv_stats_app", "store_list")
    stats = g.stats("adv_stats_app")
    assert stats["recent_calls"] == 10
    assert stats["app_id"] == "adv_stats_app"
    assert stats["soft_limit"] == 30
    assert stats["hard_limit"] == 60


def test_custom_window_sub_second():
    """Custom short window: exhaust, wait, verify recovery."""
    g = Gleipnir(soft_limit=5, hard_limit=10, window_seconds=0.1)
    for _ in range(11):
        g.check("adv_fast", "store_list")
    denied, _ = g.check("adv_fast", "store_list")
    assert denied is False
    time.sleep(0.15)
    allowed, reason = g.check("adv_fast", "store_list")
    assert allowed is True
    assert reason == ""
