"""M-08 — per-species AUC ≥ 0.72 gate with D-04/D-16 tautog fallback decision tree.

Plan 02-05 implementation: ``scripts.train_all_species._check_quality_gates`` is
the single chokepoint that asserts the gate against per-species results dicts
returned by the training orchestrator.
"""
from __future__ import annotations

import logging

import pytest


def test_gate_passes_all_species_above_target():
    """All species at AUC=0.80 / Brier=0.15 / P@25=0.70 — well above gates."""
    from scripts.train_all_species import _check_quality_gates

    results = {
        sp: {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70}
        for sp in ("striper", "fluke", "bluefish", "weakfish", "tautog")
    }
    _check_quality_gates(results)  # no raise


def test_gate_fails_non_tog_species_below_072():
    """Striper at AUC=0.71 must fail M-08 (non-tog floor is 0.72)."""
    from scripts.train_all_species import _check_quality_gates

    results = {
        "striper": {"auc_test": 0.71, "brier_test": 0.15, "p_at_25_test": 0.70},
        "fluke": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
    }
    with pytest.raises(RuntimeError, match="striper.*AUC"):
        _check_quality_gates(results)


def test_gate_tautog_065_to_072_is_pass_with_note(caplog):
    """D-16 fallback: tog at AUC=0.68 logs a warning but does not raise."""
    from scripts.train_all_species import _check_quality_gates

    caplog.set_level(logging.WARNING, logger="scripts.train_all_species")
    results = {
        "tautog": {"auc_test": 0.68, "brier_test": 0.18, "p_at_25_test": 0.66},
        "striper": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
        "fluke": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
        "bluefish": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
        "weakfish": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
    }
    _check_quality_gates(results)  # no raise
    msgs = [rec.getMessage() for rec in caplog.records]
    assert any("tautog" in m and "pass-with-note" in m.lower() for m in msgs), (
        f"expected pass-with-note warning for tautog; got: {msgs}"
    )


def test_gate_tautog_below_065_fails():
    """D-16 fallback: tog AUC=0.62 < 0.65 floor — must raise."""
    from scripts.train_all_species import _check_quality_gates

    results = {
        "tautog": {"auc_test": 0.62, "brier_test": 0.20, "p_at_25_test": 0.66},
    }
    with pytest.raises(RuntimeError, match=r"tautog.*0\.65"):
        _check_quality_gates(results)


def test_gate_skipped_species_is_warning_not_failure(caplog):
    """A species marked as skipped (insufficient_labels etc.) should not raise."""
    from scripts.train_all_species import _check_quality_gates

    caplog.set_level(logging.WARNING, logger="scripts.train_all_species")
    results = {
        "tautog": {"skipped": True, "reason": "insufficient_labels"},
        "striper": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
        "fluke": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
        "bluefish": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
        "weakfish": {"auc_test": 0.80, "brier_test": 0.15, "p_at_25_test": 0.70},
    }
    _check_quality_gates(results)
    msgs = [rec.getMessage() for rec in caplog.records]
    assert any("tautog" in m and "skipped" in m for m in msgs), (
        f"expected skip warning for tautog; got: {msgs}"
    )
