"""ML test fixtures — MLflow tracking URI redirect + synthetic labels.

`mlflow_tmp_tracking` isolates each test to its own tmp_path so MLflow runs
don't bleed across tests. `synthetic_labels_df` is a deterministic labeled
DataFrame used by the leakage-guard and temporal-split stub tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def mlflow_tmp_tracking(tmp_path, monkeypatch):
    """Redirect MLflow tracking to a tmp dir per test."""
    uri = f"file://{tmp_path}/mlruns"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    import mlflow

    mlflow.set_tracking_uri(uri)
    return uri


@pytest.fixture
def synthetic_labels_df():
    """Deterministic synthetic labeled-session DataFrame for split/leakage tests."""
    import pandas as pd
    from datetime import datetime, timedelta, timezone

    rows = []
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(400):
        rows.append(
            {
                "spot_id": (i % 10) + 1,
                "species": ["striper", "fluke", "bluefish", "weakfish", "tautog"][i % 5],
                "label_time": base + timedelta(hours=i * 3),
                "y": i % 3 != 0,  # ~66% positive
            }
        )
    return pd.DataFrame(rows)
