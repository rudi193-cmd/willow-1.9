#!/usr/bin/env python3
"""
gleipnir.py — W19GL: Behavioral rate limiting.
b17: GLP19  ΔΣ=42

The chain that held Fenrir — softer than rope, unbreakable.
Soft warnings before hard stops. Does not crash sessions. Slows runaway agents.
"""
import time
from collections import defaultdict


class Gleipnir:
    """Stateful rate limiter. One instance per SAP server process."""

    def __init__(self, soft_limit: int = 30, hard_limit: int = 60,
                 window_seconds: float = 60.0):
        self.soft_limit = soft_limit
        self.hard_limit = hard_limit
        self.window = window_seconds
        self._log: dict[str, list[float]] = defaultdict(list)

    def _recent(self, app_id: str) -> list[float]:
        now = time.time()
        recent = [t for t in self._log[app_id] if now - t < self.window]
        self._log[app_id] = recent
        return recent

    def check(self, app_id: str, tool_name: str) -> tuple[bool, str]:
        """Register one call. Returns (allowed, reason). allowed=False = deny."""
        recent = self._recent(app_id)
        self._log[app_id].append(time.time())
        count = len(recent) + 1
        if count > self.hard_limit:
            return (False,
                    f"Rate limit exceeded: {count} calls in {self.window:.0f}s "
                    f"(hard limit {self.hard_limit}). Gleipnir holds.")
        if count > self.soft_limit:
            return (True,
                    f"Warning: {count} calls in {self.window:.0f}s "
                    f"(soft limit {self.soft_limit}). Slow down.")
        return True, ""

    def stats(self, app_id: str) -> dict:
        return {
            "app_id": app_id,
            "recent_calls": len(self._recent(app_id)),
            "window_seconds": self.window,
            "soft_limit": self.soft_limit,
            "hard_limit": self.hard_limit,
        }


_default = Gleipnir()


def check(app_id: str, tool_name: str) -> tuple[bool, str]:
    return _default.check(app_id, tool_name)


def stats(app_id: str) -> dict:
    return _default.stats(app_id)
