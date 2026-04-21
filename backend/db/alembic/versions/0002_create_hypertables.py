"""0002 — convert four time-series tables into TimescaleDB hypertables.

`create_hypertable(..., if_not_exists => TRUE)` so the migration is idempotent.
Space partitioning (`by_hash('station_id', 4)`) is added to the two high-rate
observation tables to improve chunk pruning for per-station reads (CAGG scans).

Compression policies are deferred to Phase 6 — at MVP volumes (~50k rows/month
per hypertable), uncompressed storage is trivial and compression adds
query-time decompression overhead + chunk-freeze gotchas.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_hypertables"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 4 hypertables — by_range() is the TimescaleDB 2.x idiomatic form
    op.execute(
        sa.text(
            """
            SELECT create_hypertable(
                'tidal_observations',
                by_range('time', INTERVAL '7 days'),
                if_not_exists => TRUE
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            SELECT create_hypertable(
                'weather_observations',
                by_range('time', INTERVAL '7 days'),
                if_not_exists => TRUE
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            SELECT create_hypertable(
                'noaa_harmonic_forecasts',
                by_range('issued_at', INTERVAL '7 days'),
                if_not_exists => TRUE
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            SELECT create_hypertable(
                'solunar_values',
                by_range('time', INTERVAL '30 days'),
                if_not_exists => TRUE
            );
            """
        )
    )

    # Space dimension (hash on station_id) improves pruning for the CAGG reads.
    op.execute(
        sa.text(
            """
            SELECT add_dimension(
                'tidal_observations',
                by_hash('station_id', 4),
                if_not_exists => TRUE
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            SELECT add_dimension(
                'weather_observations',
                by_hash('station_id', 4),
                if_not_exists => TRUE
            );
            """
        )
    )

    # Indexes for CAGG materialization and point reads
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_tidal_obs_station_time_desc
                ON tidal_observations(station_id, time DESC);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_weather_obs_station_time_desc
                ON weather_observations(station_id, time DESC);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_solunar_station_time_desc
                ON solunar_values(station_id, time DESC);
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_noaa_forecasts_target_time
                ON noaa_harmonic_forecasts(station_id, target_time);
            """
        )
    )


def downgrade() -> None:
    # No-op: hypertable metadata is destroyed when the parent table is dropped
    # (handled in 0001 downgrade via DROP TABLE ... CASCADE).
    pass
