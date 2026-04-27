"""M-12 — inference ≤ 50ms p95 over 100 predictions on a warmed-up process.

The plan's M-12 requirement is "≤50ms per prediction on a warmed-up worker".
This test fits a small CalibratedClassifierCV on synthetic data (we only need
a real sklearn estimator to measure call overhead), warms the JIT, then
measures p95 of 100 single-row ``predict_proba`` calls.

Marked ``slow`` (excluded from the Nyquist quick suite) because fitting + 100
predictions takes ~2-3 seconds.
"""
from __future__ import annotations

import time

import numpy as np
import pytest
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV

# scikit-learn 1.7+ removed the literal cv="prefit" keyword in favor of
# wrapping an already-fitted estimator in FrozenEstimator. ml.train uses
# the same shim — keep the test mirror in sync.
try:
    from sklearn.frozen import FrozenEstimator  # type: ignore
except ImportError:  # pragma: no cover — older sklearn
    FrozenEstimator = None  # type: ignore

pytestmark = pytest.mark.slow


def test_inference_latency_under_50ms_p95():
    rng = np.random.RandomState(0)
    n_feat = 50
    X_tr = rng.randn(500, n_feat)
    y_tr = (rng.randn(500) > 0).astype(int)

    base = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        tree_method="hist",
        n_jobs=-1,
        eval_metric="logloss",
    )
    base.fit(X_tr, y_tr)
    if FrozenEstimator is not None:
        calibrated = CalibratedClassifierCV(
            FrozenEstimator(base), method="sigmoid", cv=2
        )
    else:  # pragma: no cover
        calibrated = CalibratedClassifierCV(base, method="sigmoid", cv="prefit")
    calibrated.fit(X_tr, y_tr)

    # Warm-up — first call triggers any lazy JIT / numpy buffer caching.
    for _ in range(10):
        calibrated.predict_proba(X_tr[:1])

    latencies_ms: list[float] = []
    for i in range(100):
        t0 = time.perf_counter()
        calibrated.predict_proba(X_tr[i : i + 1])
        latencies_ms.append((time.perf_counter() - t0) * 1000)
    p95 = float(np.percentile(latencies_ms, 95))
    assert p95 <= 50.0, f"p95 latency {p95:.2f}ms > 50ms (M-12 gate failed)"
