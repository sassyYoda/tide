"""Stub — M-04 temporal-holdout train/val/test split. Implemented in Plan 02."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 02")


def test_split_is_temporal_not_random():
    """Plan 02: assert max(train.label_time) < min(val.label_time) < min(test.label_time)."""
    assert False, "Not implemented"


def test_split_ratios_70_15_15():
    """Plan 02: train/val/test ratios approximately 0.70/0.15/0.15."""
    assert False, "Not implemented"
