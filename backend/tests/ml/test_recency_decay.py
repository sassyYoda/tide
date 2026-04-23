"""Stub — R-08 recency-decay multiplier on fused retrieval scores. Implemented in Plan 06."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 06")


def test_recency_multipliers_match_spec():
    """Plan 06: 1.0 ≤24h, 0.80 24-72h, 0.60 ≤1wk, 0.40 ≤1mo, 0.20 older (R-08)."""
    assert False, "Not implemented"


def test_recency_decay_applied_after_rrf():
    """Plan 06: recency multiplies the fused RRF score, not the raw dense/sparse."""
    assert False, "Not implemented"
