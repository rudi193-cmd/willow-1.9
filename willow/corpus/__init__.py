"""
willow/corpus — Corpus Collapse learning protocol.
b17: CRPS0  ΔΣ=42

Phase 0 (sandbox): intake, capture, load.
Phase 1+ (full): intelligence passes, consent federation, cross-user synthesis.

The sandbox flag marks atoms as Phase 0. When Phase 1 ships, remove the flag.
Data format is identical — nothing migrates.
"""
from willow.corpus.sandbox import (
    needs_intake,
    save_seed,
    save_preference,
    save_correction,
    save_session,
    load_context,
)

__all__ = [
    "needs_intake",
    "save_seed",
    "save_preference",
    "save_correction",
    "save_session",
    "load_context",
]
