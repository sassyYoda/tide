"""M-06/M-07/M-10 — training pipeline integration on synthetic data."""

from __future__ import annotations

import pytest

# Optuna sweep + XGBoost fits even at small n_trials are slower than unit tests.
pytestmark = pytest.mark.slow


@pytest.fixture
def synthetic_split():
    """Deterministic synthetic dataset — 400 train / 100 val / 100 test rows, 20 features.

    Signal: ``y = (X[:,0] + X[:,1] + small_noise) > 0`` so a tree model can learn it
    quickly with very few trials. Two solunar-shaped names planted at the tail so
    the leakage gate path exercises the SOLUNAR_FEATURE_NAMES intersection.
    """
    import numpy as np

    rng = np.random.RandomState(42)
    n_tr, n_val, n_te = 400, 100, 100
    n_feat = 20
    X_tr = rng.randn(n_tr, n_feat)
    X_val = rng.randn(n_val, n_feat)
    X_te = rng.randn(n_te, n_feat)
    y_tr = (X_tr[:, 0] + X_tr[:, 1] + 0.5 * rng.randn(n_tr) > 0).astype(int)
    y_val = (X_val[:, 0] + X_val[:, 1] + 0.5 * rng.randn(n_val) > 0).astype(int)
    y_te = (X_te[:, 0] + X_te[:, 1] + 0.5 * rng.randn(n_te) > 0).astype(int)
    feature_names = [f"f{i}" for i in range(n_feat)]
    feature_names[-1] = "moon_phase_sin"
    feature_names[-2] = "illumination"
    return X_tr, y_tr, X_val, y_val, X_te, y_te, feature_names


def test_train_species_logs_mlflow_run(mlflow_tmp_tracking, synthetic_split):
    import mlflow

    from ml.train import EXPERIMENT_NAME, train_species

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = synthetic_split
    result = train_species(
        "striper",
        X_tr,
        y_tr,
        X_val,
        y_val,
        X_te,
        y_te,
        fn,
        n_trials=5,
        run_tag="test",
    )
    assert "run_id" in result
    assert "auc_test" in result

    client = mlflow.tracking.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT_NAME)
    assert exp is not None
    runs = client.search_runs(experiment_ids=[exp.experiment_id])
    assert len(runs) >= 1


def test_train_species_reports_auc_brier_p25(mlflow_tmp_tracking, synthetic_split):
    from ml.train import train_species

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = synthetic_split
    result = train_species(
        "fluke", X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=5, run_tag="test"
    )
    assert 0.0 <= result["auc_test"] <= 1.0
    assert 0.0 <= result["brier_test"] <= 1.0
    assert 0.0 <= result["p_at_25_test"] <= 1.0


def test_train_species_picks_sigmoid_when_n_val_small(mlflow_tmp_tracking, synthetic_split):
    from ml.train import train_species

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = synthetic_split
    # n_val = 50 (< 500) → sigmoid
    result = train_species(
        "bluefish",
        X_tr,
        y_tr,
        X_val[:50],
        y_val[:50],
        X_te,
        y_te,
        fn,
        n_trials=3,
        run_tag="test",
    )
    assert result["calibration_method"] == "sigmoid"


def test_train_species_empty_fold_skips_gracefully(mlflow_tmp_tracking, synthetic_split):
    import numpy as np

    from ml.train import train_species

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = synthetic_split
    result = train_species(
        "weakfish",
        np.empty((0, 20)),
        np.empty(0),
        X_val,
        y_val,
        X_te,
        y_te,
        fn,
        n_trials=3,
        run_tag="test",
    )
    assert result.get("skipped") is True


def test_top_k_shap_returns_k_features(synthetic_split):
    import xgboost as xgb

    from ml.shap_utils import top_k_shap

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = synthetic_split
    model = xgb.XGBClassifier(n_estimators=20, max_depth=3, tree_method="hist", n_jobs=-1)
    model.fit(X_tr, y_tr)
    result = top_k_shap(model, X_te[0], fn, k=3)
    assert len(result) == 3
    assert all(set(r.keys()) == {"feature", "value"} for r in result)
    abs_vals = [abs(r["value"]) for r in result]
    assert abs_vals == sorted(abs_vals, reverse=True)
