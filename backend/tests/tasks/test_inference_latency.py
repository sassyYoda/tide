"""Stub — M-12 XGBoost inference ≤ 50ms per prediction. Implemented in Plan 07."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 07"),
    pytest.mark.slow,
]


def test_single_prediction_under_50ms():
    """Plan 07: median of 100 single-row predict() calls < 50ms."""
    assert False, "Not implemented"


def test_model_loads_at_app_startup():
    """Plan 07: FastAPI startup hook loads model from GCS (or local) and caches it."""
    assert False, "Not implemented"
