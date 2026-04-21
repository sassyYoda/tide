"""Integration test: `alembic upgrade head` against a real TimescaleDB container.

Asserts the load-bearing contracts of Phase 1 migrations:
  1. All four time-series hypertables exist
  2. `conditions_15min` CAGG has `materialized_only = false` (Pitfall #5)
  3. The 5-minute CAGG refresh policy is registered
  4. `fishing_spots.nearest_station` has a FK to `noaa_stations.station_id`
     (Pitfall #7)

Fixtures come from `backend/tests/conftest.py` (Plan 01):
  - `timescale_container`        — session-scoped PostgresContainer
  - `timescale_sync_url`         — postgresql+psycopg2://...
  - `timescale_async_url`        — postgresql+asyncpg://...
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/

EXPECTED_HYPERTABLES = {
    "tidal_observations",
    "weather_observations",
    "noaa_harmonic_forecasts",
    "solunar_values",
}


@pytest.fixture(scope="module")
def migrated_db(timescale_sync_url, timescale_async_url) -> str:
    """Run `alembic upgrade head` against the shared Timescale container."""
    env = os.environ.copy()
    env["DATABASE_SYNC_URL"] = timescale_sync_url
    env["DATABASE_URL"] = timescale_async_url
    env.setdefault("REDIS_URL", "redis://localhost:6379/0")
    subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
    )
    return timescale_sync_url


def test_upgrade_head_creates_all_hypertables(migrated_db: str) -> None:
    engine = sa.create_engine(migrated_db)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT hypertable_name FROM timescaledb_information.hypertables"
                )
            ).scalars().all()
    finally:
        engine.dispose()
    missing = EXPECTED_HYPERTABLES - set(rows)
    assert not missing, f"missing hypertables: {missing}"


def test_conditions_15min_cagg_is_realtime(migrated_db: str) -> None:
    engine = sa.create_engine(migrated_db)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    """
                    SELECT view_name, materialized_only
                    FROM timescaledb_information.continuous_aggregates
                    WHERE view_name = 'conditions_15min'
                    """
                )
            ).first()
    finally:
        engine.dispose()
    assert row is not None, "conditions_15min CAGG missing"
    assert row.materialized_only is False, (
        "CRITICAL: conditions_15min must have materialized_only = false "
        "(pitfall #5 — TimescaleDB 2.13+ default flipped to true)"
    )


def test_cagg_refresh_policy_exists(migrated_db: str) -> None:
    engine = sa.create_engine(migrated_db)
    try:
        with engine.connect() as conn:
            count = conn.execute(
                sa.text(
                    """
                    SELECT count(*)
                    FROM timescaledb_information.jobs
                    WHERE proc_name = 'policy_refresh_continuous_aggregate'
                      AND hypertable_name = 'conditions_15min'
                    """
                )
            ).scalar_one()
    finally:
        engine.dispose()
    assert count >= 1, "refresh policy not installed on conditions_15min"


def test_fishing_spots_fk_to_noaa_stations(migrated_db: str) -> None:
    engine = sa.create_engine(migrated_db)
    try:
        with engine.connect() as conn:
            fk_row = conn.execute(
                sa.text(
                    """
                    SELECT
                        tc.constraint_name,
                        kcu.column_name,
                        ccu.table_name AS ref_table,
                        ccu.column_name AS ref_col
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        USING (constraint_name, table_schema)
                    JOIN information_schema.constraint_column_usage ccu
                        USING (constraint_name, table_schema)
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_name = 'fishing_spots'
                      AND kcu.column_name = 'nearest_station'
                    """
                )
            ).first()
    finally:
        engine.dispose()
    assert fk_row is not None, "FK fishing_spots.nearest_station missing"
    assert fk_row.ref_table == "noaa_stations"
    assert fk_row.ref_col == "station_id"
