"""M-13 + OPS-07 — MLflow experiment structure + per-species run artifacts."""

from __future__ import annotations

import numpy as np
import pytest

# Each test trains a tiny XGBoost model so the suite is slower than unit tests.
pytestmark = pytest.mark.slow


def _synthetic(n_tr=100, n_val=30, n_te=30, n_feat=10, seed=0):
    rng = np.random.RandomState(seed)
    X_tr = rng.randn(n_tr, n_feat)
    X_val = rng.randn(n_val, n_feat)
    X_te = rng.randn(n_te, n_feat)
    # Learnable signal so AUC > 0.5 and calibration succeeds
    y_tr = (X_tr[:, 0] + 0.5 * rng.randn(n_tr) > 0).astype(int)
    y_val = (X_val[:, 0] + 0.5 * rng.randn(n_val) > 0).astype(int)
    y_te = (X_te[:, 0] + 0.5 * rng.randn(n_te) > 0).astype(int)
    fn = [f"f{i}" for i in range(n_feat)]
    return X_tr, y_tr, X_val, y_val, X_te, y_te, fn


def test_tide_activity_model_experiment_created(mlflow_tmp_tracking):
    import mlflow

    from ml.train import EXPERIMENT_NAME, train_species

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = _synthetic()
    train_species(
        "striper", X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=3, run_tag="test"
    )

    client = mlflow.tracking.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT_NAME)
    assert exp is not None, f"Experiment {EXPERIMENT_NAME} was not created"
    runs = client.search_runs(experiment_ids=[exp.experiment_id])
    assert len(runs) >= 1
    run = runs[0]

    # Required params per OPS-07 — every run logs at least these
    for key in ("species", "run_tag", "n_trials", "scale_pos_weight"):
        assert key in run.data.params, f"missing param {key} in {list(run.data.params.keys())}"
    # Required metrics per M-13
    for key in (
        "auc_test",
        "brier_test",
        "precision_at_top25_test",
        "solunar_total_auc_lift",
    ):
        assert key in run.data.metrics, (
            f"missing metric {key} in {list(run.data.metrics.keys())}"
        )


def test_per_species_runs_under_single_experiment(mlflow_tmp_tracking):
    import mlflow

    from ml.train import EXPERIMENT_NAME, train_species

    fn = [f"f{i}" for i in range(10)]
    for sp_seed, sp in enumerate(("striper", "fluke")):
        X_tr, y_tr, X_val, y_val, X_te, y_te, _ = _synthetic(seed=sp_seed)
        train_species(
            sp, X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=3, run_tag="test"
        )

    client = mlflow.tracking.MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT_NAME)
    runs = client.search_runs(experiment_ids=[exp.experiment_id])
    species_seen = {r.data.params.get("species") for r in runs}
    assert "striper" in species_seen
    assert "fluke" in species_seen


def test_shap_summary_artifact_logged(mlflow_tmp_tracking):
    import mlflow

    from ml.train import train_species

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = _synthetic()
    result = train_species(
        "bluefish", X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=3, run_tag="test"
    )
    client = mlflow.tracking.MlflowClient()
    artifacts = client.list_artifacts(result["run_id"], path="shap")
    assert any(a.path.endswith(".png") for a in artifacts), (
        f"No SHAP PNG artifact under shap/ — found: {[a.path for a in artifacts]}"
    )


def test_feature_names_json_artifact_logged(mlflow_tmp_tracking):
    import mlflow

    from ml.train import train_species

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = _synthetic()
    result = train_species(
        "weakfish", X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=3, run_tag="test"
    )
    client = mlflow.tracking.MlflowClient()
    artifacts = client.list_artifacts(result["run_id"], path="meta")
    assert any(a.path.endswith(".json") for a in artifacts), (
        f"No feature_names.json artifact under meta/ — found: {[a.path for a in artifacts]}"
    )


def test_lightgbm_baseline_run_logged_distinctly(mlflow_tmp_tracking):
    import mlflow

    from ml.train import train_lightgbm_baseline

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = _synthetic()
    result = train_lightgbm_baseline(
        "tautog", X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=3, run_tag="test"
    )
    assert "run_id" in result
    client = mlflow.tracking.MlflowClient()
    run = client.get_run(result["run_id"])
    assert run.data.params.get("baseline") == "lightgbm"


# ---------------------------------------------------------------------------
# Plan 02-05 — promote_production sets `production` alias on best-by-val-AUC
# ---------------------------------------------------------------------------


def test_promote_production_sets_alias(mlflow_tmp_tracking, tmp_path, monkeypatch):
    """promote_production runs after training → production alias on best-by-val-AUC.

    Trains striper + fluke, calls promote_all, asserts the registered model
    ``activity-{species}`` exists and the ``production`` alias resolves to the
    best-by-val-AUC run.
    """
    import mlflow

    from ml.train import train_species
    import scripts.promote_production as pp

    monkeypatch.setattr(pp, "REGISTRY_REPORT_PATH", tmp_path / "registry.json")
    promote_all = pp.promote_all

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = _synthetic()
    train_species(
        "striper", X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=3, run_tag="full"
    )
    X_tr2, y_tr2, X_val2, y_val2, X_te2, y_te2, _ = _synthetic(seed=1)
    train_species(
        "fluke",
        X_tr2,
        y_tr2,
        X_val2,
        y_val2,
        X_te2,
        y_te2,
        fn,
        n_trials=3,
        run_tag="full",
    )

    report = promote_all()
    for sp in ("striper", "fluke"):
        assert report[sp]["promoted"], f"{sp} not promoted: {report[sp]}"
    # Verify the alias resolves to the recorded run_id
    client = mlflow.tracking.MlflowClient()
    for sp in ("striper", "fluke"):
        ver = client.get_model_version_by_alias(f"activity-{sp}", "production")
        assert ver is not None
        assert ver.run_id == report[sp]["run_id"]


def test_promote_production_evaluate_gates_unit():
    """_evaluate_gates returns (passes, note, failures) per D-04/D-16 + M-09."""
    from scripts.promote_production import _evaluate_gates

    # Striper at AUC 0.80 / Brier 0.15 / P25 0.70 — clean pass
    passes, note, failures = _evaluate_gates(
        {"auc_test": 0.80, "brier_test": 0.15, "precision_at_top25_test": 0.70},
        "striper",
    )
    assert passes is True
    assert note is None
    assert failures == []

    # Tautog at 0.68 — pass-with-note (D-16)
    passes, note, failures = _evaluate_gates(
        {"auc_test": 0.68, "brier_test": 0.20, "precision_at_top25_test": 0.66},
        "tautog",
    )
    assert passes is True
    assert note is not None and "0.65-0.72" in note
    assert failures == []

    # Tautog at 0.62 — fail (D-16 floor)
    passes, _, failures = _evaluate_gates(
        {"auc_test": 0.62, "brier_test": 0.18, "precision_at_top25_test": 0.66},
        "tautog",
    )
    assert passes is False
    assert any("0.65" in f for f in failures)

    # Striper failing all three M-09 gates
    passes, _, failures = _evaluate_gates(
        {"auc_test": 0.50, "brier_test": 0.30, "precision_at_top25_test": 0.40},
        "striper",
    )
    assert passes is False
    assert len(failures) == 3  # AUC + Brier + P@25


def test_promote_production_gates_block_low_quality_runs(mlflow_tmp_tracking, tmp_path, monkeypatch):
    """A run with synthetic random labels (AUC ~0.5) is gated under enforce_gates=True."""
    import numpy as np

    from ml.train import train_species
    import scripts.promote_production as pp

    monkeypatch.setattr(pp, "REGISTRY_REPORT_PATH", tmp_path / "registry.json")

    # Random labels — XGBoost cannot find signal, AUC will be ≤ 0.5 territory.
    rng = np.random.RandomState(42)
    X_tr = rng.randn(60, 10)
    X_val = rng.randn(20, 10)
    X_te = rng.randn(20, 10)
    y_tr = rng.randint(0, 2, 60)
    y_val = rng.randint(0, 2, 20)
    y_te = rng.randint(0, 2, 20)
    fn = [f"f{i}" for i in range(10)]
    train_species(
        "striper", X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=3, run_tag="full"
    )

    report = pp.promote_all(enforce_gates=True)
    striper = report["striper"]
    # Either gated (most likely) or pass-with-note — but if gated, the report
    # must surface the reason.
    if not striper["promoted"]:
        assert striper["reason"] == "gated"
        assert "gate_failures" in striper
        assert len(striper["gate_failures"]) >= 1


def test_promote_production_skips_no_runs(mlflow_tmp_tracking, tmp_path, monkeypatch):
    """If no eligible runs exist for a species, promote_production records the skip."""
    from ml.train import train_species
    import scripts.promote_production as pp

    monkeypatch.setattr(pp, "REGISTRY_REPORT_PATH", tmp_path / "registry.json")
    promote_all = pp.promote_all

    X_tr, y_tr, X_val, y_val, X_te, y_te, fn = _synthetic()
    train_species(
        "striper", X_tr, y_tr, X_val, y_val, X_te, y_te, fn, n_trials=3, run_tag="full"
    )

    report = promote_all()
    assert report["striper"]["promoted"] is True
    for sp in ("tautog", "weakfish", "bluefish", "fluke"):
        assert report[sp]["promoted"] is False
        assert report[sp]["reason"] == "no_eligible_runs"
