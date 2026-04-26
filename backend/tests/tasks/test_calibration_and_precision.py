"""M-09 — Brier ≤ 0.22 + Precision@Top25% ≥ 0.65 quality gates.

Both metrics are hard for every promoted (non-skipped) species. Tested through
``scripts.train_all_species._check_quality_gates``.
"""
from __future__ import annotations

import pytest


def test_gate_fails_brier_over_022():
    """Brier=0.25 fails M-09 even when AUC and P@25 are clean."""
    from scripts.train_all_species import _check_quality_gates

    results = {
        "striper": {"auc_test": 0.80, "brier_test": 0.25, "p_at_25_test": 0.70},
    }
    with pytest.raises(RuntimeError, match="Brier"):
        _check_quality_gates(results)


def test_gate_fails_p25_below_065():
    """P@25=0.60 fails M-09 even when AUC and Brier are clean."""
    from scripts.train_all_species import _check_quality_gates

    results = {
        "striper": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.60},
    }
    with pytest.raises(RuntimeError, match="P@25"):
        _check_quality_gates(results)


def test_gate_all_metrics_borderline_passes():
    """Exact thresholds (AUC=0.72 / Brier=0.22 / P@25=0.65) pass — borderline."""
    from scripts.train_all_species import _check_quality_gates

    results = {
        "striper": {"auc_test": 0.72, "brier_test": 0.22, "p_at_25_test": 0.65},
        "fluke": {"auc_test": 0.72, "brier_test": 0.22, "p_at_25_test": 0.65},
        "bluefish": {"auc_test": 0.72, "brier_test": 0.22, "p_at_25_test": 0.65},
        "weakfish": {"auc_test": 0.72, "brier_test": 0.22, "p_at_25_test": 0.65},
        "tautog": {"auc_test": 0.72, "brier_test": 0.22, "p_at_25_test": 0.65},
    }
    _check_quality_gates(results)  # borderline pass — no raise
