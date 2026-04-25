"""ML test fixtures — MLflow tracking URI redirect + synthetic labels.

`mlflow_tmp_tracking` isolates each test to its own tmp_path so MLflow runs
don't bleed across tests. `synthetic_labels_df` is a deterministic labeled
DataFrame used by the leakage-guard and temporal-split stub tests.
`migrated_ingest_db` (Plan 02) applies all Alembic migrations to the shared
Timescale testcontainer so leakage-guard integration tests can seed
real environmental rows.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def mlflow_tmp_tracking(tmp_path, monkeypatch):
    """Redirect MLflow tracking to a tmp dir per test."""
    uri = f"file://{tmp_path}/mlruns"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    import mlflow

    mlflow.set_tracking_uri(uri)
    return uri


BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/


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
    """Apply all migrations against the shared Timescale container.

    Mirrors the fixture defined in ``tests/integration/test_ingest_e2e.py``;
    duplicated here so ml integration tests don't depend on import-order
    quirks of the integration package.
    """
    _run_alembic_upgrade(timescale_sync_url, timescale_async_url)
    return timescale_sync_url


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
