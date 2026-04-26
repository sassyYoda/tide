"""Test fixtures shared by tests/tasks/* — re-exports MLflow tmp tracking.

The MLflow tmp-tracking fixture lives in ``tests/ml/conftest.py`` (Plan 02-00
Wave 0 scaffolding). pytest only auto-applies a conftest within its own
package tree, so we re-export the fixture here for ``tests/tasks/`` files
(test_mlflow_run_structure, test_optuna_study, test_permutation_gate) that
exercise MLflow run logging.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def mlflow_tmp_tracking(tmp_path, monkeypatch):
    """Redirect MLflow tracking to a tmp dir per test (mirrors tests/ml fixture)."""
    uri = f"file://{tmp_path}/mlruns"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    import mlflow

    mlflow.set_tracking_uri(uri)
    return uri
