"""Stub — M-13 / OPS-07 MLflow run structure (params, metrics, artifacts). Implemented in Plans 03, 05."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plans 03, 05")


def test_per_species_runs_logged():
    """Plan 05: one MLflow run per species per training pass (early + full)."""
    assert False, "Not implemented"


def test_run_captures_optuna_params_metrics_shap():
    """Plan 03: run has all Optuna trial params, AUC/Brier metrics, SHAP summary plot."""
    assert False, "Not implemented"


def test_best_run_promoted_to_production_alias():
    """Plan 05 (D-12): best-by-val-AUC run gets the 'production' alias in MLflow registry."""
    assert False, "Not implemented"
