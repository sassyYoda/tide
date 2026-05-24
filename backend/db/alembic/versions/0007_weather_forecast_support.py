"""0007 — weather forecast support: add is_forecast to weather_observations.

Extends ``weather_observations`` from observation-only to (observation +
hourly forecast) storage. The hourly forecast block from the same Open-Meteo
endpoint is shaped into rows with ``is_forecast = true``; the existing
``current`` block continues to write ``is_forecast = false``.

The boolean joins the primary key — without it, an observation and a forecast
at the same wall-clock hour would collide on ``session.merge()`` and one would
silently overwrite the other. With it, both can coexist; readers MUST filter
``is_forecast = false`` to retrieve actual observations (or
``is_forecast = true`` for forecast lookups).

TimescaleDB constraint: the partitioning column (``time``) must remain part of
every unique constraint on a hypertable, which the new PK satisfies.

Hand-written raw SQL — autogenerate is unused project-wide for Phase 1 (per
0001 docstring) and the PK swap below would not be expressed cleanly anyway.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_weather_forecast"
down_revision = "0006_activity_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the column with a default so existing rows backfill to FALSE.
    op.execute(
        sa.text(
            """
            ALTER TABLE weather_observations
                ADD COLUMN IF NOT EXISTS is_forecast BOOLEAN
                NOT NULL DEFAULT FALSE;
            """
        )
    )

    # 2. Swap the primary key: (station_id, time) → (station_id, time, is_forecast).
    # The TimescaleDB hypertable requires ``time`` to remain in the PK; including
    # the boolean is additive and preserves chunk-pruning semantics.
    op.execute(
        sa.text(
            """
            ALTER TABLE weather_observations
                DROP CONSTRAINT IF EXISTS weather_observations_pkey;
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE weather_observations
                ADD CONSTRAINT weather_observations_pkey
                PRIMARY KEY (station_id, time, is_forecast);
            """
        )
    )

    # 3. Partial index on observation-only rows so the hot "latest observation"
    # query (ORDER BY time DESC LIMIT 1 WHERE is_forecast = false) keeps the
    # tight scan it had pre-migration. The pre-existing
    # idx_weather_obs_station_time_desc still covers full-table scans.
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_weather_obs_station_time_obs_only
                ON weather_observations (station_id, time DESC)
                WHERE is_forecast = FALSE;
            """
        )
    )

    # 4. Index for forecast lookups by target time (data_fetcher will query
    # WHERE is_forecast = true AND station_id = :sid AND time = :target_hour).
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_weather_obs_station_time_forecast_only
                ON weather_observations (station_id, time)
                WHERE is_forecast = TRUE;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS idx_weather_obs_station_time_forecast_only;"
        )
    )
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS idx_weather_obs_station_time_obs_only;"
        )
    )
    # Delete forecast rows BEFORE narrowing the PK — leaving them in place
    # would create duplicate (station_id, time) keys when the boolean drops
    # out of the PK and break the constraint re-add.
    op.execute(
        sa.text("DELETE FROM weather_observations WHERE is_forecast = TRUE;")
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE weather_observations
                DROP CONSTRAINT IF EXISTS weather_observations_pkey;
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE weather_observations
                ADD CONSTRAINT weather_observations_pkey
                PRIMARY KEY (station_id, time);
            """
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE weather_observations DROP COLUMN IF EXISTS is_forecast;"
        )
    )
