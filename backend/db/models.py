"""SQLAlchemy 2.0 ORM models for Phase 1 schema.

These classes mirror the SQL schema declared in
`.planning/phases/01-data-foundation/01-RESEARCH.md` §TimescaleDB Schema.

Design notes:
- Every datetime column is `TIMESTAMP(timezone=True)` (TIMESTAMPTZ) — naive
  datetimes are banned project-wide (Pitfall #3).
- Every observation table carries a `raw_payload JSONB NOT NULL` for D-09
  replayability and a `source TEXT NOT NULL` with a sensible default.
- `fishing_spots.nearest_station` has a hard FK to `noaa_stations.station_id`
  (Pitfall #7 — prevent orphan spots).
- Composite primary keys use `mapped_column(..., primary_key=True)` on each
  column; SQLAlchemy 2.0 builds the PK from the union.
- These models exist for the application layer (Plan 05 ORM inserts, Plan 06
  queries). The Alembic migrations in this plan are HAND-WRITTEN raw SQL
  (autogenerate cannot express `create_hypertable()` or CAGGs).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class NoaaStation(Base):
    """NOAA CO-OPS stations — master data for all observations and forecasts."""

    __tablename__ = "noaa_stations"

    station_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    lat: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    lon: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    products: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)
    source_url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class FishingSpot(Base):
    """Curated fishing spots — referenced by the agent / recommendation layer."""

    __tablename__ = "fishing_spots"
    __table_args__ = (
        CheckConstraint(
            "access_type IN ('shore','boat','kayak')",
            name="fishing_spots_access_type_check",
        ),
    )

    spot_id: Mapped[int] = mapped_column(
        sa.BigInteger, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    lat: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    lon: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    water_body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    spot_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    depth_ft: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    species: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)
    nearest_station: Mapped[str] = mapped_column(
        sa.Text,
        ForeignKey("noaa_stations.station_id"),
        nullable=False,
    )
    orientation_deg: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    access_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class TidalObservation(Base):
    """NOAA CO-OPS tidal hypertable — 6-min cadence, composite PK (station_id, time)."""

    __tablename__ = "tidal_observations"

    station_id: Mapped[str] = mapped_column(
        sa.Text,
        ForeignKey("noaa_stations.station_id"),
        primary_key=True,
        nullable=False,
    )
    time: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    water_level_m: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    water_temp_c: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    wind_speed_ms: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    wind_dir_deg: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    current_speed_ms: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    current_dir_deg: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    source: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'noaa'")
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class WeatherObservation(Base):
    """Open-Meteo weather hypertable — 30-min cadence, composite PK (station_id, time)."""

    __tablename__ = "weather_observations"

    station_id: Mapped[str] = mapped_column(
        sa.Text,
        ForeignKey("noaa_stations.station_id"),
        primary_key=True,
        nullable=False,
    )
    time: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    wind_speed_ms: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    wind_dir_deg: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    surface_pressure_hpa: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    temperature_2m_c: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    precipitation_prob_pct: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    cloud_cover_pct: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    source: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'open-meteo'")
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class NoaaHarmonicForecast(Base):
    """NOAA harmonic tide predictions — composite PK (station_id, issued_at, target_time)."""

    __tablename__ = "noaa_harmonic_forecasts"

    station_id: Mapped[str] = mapped_column(
        sa.Text,
        ForeignKey("noaa_stations.station_id"),
        primary_key=True,
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    target_time: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    predicted_level_m: Mapped[float | None] = mapped_column(sa.Double(), nullable=True)
    hi_lo: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'noaa-predictions'")
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class SolunarValue(Base):
    """Solunar (moon phase / major-minor window) hypertable.

    Written by the hourly `compute_solunar` beat task (Plan 05); read by
    `/conditions` and the ML feature builder.
    """

    __tablename__ = "solunar_values"

    station_id: Mapped[str] = mapped_column(
        sa.Text,
        ForeignKey("noaa_stations.station_id"),
        primary_key=True,
        nullable=False,
    )
    time: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    moon_phase: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    moon_phase_sin: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    moon_phase_cos: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    illumination: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    lunar_day: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    sunrise: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    sunset: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    next_major_start: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    next_major_end: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    next_minor_start: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    next_minor_end: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    quality_score: Mapped[float] = mapped_column(sa.Double(), nullable=False)
    source: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'ephem'")
    )
    inserted_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


__all__ = [
    "NoaaStation",
    "FishingSpot",
    "TidalObservation",
    "WeatherObservation",
    "NoaaHarmonicForecast",
    "SolunarValue",
]
