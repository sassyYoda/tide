"""Per-species XGBoost training driver (M-06, M-07, M-13, OPS-07).

Cycle per species:
  1. Optuna TPE sweep on train/val → best params
  2. Refit base XGBClassifier on best params
  3. CalibratedClassifierCV(cv='prefit') on val fold (Pitfall #2)
  4. Evaluate on test fold — AUC, Brier, P@Top25%
  5. SHAP summary plot artifact (per-species qualitative check)
  6. Permutation-importance gate on test fold (Pitfall #9)
  7. MLflow run: params, metrics, artifacts, SHAP

LightGBM baseline (M-06) is logged as a separate distinct MLflow run per
species with a reduced 20-trial Optuna budget — same split, same features.
"""
from __future__ import annotations

import json
import logging
import tempfile
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import mlflow.sklearn  # noqa: E402
import mlflow.xgboost  # noqa: E402
import numpy as np  # noqa: E402
import optuna  # noqa: E402
import shap  # noqa: E402
import xgboost as xgb  # noqa: E402
from sklearn.calibration import CalibratedClassifierCV  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import brier_score_loss, roc_auc_score  # noqa: E402

# CalibratedClassifierCV API note: scikit-learn 1.7 removed the literal
# ``cv="prefit"`` keyword in favor of wrapping the already-fitted estimator
# in ``FrozenEstimator``. Functionally identical: validation-fold-only
# calibration of a base estimator that has already seen the train fold.
# We keep the original ``cv="prefit"`` semantics by importing FrozenEstimator
# when available and falling back to the old kwarg on sklearn<1.7.
try:  # pragma: no cover - branch picked once at import
    from sklearn.frozen import FrozenEstimator  # type: ignore

    _HAS_FROZEN = True
except ImportError:  # sklearn < 1.7
    FrozenEstimator = None  # type: ignore
    _HAS_FROZEN = False

from ml.labels import compute_scale_pos_weight  # noqa: E402

log = logging.getLogger(__name__)

EXPERIMENT_NAME = "tide-activity-model"

SOLUNAR_FEATURE_NAMES = {
    "moon_phase_sin",
    "moon_phase_cos",
    "illumination",
    "lunar_day",
    "solunar_quality",
    "is_major_period",
    "hours_to_next_major",
}

# Substrings that mark a feature as backward-looking (lag/delta/rolling).
# Used by the leakage gate to decide whether a high-permutation-importance
# feature should be flagged as a possible leak.
TEMPORAL_LAG_KEYWORDS = ("_lag_", "_delta_", "rolling")


def _is_temporal_feature(name: str) -> bool:
    return any(kw in name for kw in TEMPORAL_LAG_KEYWORDS)


def _precision_at_top_k(y_true: np.ndarray, proba: np.ndarray, frac: float = 0.25) -> float:
    n_top = max(int(len(proba) * frac), 1)
    top_idx = np.argsort(-proba)[:n_top]
    return float(np.asarray(y_true)[top_idx].mean())


def objective_for_species(
    trial: optuna.Trial,
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    scale_pos_weight: float,
) -> float:
    """Optuna objective — return validation AUC-ROC (M-07).

    Search space matches PRD §6.2 FR-M3 + 02-RESEARCH Pattern 3 verbatim.
    """
    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "scale_pos_weight": scale_pos_weight,
        "n_estimators": trial.suggest_int("n_estimators", 200, 1500, step=100),
        "max_depth": trial.suggest_int("max_depth", 3, 10),
        "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        "gamma": trial.suggest_float("gamma", 0.0, 5.0),
        "tree_method": "hist",
        "n_jobs": -1,
    }
    clf = xgb.XGBClassifier(**params, early_stopping_rounds=50)
    clf.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
    return float(roc_auc_score(y_val, clf.predict_proba(X_val)[:, 1]))


def leakage_and_solunar_check(
    calibrated_clf,
    X_te: np.ndarray,
    y_te: np.ndarray,
    feature_names: list[str],
) -> dict:
    """Permutation-importance gate on TEST fold only (Pitfall #9).

    Returns:
        ``{"top_features": [(name, mean_drop), ...top-5...],
            "leakage_flags": [names with drop > 0.20 AND temporal-lag feature],
            "solunar_total_auc_lift": sum of mean_drop over solunar feature names}``
    """
    r = permutation_importance(
        calibrated_clf,
        X_te,
        y_te,
        n_repeats=10,
        random_state=42,
        scoring="roc_auc",
        n_jobs=-1,
    )
    ranked = sorted(
        [(n, float(r.importances_mean[i])) for i, n in enumerate(feature_names)],
        key=lambda kv: -kv[1],
    )
    top_5 = ranked[:5]
    leakage_flags = [n for n, d in top_5 if d > 0.20 and _is_temporal_feature(n)]
    solunar_lift = sum(
        float(r.importances_mean[feature_names.index(n)])
        for n in SOLUNAR_FEATURE_NAMES
        if n in feature_names
    )
    return {
        "top_features": top_5,
        "leakage_flags": leakage_flags,
        "solunar_total_auc_lift": solunar_lift,
    }


def _log_shap_summary(model, X_tr: np.ndarray, species: str, feature_names: list[str]) -> None:
    """Save a SHAP summary plot to a tmp file and log as MLflow artifact."""
    explainer = shap.TreeExplainer(model)
    vals = explainer.shap_values(X_tr)
    if isinstance(vals, list):
        vals = vals[1] if len(vals) > 1 else vals[0]
    fig = plt.figure()
    shap.summary_plot(vals, X_tr, feature_names=feature_names, show=False)
    with tempfile.NamedTemporaryFile(suffix=f"_shap_{species}.png", delete=False) as f:
        fig.savefig(f.name, bbox_inches="tight", dpi=120)
        plt.close(fig)
        mlflow.log_artifact(f.name, artifact_path="shap")


def train_species(
    species: str,
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    X_te: np.ndarray,
    y_te: np.ndarray,
    feature_names: list[str],
    n_trials: int = 60,
    run_tag: str = "subset",
) -> dict[str, Any]:
    """Train one species end-to-end. Returns dict of run metadata.

    On empty fold the run is logged with ``skip_reason=empty_fold`` and
    ``{"skipped": True, "run_id": ...}`` is returned without raising.
    """
    mlflow.set_experiment(EXPERIMENT_NAME)
    with mlflow.start_run(run_name=f"{species}_{run_tag}") as run:
        n_tr = int(len(y_tr))
        n_val = int(len(y_val))
        n_te = int(len(y_te))
        if n_tr == 0 or n_val == 0 or n_te == 0:
            log.warning(
                "%s: empty fold (tr=%d, val=%d, te=%d) — skipping",
                species,
                n_tr,
                n_val,
                n_te,
            )
            mlflow.log_params({"species": species, "skip_reason": "empty_fold"})
            return {"skipped": True, "run_id": run.info.run_id}

        # Guard against degenerate single-class folds (Optuna AUC undefined)
        if len(set(y_tr.tolist())) < 2 or len(set(y_val.tolist())) < 2 or len(set(y_te.tolist())) < 2:
            log.warning(
                "%s: single-class fold detected — skipping. tr=%s val=%s te=%s",
                species,
                set(y_tr.tolist()),
                set(y_val.tolist()),
                set(y_te.tolist()),
            )
            mlflow.log_params({"species": species, "skip_reason": "single_class_fold"})
            return {"skipped": True, "run_id": run.info.run_id}

        spw = compute_scale_pos_weight(y_tr)
        method = "isotonic" if n_val >= 500 else "sigmoid"
        mlflow.log_params(
            {
                "species": species,
                "run_tag": run_tag,
                "n_trials": n_trials,
                "n_labels_train": n_tr,
                "n_labels_val": n_val,
                "n_labels_test": n_te,
                "scale_pos_weight": spw,
                "calibration_method": method,
            }
        )

        # ---- Optuna TPE sweep --------------------------------------------------
        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        study.optimize(
            lambda t: objective_for_species(t, X_tr, y_tr, X_val, y_val, spw),
            n_trials=n_trials,
            show_progress_bar=False,
        )
        best_params = {
            **study.best_params,
            "scale_pos_weight": spw,
            "objective": "binary:logistic",
            "eval_metric": "auc",
            "tree_method": "hist",
            "n_jobs": -1,
        }
        mlflow.log_params({f"best_{k}": v for k, v in study.best_params.items()})

        # ---- Refit base + CalibratedClassifierCV(cv="prefit") -----------------
        # PITFALL #2: calibration must be fit on the validation fold ONLY,
        # treating the base estimator as already fitted (no resplitting).
        # Modern sklearn expresses this with FrozenEstimator; legacy API used
        # the cv="prefit" keyword. Both produce identical isotonic/sigmoid fits.
        base = xgb.XGBClassifier(**best_params, early_stopping_rounds=50)
        base.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)

        if _HAS_FROZEN:
            calibrated = CalibratedClassifierCV(FrozenEstimator(base), method=method)
        else:  # pragma: no cover - legacy sklearn path
            calibrated = CalibratedClassifierCV(base, method=method, cv="prefit")
        calibrated.fit(X_val, y_val)

        # ---- Evaluate ----------------------------------------------------------
        auc_val = float(roc_auc_score(y_val, calibrated.predict_proba(X_val)[:, 1]))
        proba_te = calibrated.predict_proba(X_te)[:, 1]
        auc_test = float(roc_auc_score(y_te, proba_te))
        brier_test = float(brier_score_loss(y_te, proba_te))
        p_at_25 = _precision_at_top_k(y_te, proba_te, frac=0.25)

        gate = leakage_and_solunar_check(calibrated, X_te, y_te, feature_names)

        mlflow.log_metrics(
            {
                "auc_val": auc_val,
                "auc_test": auc_test,
                "brier_test": brier_test,
                "precision_at_top25_test": p_at_25,
                "solunar_total_auc_lift": gate["solunar_total_auc_lift"],
                "calibration_method_code": 1 if method == "isotonic" else 0,
                "n_leakage_flags": len(gate["leakage_flags"]),
            }
        )
        # Log permutation top-5 + leakage flags as a JSON artifact
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "top_features": gate["top_features"],
                    "leakage_flags": gate["leakage_flags"],
                },
                f,
                indent=2,
            )
            mlflow.log_artifact(f.name, artifact_path="permutation")

        # ---- Log models --------------------------------------------------------
        try:
            mlflow.xgboost.log_model(base, artifact_path=f"model_{species}")
        except Exception as e:  # pragma: no cover - mlflow API drift
            log.exception("%s: xgboost log_model failed: %s", species, e)
            mlflow.set_tag("xgboost_log_error", str(e)[:200])
        try:
            mlflow.sklearn.log_model(calibrated, artifact_path=f"calibrated_{species}")
        except Exception as e:  # pragma: no cover
            log.exception("%s: sklearn log_model failed: %s", species, e)
            mlflow.set_tag("sklearn_log_error", str(e)[:200])

        # Log feature_names.json — consumed by Plan 07 inference loader
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {"feature_names": feature_names, "model_version": run.info.run_id[:12]},
                f,
            )
            mlflow.log_artifact(f.name, artifact_path="meta")

        # SHAP summary artifact (qualitative per-species check)
        try:
            _log_shap_summary(base, X_tr, species, feature_names)
        except Exception as e:
            log.exception("%s: SHAP summary failed: %s", species, e)
            mlflow.set_tag("shap_summary_error", str(e)[:200])

        return {
            "run_id": run.info.run_id,
            "auc_val": auc_val,
            "auc_test": auc_test,
            "brier_test": brier_test,
            "p_at_25_test": p_at_25,
            "calibration_method": method,
            "leakage_flags": gate["leakage_flags"],
            "solunar_lift": gate["solunar_total_auc_lift"],
        }


def train_lightgbm_baseline(
    species: str,
    X_tr,
    y_tr,
    X_val,
    y_val,
    X_te,
    y_te,
    feature_names: list[str],
    n_trials: int = 20,
    run_tag: str = "subset",
) -> dict[str, Any]:
    """M-06 LightGBM baseline — per-species, reduced Optuna budget (Open Q #5).

    Same temporal split + features; logs a distinct MLflow run named
    ``{species}_lightgbm_baseline_{run_tag}`` under EXPERIMENT_NAME.
    """
    import lightgbm as lgb

    mlflow.set_experiment(EXPERIMENT_NAME)
    with mlflow.start_run(run_name=f"{species}_lightgbm_baseline_{run_tag}") as run:
        n_tr, n_val, n_te = len(y_tr), len(y_val), len(y_te)
        if min(n_tr, n_val, n_te) == 0:
            mlflow.log_params({"species": species, "skip_reason": "empty_fold", "baseline": "lightgbm"})
            return {"skipped": True, "run_id": run.info.run_id}
        if (
            len(set(np.asarray(y_tr).tolist())) < 2
            or len(set(np.asarray(y_val).tolist())) < 2
            or len(set(np.asarray(y_te).tolist())) < 2
        ):
            mlflow.log_params(
                {"species": species, "skip_reason": "single_class_fold", "baseline": "lightgbm"}
            )
            return {"skipped": True, "run_id": run.info.run_id}

        spw = compute_scale_pos_weight(y_tr)

        def _obj(trial):
            params = {
                "objective": "binary",
                "metric": "auc",
                "is_unbalance": False,
                "scale_pos_weight": spw,
                "num_leaves": trial.suggest_int("num_leaves", 15, 127),
                "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
                "n_estimators": trial.suggest_int("n_estimators", 200, 800, step=100),
                "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
                "verbose": -1,
            }
            clf = lgb.LGBMClassifier(**params)
            clf.fit(
                X_tr,
                y_tr,
                eval_set=[(X_val, y_val)],
                callbacks=[lgb.early_stopping(50, verbose=False)],
            )
            return float(roc_auc_score(y_val, clf.predict_proba(X_val)[:, 1]))

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        study.optimize(_obj, n_trials=n_trials, show_progress_bar=False)
        best = {
            **study.best_params,
            "scale_pos_weight": spw,
            "objective": "binary",
            "metric": "auc",
            "verbose": -1,
        }
        final = lgb.LGBMClassifier(**best)
        final.fit(
            X_tr,
            y_tr,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )
        auc_test = float(roc_auc_score(y_te, final.predict_proba(X_te)[:, 1]))
        mlflow.log_params(
            {
                "species": species,
                "run_tag": run_tag,
                "n_trials": n_trials,
                "baseline": "lightgbm",
            }
        )
        mlflow.log_params({f"best_{k}": v for k, v in study.best_params.items()})
        mlflow.log_metrics({"auc_test": auc_test})
        return {"run_id": run.info.run_id, "auc_test": auc_test}


__all__ = [
    "EXPERIMENT_NAME",
    "SOLUNAR_FEATURE_NAMES",
    "TEMPORAL_LAG_KEYWORDS",
    "objective_for_species",
    "train_species",
    "train_lightgbm_baseline",
    "leakage_and_solunar_check",
    "_is_temporal_feature",
    "_precision_at_top_k",
]
