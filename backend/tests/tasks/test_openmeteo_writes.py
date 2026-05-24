"""Plan 07 — Open-Meteo poll writes observation + 168h forecast rows.

Integration test against a live Timescale testcontainer. The Open-Meteo
endpoint is mocked with respx; everything below the HTTP boundary is the
real ``celery_app.tasks.meteo._poll_all`` codepath.

Asserts:
- A single poll writes BOTH the observation row (is_forecast=False) AND the
  hourly forecast rows (is_forecast=True) to ``weather_observations``.
- Observation and forecast rows that share ``(station_id, time)`` do NOT
  collide — they coexist because ``is_forecast`` is part of the PK.
- A re-poll is idempotent: same composite key → ``session.merge`` overwrites
  in place, row counts stay stable.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
import sqlalchemy as sa


pytestmark = pytest.mark.integration


BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"


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
def meteo_migrated_db(timescale_sync_url, timescale_async_url) -> str:
    """Module-scoped migrated DB (avoids re-running alembic per test)."""
    _run_alembic_upgrade(timescale_sync_url, timescale_async_url)
    return timescale_sync_url


@pytest.fixture
def meteo_ingest_urls(
    meteo_migrated_db, timescale_async_url, redis_container, monkeypatch
):
    """Repoint ingest code at the live testcontainers (NullPool — see scorer test)."""
    from app import config as app_config
    from db import session as db_session
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    redis_url = f"redis://{host}:{port}/0"

    monkeypatch.setattr(app_config.settings, "database_url", timescale_async_url)
    monkeypatch.setattr(app_config.settings, "database_sync_url", meteo_migrated_db)
    monkeypatch.setattr(app_config.settings, "redis_url", redis_url)

    new_engine = create_async_engine(timescale_async_url, poolclass=NullPool)
    new_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "async_engine", new_engine)
    monkeypatch.setattr(db_session, "async_session_factory", new_factory)

    yield {
        "sync_url": meteo_migrated_db,
        "async_url": timescale_async_url,
    }


@pytest.fixture
def seed_one_station(meteo_ingest_urls):
    """Insert one NoaaStation; clean weather_observations before + after."""
    sync_url = meteo_ingest_urls["sync_url"]
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM weather_observations"))
            conn.execute(sa.text("DELETE FROM tidal_observations"))
            conn.execute(sa.text("DELETE FROM noaa_harmonic_forecasts"))
            conn.execute(sa.text("DELETE FROM solunar_values"))
            conn.execute(sa.text("DELETE FROM activity_scores"))
            conn.execute(sa.text("DELETE FROM fishing_spots"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
            conn.execute(
                sa.text(
                    "INSERT INTO noaa_stations (station_id, name, lat, lon, "
                    "products, source_url) VALUES "
                    "(:sid, :name, :lat, :lon, :products, :url)"
                ),
                {
                    "sid": "METEO_STATION_1",
                    "name": "Meteo Test Station 1",
                    "lat": 39.36,
                    "lon": -74.42,
                    "products": ["water_level"],
                    "url": "https://example.test/stations/METEO_STATION_1",
                },
            )
        yield "METEO_STATION_1"
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM weather_observations"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
        engine.dispose()


def _build_synthetic_response(hours: int = 168) -> dict:
    """Construct a synthetic Open-Meteo response covering N hourly slots."""
    base = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    times = [
        (base + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(hours)
    ]
    return {
        "latitude": 39.36,
        "longitude": -74.42,
        "current": {
            "time": base.strftime("%Y-%m-%dT%H:00"),
            "wind_speed_10m": 4.1,
            "wind_direction_10m": 218.0,
            "surface_pressure": 1014.6,
            "temperature_2m": 14.2,
            "precipitation": 0.0,
            "cloud_cover": 42,
        },
        "hourly": {
            "time": times,
            "wind_speed_10m": [4.1 + i * 0.01 for i in range(hours)],
            "wind_direction_10m": [218.0] * hours,
            "surface_pressure": [1014.6 + i * 0.05 for i in range(hours)],
            "temperature_2m": [14.2] * hours,
            "precipitation_probability": [5] * hours,
            "cloud_cover": [42] * hours,
        },
    }


@pytest.mark.asyncio
async def test_open_meteo_writes_observation_and_forecast(seed_one_station):
    """A single poll writes 1 observation row + 168 forecast rows."""
    from celery_app.tasks.meteo import _poll_all

    response = _build_synthetic_response(hours=168)
    with respx.mock(assert_all_called=False) as router:
        router.get(OPEN_METEO_BASE).mock(
            return_value=httpx.Response(200, json=response)
        )
        result = await _poll_all()

    assert result["failure"] == 0
    assert result["success"] >= 1

    # Read back and assert split counts.
    from db.session import async_session_factory
    from sqlalchemy import select, func
    from db.models import WeatherObservation

    async with async_session_factory() as session:
        n_obs = (
            await session.execute(
                select(func.count())
                .select_from(WeatherObservation)
                .where(WeatherObservation.station_id == seed_one_station)
                .where(WeatherObservation.is_forecast.is_(False))
            )
        ).scalar_one()
        n_fc = (
            await session.execute(
                select(func.count())
                .select_from(WeatherObservation)
                .where(WeatherObservation.station_id == seed_one_station)
                .where(WeatherObservation.is_forecast.is_(True))
            )
        ).scalar_one()

    assert n_obs == 1, f"expected 1 observation row, got {n_obs}"
    assert n_fc == 168, f"expected 168 forecast rows, got {n_fc}"


@pytest.mark.asyncio
async def test_observation_and_forecast_at_same_time_dont_collide(seed_one_station):
    """The hour-0 forecast and the observation share `time` — both must persist."""
    from celery_app.tasks.meteo import _poll_all

    response = _build_synthetic_response(hours=24)
    with respx.mock(assert_all_called=False) as router:
        router.get(OPEN_METEO_BASE).mock(
            return_value=httpx.Response(200, json=response)
        )
        await _poll_all()

    from db.session import async_session_factory
    from sqlalchemy import select
    from db.models import WeatherObservation

    base_time = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(WeatherObservation)
                .where(WeatherObservation.station_id == seed_one_station)
                .where(WeatherObservation.time == base_time)
            )
        ).scalars().all()

    # Exactly two rows at the same wall-clock time: one obs, one forecast.
    flags = sorted(r.is_forecast for r in rows)
    assert flags == [False, True], (
        f"expected one obs + one forecast at base hour, got is_forecast={flags}"
    )


@pytest.mark.asyncio
async def test_repoll_is_idempotent(seed_one_station):
    """Two consecutive polls land on the same composite PK → row count stable."""
    from celery_app.tasks.meteo import _poll_all

    response = _build_synthetic_response(hours=48)
    with respx.mock(assert_all_called=False) as router:
        router.get(OPEN_METEO_BASE).mock(
            return_value=httpx.Response(200, json=response)
        )
        await _poll_all()
        await _poll_all()

    from db.session import async_session_factory
    from sqlalchemy import select, func
    from db.models import WeatherObservation

    async with async_session_factory() as session:
        total = (
            await session.execute(
                select(func.count())
                .select_from(WeatherObservation)
                .where(WeatherObservation.station_id == seed_one_station)
            )
        ).scalar_one()
    # 1 observation + 48 forecast rows, regardless of how many times we polled.
    assert total == 49, f"expected 49 rows after 2 polls, got {total}"
