"""Test fixtures shared by tests/tasks/* — re-exports MLflow tmp tracking +
migrated_ingest_db.

The MLflow tmp-tracking fixture lives in ``tests/ml/conftest.py`` (Plan 02-00
Wave 0 scaffolding). pytest only auto-applies a conftest within its own
package tree, so we re-export the fixture here for ``tests/tasks/`` files
(test_mlflow_run_structure, test_optuna_study, test_permutation_gate) that
exercise MLflow run logging.

Plan 02-07 adds ``migrated_ingest_db`` (also defined in tests/ml/conftest.py
and tests/integration/test_ingest_e2e.py). Re-exported here so the scorer
integration tests can run alembic against the shared Timescale container
without depending on tests/ml/ import-order quirks.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/


@pytest.fixture
def mlflow_tmp_tracking(tmp_path, monkeypatch):
    """Redirect MLflow tracking to a tmp dir per test (mirrors tests/ml fixture)."""
    uri = f"file://{tmp_path}/mlruns"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    import mlflow

    mlflow.set_tracking_uri(uri)
    return uri


def _run_alembic_upgrade(sync_url: str, async_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_SYNC_URL"] = sync_url
    env["DATABASE_URL"] = async_url
    env.setdefault("REDIS_URL", "redis://localhost:6379/0")
    subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
    )


@pytest.fixture(scope="module")
def migrated_ingest_db(timescale_sync_url, timescale_async_url) -> str:
    """Apply all migrations against the shared Timescale container (module-scoped)."""
    _run_alembic_upgrade(timescale_sync_url, timescale_async_url)
    return timescale_sync_url
