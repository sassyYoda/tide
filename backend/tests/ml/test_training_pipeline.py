"""Stub — M-04/M-06/M-07/M-08/M-09 training pipeline. Implemented in Plans 03, 05."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plans 03, 05")


def test_per_species_metrics_meet_thresholds():
    """Plan 05: AUC ≥ 0.72 and Brier ≤ 0.22 per species on temporal-holdout."""
    assert False, "Not implemented"


def test_solunar_permutation_gate():
    """Plan 03: solunar features contribute > 0.01 AUC lift via permutation."""
    assert False, "Not implemented"


def test_lightgbm_baseline_logged():
    """Plan 03: LightGBM baseline run exists in MLflow for comparison (M-06)."""
    assert False, "Not implemented"
