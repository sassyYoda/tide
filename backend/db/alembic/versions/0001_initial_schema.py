"""0001 — initial schema: CREATE EXTENSION timescaledb + all regular + observation tables.

Hand-written raw SQL (autogenerate is not used for Phase 1 — it cannot represent
TimescaleDB hypertables or continuous aggregates). Each `op.execute` call is
isolated so failures point to a specific statement.

Tables created here are all "regular" Postgres tables at this point. Migration
0002 hypertablizes the four time-series tables via `create_hypertable()`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. TimescaleDB extension
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))

    # 2. noaa_stations — master data (NOAA CO-OPS stations)
    op.execute(
        sa.text(
            """
            CREATE TABLE noaa_stations (
                station_id      TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                lat             DOUBLE PRECISION NOT NULL,
                lon             DOUBLE PRECISION NOT NULL,
                products        TEXT[] NOT NULL,
                source_url      TEXT NOT NULL,
                inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )

    # 3. fishing_spots — curated spots, FK -> noaa_stations (Pitfall #7)
    op.execute(
        sa.text(
            """
            CREATE TABLE fishing_spots (
                spot_id         BIGSERIAL PRIMARY KEY,
                name            TEXT NOT NULL,
                lat             DOUBLE PRECISION NOT NULL,
                lon             DOUBLE PRECISION NOT NULL,
                water_body      TEXT NOT NULL,
                spot_type       TEXT NOT NULL,
                depth_ft        DOUBLE PRECISION,
                species         TEXT[] NOT NULL,
                nearest_station TEXT NOT NULL REFERENCES noaa_stations(station_id),
                orientation_deg DOUBLE PRECISION,
                access_type     TEXT NOT NULL CHECK (access_type IN ('shore','boat','kayak')),
                inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )

    # 4-5. Indexes on fishing_spots
    op.execute(
        sa.text(
            "CREATE INDEX idx_fishing_spots_nearest_station ON fishing_spots(nearest_station);"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX idx_fishing_spots_species_gin ON fishing_spots USING GIN(species);"
        )
    )

    # 6. tidal_observations — NOAA CO-OPS 6-min cadence (hypertable in 0002)
    op.execute(
        sa.text(
            """
            CREATE TABLE tidal_observations (
                station_id        TEXT NOT NULL REFERENCES noaa_stations(station_id),
                time              TIMESTAMPTZ NOT NULL,
                water_level_m     DOUBLE PRECISION,
                water_temp_c      DOUBLE PRECISION,
                wind_speed_ms     DOUBLE PRECISION,
                wind_dir_deg      DOUBLE PRECISION,
                current_speed_ms  DOUBLE PRECISION,
                current_dir_deg   DOUBLE PRECISION,
                source            TEXT NOT NULL DEFAULT 'noaa',
                raw_payload JSONB NOT NULL,
                inserted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (station_id, time)
            );
            """
        )
    )

    # 7. weather_observations — Open-Meteo 30-min cadence (hypertable in 0002)
    op.execute(
        sa.text(
            """
            CREATE TABLE weather_observations (
                station_id              TEXT NOT NULL REFERENCES noaa_stations(station_id),
                time                    TIMESTAMPTZ NOT NULL,
                wind_speed_ms           DOUBLE PRECISION,
                wind_dir_deg            DOUBLE PRECISION,
                surface_pressure_hpa    DOUBLE PRECISION,
                temperature_2m_c        DOUBLE PRECISION,
                precipitation_prob_pct  DOUBLE PRECISION,
                cloud_cover_pct         DOUBLE PRECISION,
                source                  TEXT NOT NULL DEFAULT 'open-meteo',
                raw_payload JSONB NOT NULL,
                inserted_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (station_id, time)
            );
            """
        )
    )

    # 8. noaa_harmonic_forecasts — composite PK (station_id, issued_at, target_time)
    op.execute(
        sa.text(
            """
            CREATE TABLE noaa_harmonic_forecasts (
                station_id         TEXT NOT NULL REFERENCES noaa_stations(station_id),
                issued_at          TIMESTAMPTZ NOT NULL,
                target_time        TIMESTAMPTZ NOT NULL,
                predicted_level_m  DOUBLE PRECISION,
                hi_lo              TEXT,
                source             TEXT NOT NULL DEFAULT 'noaa-predictions',
                raw_payload JSONB NOT NULL,
                inserted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (station_id, issued_at, target_time)
            );
            """
        )
    )

    # 9. solunar_values — hourly computed ephem outputs
    op.execute(
        sa.text(
            """
            CREATE TABLE solunar_values (
                station_id        TEXT NOT NULL REFERENCES noaa_stations(station_id),
                time              TIMESTAMPTZ NOT NULL,
                moon_phase        DOUBLE PRECISION NOT NULL,
                moon_phase_sin    DOUBLE PRECISION NOT NULL,
                moon_phase_cos    DOUBLE PRECISION NOT NULL,
                illumination      DOUBLE PRECISION NOT NULL,
                lunar_day         DOUBLE PRECISION NOT NULL,
                sunrise           TIMESTAMPTZ,
                sunset            TIMESTAMPTZ,
                next_major_start  TIMESTAMPTZ,
                next_major_end    TIMESTAMPTZ,
                next_minor_start  TIMESTAMPTZ,
                next_minor_end    TIMESTAMPTZ,
                quality_score     DOUBLE PRECISION NOT NULL,
                source            TEXT NOT NULL DEFAULT 'ephem',
                inserted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (station_id, time)
            );
            """
        )
    )


def downgrade() -> None:
    # Drop in reverse dependency order. CASCADE handles any derived objects
    # (hypertable metadata, CAGG references, indexes).
    op.execute(sa.text("DROP TABLE IF EXISTS solunar_values CASCADE;"))
    op.execute(sa.text("DROP TABLE IF EXISTS noaa_harmonic_forecasts CASCADE;"))
    op.execute(sa.text("DROP TABLE IF EXISTS weather_observations CASCADE;"))
    op.execute(sa.text("DROP TABLE IF EXISTS tidal_observations CASCADE;"))
    op.execute(sa.text("DROP TABLE IF EXISTS fishing_spots CASCADE;"))
    op.execute(sa.text("DROP TABLE IF EXISTS noaa_stations CASCADE;"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS timescaledb;"))
