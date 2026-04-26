"""M-14 — permutation importance gate surfaces leakage + computes solunar lift."""

from __future__ import annotations

import numpy as np
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV

try:
    from sklearn.frozen import FrozenEstimator  # type: ignore

    _HAS_FROZEN = True
except ImportError:  # pragma: no cover
    FrozenEstimator = None  # type: ignore
    _HAS_FROZEN = False


def _calibrate_prefit(base, X_val, y_val, method="sigmoid"):
    """Wrap CalibratedClassifierCV(cv='prefit') across sklearn 1.6 / 1.7+."""
    if _HAS_FROZEN:
        clf = CalibratedClassifierCV(FrozenEstimator(base), method=method)
    else:  # pragma: no cover
        clf = CalibratedClassifierCV(base, method=method, cv="prefit")
    clf.fit(X_val, y_val)
    return clf


def _make_model_with_leakage_feature(n_tr: int = 200, n_te: int = 100):
    """Build a model where ``water_temp_lag_1h`` IS the label (perfect leakage).

    The label is generated from feature_5 directly so that feature dominates
    permutation importance. Other features carry pure noise — XGBoost will
    learn to use feature_5 almost exclusively.

    Returns ``(calibrated_model, X_te, y_te, feature_names)`` ready for the gate.
    """
    rng = np.random.RandomState(0)
    # All inputs random noise...
    X_tr = rng.randn(n_tr, 10)
    X_te = rng.randn(n_te, 10)
    # ... except feature_5, which IS the label (with tiny jitter).
    y_tr = (rng.randn(n_tr) > 0).astype(int)
    y_te = (rng.randn(n_te) > 0).astype(int)
    X_tr[:, 5] = y_tr + rng.randn(n_tr) * 0.01
    X_te[:, 5] = y_te + rng.randn(n_te) * 0.01
    feature_names = [f"f{i}" for i in range(10)]
    feature_names[5] = "water_temp_lag_1h"  # _is_temporal_feature → True
    model = xgb.XGBClassifier(n_estimators=50, max_depth=3, tree_method="hist", n_jobs=-1)
    model.fit(X_tr, y_tr)
    calibrated = _calibrate_prefit(model, X_tr, y_tr, method="sigmoid")
    return calibrated, X_te, y_te, feature_names


def test_permutation_gate_surfaces_leakage_feature():
    from ml.train import leakage_and_solunar_check

    calibrated, X_te, y_te, fn = _make_model_with_leakage_feature()
    gate = leakage_and_solunar_check(calibrated, X_te, y_te, fn)
    assert "water_temp_lag_1h" in gate["leakage_flags"], (
        f"Gate failed to surface leakage; top features: {gate['top_features']}"
    )


def test_permutation_gate_reports_solunar_lift_sum():
    from ml.train import leakage_and_solunar_check

    calibrated, X_te, y_te, fn = _make_model_with_leakage_feature()
    fn[-1] = "moon_phase_sin"
    fn[-2] = "illumination"
    gate = leakage_and_solunar_check(calibrated, X_te, y_te, fn)
    assert "solunar_total_auc_lift" in gate
    assert isinstance(gate["solunar_total_auc_lift"], float)


def test_is_temporal_feature_detects_lag_and_delta():
    from ml.train import _is_temporal_feature

    assert _is_temporal_feature("water_temp_lag_3h")
    assert _is_temporal_feature("pressure_delta_6h")
    assert not _is_temporal_feature("moon_phase_sin")
    assert not _is_temporal_feature("spot_is_jetty")
