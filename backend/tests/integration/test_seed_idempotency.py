"""Integration test: seed migrations load, are idempotent, and preserve FK integrity.

Runs `alembic upgrade head` against the shared Timescale testcontainer and
asserts:

  1. ``test_seed_migration_populates`` — >=8 NOAA stations and >=25 fishing
     spots are materialized after the migration chain finishes.
  2. ``test_seed_migration_idempotent`` — re-running ``alembic upgrade head``
     does not change row counts (upsert is a no-op on identical data).
  3. ``test_fishing_spots_fk_valid`` — every ``fishing_spots.nearest_station``
     value resolves to an existing ``noaa_stations.station_id`` (pitfall #7).
  4. ``test_unknown_json_keys_not_materialized`` — audit-only JSON fields
     (e.g., the rationale text preserved in the committed seed JSON) are
     silently dropped by the column whitelist and never become table columns.

Reuses the session-scoped ``timescale_sync_url`` / ``timescale_async_url``
fixtures from ``backend/tests/conftest.py``.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/


def _run_alembic_upgrade(sync_url: str, async_url: str) -> None:
    """Invoke ``alembic upgrade head`` in a subprocess with the URL env set."""
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
def seeded_db(timescale_sync_url, timescale_async_url) -> str:
    _run_alembic_upgrade(timescale_sync_url, timescale_async_url)
    return timescale_sync_url


def test_seed_migration_populates(seeded_db: str) -> None:
    engine = sa.create_engine(seeded_db)
    try:
        with engine.connect() as conn:
            n_stations = conn.execute(
                sa.text("SELECT count(*) FROM noaa_stations")
            ).scalar_one()
            n_spots = conn.execute(
                sa.text("SELECT count(*) FROM fishing_spots")
            ).scalar_one()
    finally:
        engine.dispose()
    assert n_stations >= 8, f"expected >=8 stations, got {n_stations}"
    assert n_spots >= 25, f"expected >=25 fishing spots, got {n_spots}"


def test_seed_migration_idempotent(seeded_db: str, timescale_async_url: str) -> None:
    engine = sa.create_engine(seeded_db)
    try:
        with engine.connect() as conn:
            n_stations_1 = conn.execute(
                sa.text("SELECT count(*) FROM noaa_stations")
            ).scalar_one()
            n_spots_1 = conn.execute(
                sa.text("SELECT count(*) FROM fishing_spots")
            ).scalar_one()

        # Re-run upgrade against the already-populated DB. Schema is at head
        # so this is a no-op there; data migrations upsert without duplicates.
        _run_alembic_upgrade(seeded_db, timescale_async_url)

        with engine.connect() as conn:
            n_stations_2 = conn.execute(
                sa.text("SELECT count(*) FROM noaa_stations")
            ).scalar_one()
            n_spots_2 = conn.execute(
                sa.text("SELECT count(*) FROM fishing_spots")
            ).scalar_one()
    finally:
        engine.dispose()

    assert n_stations_1 == n_stations_2, (
        f"re-run changed station count ({n_stations_1} -> {n_stations_2}) — not idempotent"
    )
    assert n_spots_1 == n_spots_2, (
        f"re-run changed spot count ({n_spots_1} -> {n_spots_2}) — not idempotent"
    )


def test_fishing_spots_fk_valid(seeded_db: str) -> None:
    engine = sa.create_engine(seeded_db)
    try:
        with engine.connect() as conn:
            orphans = conn.execute(
                sa.text(
                    """
                    SELECT fs.spot_id, fs.name, fs.nearest_station
                    FROM fishing_spots fs
                    LEFT JOIN noaa_stations ns
                        ON ns.station_id = fs.nearest_station
                    WHERE ns.station_id IS NULL
                    """
                )
            ).fetchall()
    finally:
        engine.dispose()
    assert not orphans, f"FK orphans: {orphans}"


def test_unknown_json_keys_not_materialized(seeded_db: str) -> None:
    """Audit-only JSON fields must not leak into the table schema.

    The seed JSON carries rationale text for auditability, but the migration
    binds a fixed column list — so the extra keys never reach the DB. If they
    somehow did, they would show up in ``information_schema.columns`` below.
    """
    engine = sa.create_engine(seeded_db)
    try:
        with engine.connect() as conn:
            cols = (
                conn.execute(
                    sa.text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = 'fishing_spots'
                        """
                    )
                )
                .scalars()
                .all()
            )
    finally:
        engine.dispose()
    assert "orientation_rationale" not in cols
    assert "source_url" not in cols
