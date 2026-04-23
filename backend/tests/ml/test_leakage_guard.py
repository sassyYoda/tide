"""Stub — M-04 / M-14 temporal-holdout leakage guard. Implemented in Plan 02.

This is the single most critical test in Phase 2 per PITFALLS.md §1: any
test timestamp appearing in the training feature matrix is a hard fail.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 02")


def test_no_test_timestamps_in_training_features():
    """Plan 02: assert set(train.label_time) ∩ set(test.label_time) == empty."""
    assert False, "Not implemented"


def test_no_future_environmental_joins():
    """Plan 02: assert no feature row joins env data newer than its label_time."""
    assert False, "Not implemented"
