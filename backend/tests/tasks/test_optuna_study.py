"""M-07 — Optuna study runs with the correct search space."""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.slow


def test_objective_returns_float_auc():
    import optuna

    from ml.train import objective_for_species

    rng = np.random.RandomState(0)
    X_tr, y_tr = rng.randn(200, 10), (rng.randn(200) > 0).astype(int)
    X_val, y_val = rng.randn(50, 10), (rng.randn(50) > 0).astype(int)

    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=1)
    )
    study.optimize(
        lambda t: objective_for_species(t, X_tr, y_tr, X_val, y_val, scale_pos_weight=1.0),
        n_trials=3,
        show_progress_bar=False,
    )
    assert 0.0 <= study.best_value <= 1.0


def test_objective_search_space_contains_required_params():
    """M-07 / PRD §6.2 FR-M3 — search space must include every hyperparameter
    in {n_estimators, max_depth, learning_rate, subsample, colsample_bytree,
    min_child_weight, reg_alpha, reg_lambda, gamma}."""
    import optuna

    from ml.train import objective_for_species

    rng = np.random.RandomState(0)
    X_tr, y_tr = rng.randn(100, 5), (rng.randn(100) > 0).astype(int)
    X_val, y_val = rng.randn(25, 5), (rng.randn(25) > 0).astype(int)
    seen: set[str] = set()

    def wrapped(trial):
        auc = objective_for_species(trial, X_tr, y_tr, X_val, y_val, 1.0)
        seen.update(trial.params.keys())
        return auc

    study = optuna.create_study(direction="maximize")
    study.optimize(wrapped, n_trials=2, show_progress_bar=False)
    required = {
        "n_estimators",
        "max_depth",
        "learning_rate",
        "subsample",
        "colsample_bytree",
        "min_child_weight",
        "reg_alpha",
        "reg_lambda",
        "gamma",
    }
    missing = required - seen
    assert not missing, f"Optuna search space missing: {missing}"
