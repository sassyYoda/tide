# Pitfall #5: materialized_only = false is NON-NEGOTIABLE. TimescaleDB 2.13+ flipped the default to true (real-time OFF). A redundant app-layer freshness gate lives in app/deps/freshness.py — but this setting is defense-in-depth layer 1.
"""0003 — conditions_15min continuous aggregate.

The CAGG is the source of truth for the freshness gate (Plan 06) and every
downstream Phase 2/3 consumer. It MUST be created with `materialized_only =
false` so reads transparently fall back to the raw hypertables for the
trailing window the refresh policy has not yet materialized.

Refresh policy: every 5 min rematerialize the last hour (start_offset=1h,
end_offset=5min). The 0–5min gap is served live from raw rows via
materialized_only=false.

Join choice: `LEFT JOIN weather` on tide — TimescaleDB CAGGs only support
INNER and LEFT joins, not FULL OUTER. Tide is the primary because NOAA posts
water_level every 6 min for active stations, so 15-min buckets effectively
always have a tide row; a weather-only bucket (no tide in that window) would
be rare and is acceptably dropped at MVP.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_cagg"
down_revision = "0002_hypertables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the CAGG with NO DATA — the refresh policy below populates it.
    # materialized_only = false is REQUIRED (Pitfall #5).
    op.execute(
        sa.text(
            """
            CREATE MATERIALIZED VIEW conditions_15min
            WITH (timescaledb.continuous, timescaledb.materialized_only = false)
            AS
            SELECT
                time_bucket('15 minutes', t.time)        AS bucket,
                t.station_id,
                last(t.water_level_m, t.time)            AS water_level_m,
                last(t.water_temp_c, t.time)             AS water_temp_c,
                last(w.wind_speed_ms, w.time)            AS wind_speed_ms,
                last(w.wind_dir_deg, w.time)             AS wind_dir_deg,
                last(w.surface_pressure_hpa, w.time)     AS surface_pressure_hpa,
                last(w.temperature_2m_c, w.time)         AS air_temperature_c,
                last(w.precipitation_prob_pct, w.time)   AS precipitation_prob_pct,
                last(w.cloud_cover_pct, w.time)          AS cloud_cover_pct,
                count(t.*)                               AS tidal_obs_count,
                count(w.*)                               AS weather_obs_count
            FROM tidal_observations t
            LEFT JOIN weather_observations w
                ON w.station_id = t.station_id
                AND time_bucket('15 minutes', w.time) = time_bucket('15 minutes', t.time)
            GROUP BY bucket, t.station_id
            WITH NO DATA;
            """
        )
    )

    # Refresh policy: every 5 min rematerialize the trailing 1h.
    op.execute(
        sa.text(
            """
            SELECT add_continuous_aggregate_policy(
                'conditions_15min',
                start_offset => INTERVAL '1 hour',
                end_offset   => INTERVAL '5 minutes',
                schedule_interval => INTERVAL '5 minutes'
            );
            """
        )
    )

    # Index for (station_id, bucket DESC) point reads from /conditions.
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_conditions_15min_station_bucket_desc
                ON conditions_15min(station_id, bucket DESC);
            """
        )
    )


def downgrade() -> None:
    # DROP MATERIALIZED VIEW ... CASCADE removes the refresh policy job and index.
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS conditions_15min CASCADE;"))
