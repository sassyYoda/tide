"""SHAP top-k feature attribution (M-10).

TreeExplainer operates on the UNCALIBRATED base XGBoost model — SHAP reads
the tree structure directly. For final ranking the model's absolute SHAP
magnitudes are what matter; sign indicates direction of effect.
"""
from __future__ import annotations

import numpy as np
import shap


def top_k_shap(model, X_row: np.ndarray, feature_names: list[str], k: int = 3) -> list[dict]:
    """Top-k features by |SHAP| for a single prediction.

    Args:
        model: uncalibrated xgb.XGBClassifier (SHAP TreeExplainer needs raw tree).
        X_row: 1-D numpy array of feature values in FEATURE_NAMES order.
        feature_names: feature-column list (FEATURE_NAMES from ml.features).
        k: number of top features.

    Returns:
        [{"feature": name, "value": signed_shap_float}, ...] length k, sorted
        by absolute magnitude descending. ``value`` sign indicates direction.
    """
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X_row.reshape(1, -1))
    if isinstance(shap_vals, list):
        shap_vals = shap_vals[1] if len(shap_vals) > 1 else shap_vals[0]
    shap_vals = np.asarray(shap_vals).squeeze()
    abs_vals = np.abs(shap_vals)
    top_idx = np.argsort(-abs_vals)[:k]
    return [{"feature": feature_names[i], "value": float(shap_vals[i])} for i in top_idx]


__all__ = ["top_k_shap"]
