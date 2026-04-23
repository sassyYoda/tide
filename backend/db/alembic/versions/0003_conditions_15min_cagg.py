# Pitfall #5: materialized_only = false is NON-NEGOTIABLE. TimescaleDB 2.13+ flipped the default to true (real-time OFF). A redundant app-layer freshness gate lives in app/deps/freshness.py — but this setting is defense-in-depth layer 1.
"""0003 — conditions_15min continuous aggregate (tide-only).

The CAGG is the source of truth for the freshness gate (Plan 06). It MUST be
created with `materialized_only = false` so reads transparently fall back to
the raw hypertable for the trailing window the refresh policy has not yet
materialized.

Refresh policy: every 5 min rematerialize the last hour (start_offset=1h,
end_offset=5min). The 0–5min gap is served live from raw rows via
materialized_only=false.

Single-hypertable constraint: TimescaleDB continuous aggregates must reference
exactly one hypertable. The original design joined `tidal_observations` and
`weather_observations` which fails at CREATE MATERIALIZED VIEW with
`FeatureNotSupported: Only one hypertable is allowed in continuous aggregate
view`. Resolution: this CAGG aggregates tidal data only; the /conditions
endpoint joins against raw `weather_observations` at read time (Open-Meteo is
hourly, so read-side join is cheap).

Tide is the canonical freshness signal — NOAA posts water_level every 6 min
for active stations, so if tide is stale, ingest is broken. Weather staleness
is less operationally informative.
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
    # Single-hypertable (tidal_observations only) to satisfy CAGG constraint.
    op.execute(
        sa.text(
            """
            CREATE MATERIALIZED VIEW conditions_15min
            WITH (timescaledb.continuous, timescaledb.materialized_only = false)
            AS
            SELECT
                time_bucket('15 minutes', t.time)  AS bucket,
                t.station_id,
                last(t.water_level_m, t.time)      AS water_level_m,
                last(t.water_temp_c, t.time)       AS water_temp_c,
                count(t.*)                         AS tidal_obs_count
            FROM tidal_observations t
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
