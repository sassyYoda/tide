"""Stub — M-07 Optuna hyperparameter search. Implemented in Plan 03."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 03"),
    pytest.mark.slow,
]


def test_optuna_study_has_n_trials():
    """Plan 03: study.trials length >= configured target (100 by default, reducible to 60/species)."""
    assert False, "Not implemented"


def test_optuna_optimizes_val_auc():
    """Plan 03: objective returns validation AUC-ROC; direction=maximize."""
    assert False, "Not implemented"
