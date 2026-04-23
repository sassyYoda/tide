"""Stub — M-09 Brier ≤ 0.22 and Precision@top-25% ≥ 0.65. Implemented in Plan 05."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05"),
    pytest.mark.slow,
]


def test_brier_score_under_threshold():
    """Plan 05: per-species Brier ≤ 0.22 after CalibratedClassifierCV."""
    assert False, "Not implemented"


def test_precision_at_top_25_percent():
    """Plan 05: top-25% of predictions by score contain ≥ 65% true positives."""
    assert False, "Not implemented"
