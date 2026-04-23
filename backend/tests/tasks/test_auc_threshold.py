"""Stub — M-08 AUC-ROC ≥ 0.72 on temporal-holdout test set. Implemented in Plan 05."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 05"),
    pytest.mark.slow,
]


def test_per_species_auc_meets_threshold():
    """Plan 05: every species' test AUC ≥ 0.72. Low-label regime caveat documented in MLflow notes (D-04)."""
    assert False, "Not implemented"
