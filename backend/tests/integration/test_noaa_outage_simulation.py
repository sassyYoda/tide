"""REL-02 + ROADMAP SC #5 — NOAA outage simulation against live testcontainers.

Four single-responsibility tests:

- ``test_3x_failure_trips_breaker_no_raise`` — 3 consecutive failures trip the
  breaker and increment ``noaa_breaker_tripped_total`` exactly once, without
  raising out of ``_poll_one``. No tidal_observations row is inserted. No LKG
  key is written on the failure path.

- ``test_lkg_persists_through_outage`` — a pre-seeded LKG key survives a
  simulated 3x NOAA outage. The key remains readable with its original
  payload (byte-for-byte), TTL within the 0..2100s ceiling.
  ROADMAP SC #5 ("confirms LKG fallback").

- ``test_recovery_resets_breaker`` — after a failure, a subsequent success
  clears the breaker key; because the threshold was not crossed, the
  breaker counter did not move.

- ``test_breaker_fires_once_not_on_4th_failure`` — 4 consecutive failures
  emit the breaker counter exactly once (the edge-triggered semantic in
  ``ingest.lkg.increment_breaker``).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
import sqlalchemy as sa

from ingest.lkg import BREAKER_THRESHOLD, read_lkg, write_lkg
from ingest.metrics import noaa_breaker_tripped_total
from ingest.noaa_client import NOAA_BASE


pytestmark = pytest.mark.integration


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
def migrated_db_for_outage(timescale_sync_url, timescale_async_url) -> str:
    _run_alembic_upgrade(timescale_sync_url, timescale_async_url)
    return timescale_sync_url


@pytest.fixture
def outage_env(
    migrated_db_for_outage, timescale_async_url, redis_container, monkeypatch
):
    """Same pattern as the ingest_e2e fixture — repoint settings + engines."""
    from app import config as app_config
    from db import session as db_session
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    redis_url = f"redis://{host}:{port}/0"

    monkeypatch.setattr(app_config.settings, "database_url", timescale_async_url)
    monkeypatch.setattr(
        app_config.settings, "database_sync_url", migrated_db_for_outage
    )
    monkeypatch.setattr(app_config.settings, "redis_url", redis_url)

    new_engine = create_async_engine(timescale_async_url, pool_pre_ping=True)
    new_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "async_engine", new_engine)
    monkeypatch.setattr(db_session, "async_session_factory", new_factory)

    yield {
        "sync_url": migrated_db_for_outage,
        "async_url": timescale_async_url,
        "redis_url": redis_url,
    }

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        new_engine.dispose()
    )


def _first_station(sync_url: str):
    """Return a duck-typed station object usable by ``_poll_one``."""
    engine = sa.create_engine(sync_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT station_id, lat, lon, products, source_url "
                    "FROM noaa_stations ORDER BY station_id LIMIT 1"
                )
            ).first()
    finally:
        engine.dispose()
    assert row is not None

    class _Station:
        station_id = row.station_id
        lat = float(row.lat)
        lon = float(row.lon)
        products = list(row.products or [])

    return _Station


def _kill_jitter(monkeypatch):
    """Disable the 0..60s per-station jitter + tenacity backoff randomness."""
    import random as _random

    monkeypatch.setattr(_random, "uniform", lambda a, b: 0)
    monkeypatch.setenv("NOAA_TEST_NO_JITTER", "1")


# ---------------------------------------------------------------------------
# REL-02 — 3x outage trips breaker, does not raise, does not write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_3x_failure_trips_breaker_no_raise(
    outage_env, redis_client, monkeypatch
):
    """3x NOAA 500 → breaker=3, counter +1, no raise, no row, no LKG."""
    from celery_app.tasks import noaa as noaa_task

    station = _first_station(outage_env["sync_url"])
    station_id = station.station_id

    _kill_jitter(monkeypatch)
    await redis_client.delete(f"breaker:noaa:{station_id}")
    await redis_client.delete(f"lkg:noaa:{station_id}:water_level")

    trip_counter = noaa_breaker_tripped_total.labels(station_id=station_id)
    baseline_trips = trip_counter._value.get()

    with respx.mock(assert_all_called=False) as router:
        router.get(NOAA_BASE).mock(return_value=httpx.Response(500))

        # A single tick of _poll_one internally retries via tenacity up to 3x
        # — after the 3rd failure tenacity reraises, the handler catches,
        # increments the breaker, and must NOT raise.
        results: dict[str, int] = {"success": 0, "failure": 0}
        await noaa_task._poll_one(station(), redis_client, results)

    # No raise out of _poll_one (we reached this line).
    assert results["failure"] == 1

    # Breaker count == BREAKER_THRESHOLD (==3) after the first tick's
    # retry-exhausted failure is counted once by the outer handler.
    # Note: _poll_one counts ONE breaker increment per outer-exception, so a
    # single tick yields breaker=1. The plan's assertion "breaker == 3" is
    # reinterpreted: three consecutive ticks get us to 3. We therefore run
    # two MORE ticks to land on the stated invariant.
    for _ in range(2):
        results2: dict[str, int] = {"success": 0, "failure": 0}
        with respx.mock(assert_all_called=False) as router:
            router.get(NOAA_BASE).mock(return_value=httpx.Response(500))
            await noaa_task._poll_one(station(), redis_client, results2)

    breaker_raw = await redis_client.get(f"breaker:noaa:{station_id}")
    assert breaker_raw is not None
    assert int(breaker_raw) == BREAKER_THRESHOLD

    # Counter fired exactly once (on count == THRESHOLD).
    assert trip_counter._value.get() - baseline_trips == pytest.approx(1.0)

    # ingest_failure_total moved (label = some exception class name).
    # Compare the sum across all reason labels for this (source, station).
    from prometheus_client import REGISTRY  # default registry

    total_failures_for_station = 0.0
    for metric in REGISTRY.collect():
        if metric.name != "ingest_failure":
            continue
        for s in metric.samples:
            if (
                s.name == "ingest_failure_total"
                and s.labels.get("source") == "noaa"
                and s.labels.get("station_id") == station_id
            ):
                total_failures_for_station += s.value
    assert total_failures_for_station >= 3.0

    # No tidal_observations row inserted for the station during these ticks.
    # (The FK-constrained INSERT path was never reached because the fetch failed.)
    engine = sa.create_engine(outage_env["sync_url"])
    try:
        with engine.connect() as conn:
            n = conn.execute(
                sa.text(
                    "SELECT count(*) FROM tidal_observations WHERE station_id = :sid"
                ),
                {"sid": station_id},
            ).scalar_one()
    finally:
        engine.dispose()
    assert n == 0

    # No LKG key written on failure.
    assert await redis_client.exists(f"lkg:noaa:{station_id}:water_level") == 0

    # Cleanup so subsequent tests don't inherit state.
    await redis_client.delete(f"breaker:noaa:{station_id}")


# ---------------------------------------------------------------------------
# ROADMAP SC #5 — pre-outage LKG persists through the outage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lkg_persists_through_outage(
    outage_env, redis_client, monkeypatch
):
    """Pre-seeded LKG survives 3x NOAA 500 with payload + TTL intact."""
    from celery_app.tasks import noaa as noaa_task

    station = _first_station(outage_env["sync_url"])
    station_id = station.station_id

    _kill_jitter(monkeypatch)
    await redis_client.delete(f"breaker:noaa:{station_id}")

    lkg_key = f"lkg:noaa:{station_id}:water_level"
    payload = {
        "water_level_m": 0.42,
        "water_temp_c": 12.3,
        "observed_at": (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat(),
    }
    await write_lkg(redis_client, lkg_key, payload, ttl=2100)  # 35 min

    # Confirm seed landed.
    assert await redis_client.exists(lkg_key) == 1

    with respx.mock(assert_all_called=False) as router:
        router.get(NOAA_BASE).mock(return_value=httpx.Response(500))
        for _ in range(3):
            results: dict[str, int] = {"success": 0, "failure": 0}
            await noaa_task._poll_one(station(), redis_client, results)

    # 1. Key still present (failure path must not delete LKG).
    assert await redis_client.exists(lkg_key) == 1

    # 2. Payload byte-for-byte intact.
    got = await read_lkg(redis_client, lkg_key)
    assert got == payload

    # 3. TTL still healthy — not expired, not extended past the ceiling.
    ttl = await redis_client.ttl(lkg_key)
    assert ttl > 0
    assert ttl <= 2100

    # Cleanup.
    await redis_client.delete(lkg_key)
    await redis_client.delete(f"breaker:noaa:{station_id}")


# ---------------------------------------------------------------------------
# Recovery — a success after a failure clears the breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_resets_breaker(
    outage_env, redis_client, monkeypatch
):
    """Failure → success → breaker cleared; no trip emission occurred."""
    from celery_app.tasks import noaa as noaa_task

    station = _first_station(outage_env["sync_url"])
    station_id = station.station_id

    _kill_jitter(monkeypatch)
    await redis_client.delete(f"breaker:noaa:{station_id}")

    trip_counter = noaa_breaker_tripped_total.labels(station_id=station_id)
    baseline = trip_counter._value.get()

    # First tick: total failure.
    with respx.mock(assert_all_called=False) as router:
        router.get(NOAA_BASE).mock(return_value=httpx.Response(500))
        results1: dict[str, int] = {"success": 0, "failure": 0}
        await noaa_task._poll_one(station(), redis_client, results1)

    # Second tick: all products succeed.
    import json as _json

    wl = _json.loads((BACKEND_DIR / "tests" / "fixtures" / "noaa_responses" / "water_level.json").read_text())
    wt = _json.loads((BACKEND_DIR / "tests" / "fixtures" / "noaa_responses" / "water_temperature.json").read_text())
    wind = _json.loads((BACKEND_DIR / "tests" / "fixtures" / "noaa_responses" / "wind.json").read_text())
    pred = _json.loads((BACKEND_DIR / "tests" / "fixtures" / "noaa_responses" / "predictions.json").read_text())

    with respx.mock(assert_all_called=False) as router:
        def _dispatch(request: httpx.Request) -> httpx.Response:
            product = request.url.params.get("product")
            return httpx.Response(
                200,
                json={
                    "water_level": wl,
                    "water_temperature": wt,
                    "wind": wind,
                    "predictions": pred,
                }.get(product, {}),
            )
        router.get(NOAA_BASE).mock(side_effect=_dispatch)

        results2: dict[str, int] = {"success": 0, "failure": 0}
        await noaa_task._poll_one(station(), redis_client, results2)

    # Success clears the breaker key (reset_breaker is called on the success path).
    assert await redis_client.exists(f"breaker:noaa:{station_id}") == 0
    # Threshold never crossed — trip counter unchanged.
    assert trip_counter._value.get() - baseline == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Edge-triggered — 4 failures in a row fire the counter exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breaker_fires_once_not_on_4th_failure(
    outage_env, redis_client, monkeypatch
):
    """Four consecutive failures emit the trip counter exactly once."""
    from celery_app.tasks import noaa as noaa_task

    station = _first_station(outage_env["sync_url"])
    station_id = station.station_id

    _kill_jitter(monkeypatch)
    await redis_client.delete(f"breaker:noaa:{station_id}")

    trip_counter = noaa_breaker_tripped_total.labels(station_id=station_id)
    baseline = trip_counter._value.get()

    with respx.mock(assert_all_called=False) as router:
        router.get(NOAA_BASE).mock(return_value=httpx.Response(500))
        for _ in range(4):
            results: dict[str, int] = {"success": 0, "failure": 0}
            await noaa_task._poll_one(station(), redis_client, results)

    # Exactly one emission — on the 3rd failure (count == BREAKER_THRESHOLD).
    assert trip_counter._value.get() - baseline == pytest.approx(1.0)

    # Breaker sits at 4 after the fourth tick.
    breaker_raw = await redis_client.get(f"breaker:noaa:{station_id}")
    assert breaker_raw is not None
    assert int(breaker_raw) == 4

    await redis_client.delete(f"breaker:noaa:{station_id}")
