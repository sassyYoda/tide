"""End-to-end integration tests for ``/api/v1/conditions/{station_id}``.

Boots the FastAPI ``app`` against a migrated Timescale testcontainer + Redis
testcontainer (both session-scoped from conftest.py) and exercises every
branch of the freshness gate + route body:

- 200 fresh
- 503 stale (latest bucket > 35 min)
- 503 no_data (station exists but CAGG empty)
- 404 unknown station (freshness gate may 503 first — either is accepted)
- /healthz always 200 (even if DB is down)
- /metrics scrapeable
- pressure_trend_label surfaced in WeatherBlock
- sunrise / sunset ISO strings (tz-aware)
- data_age_seconds numeric and consistent with wall-clock age

Each test resets only its own data; the container is shared across the
module (session scope). Dependency overrides repoint ``get_session`` /
``get_redis`` at the testcontainer instances.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


pytestmark = pytest.mark.integration


BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
STATION = "8534720"  # Atlantic City — always in the seed set


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
def migrated_api_db(timescale_sync_url, timescale_async_url) -> str:
    _run_alembic_upgrade(timescale_sync_url, timescale_async_url)
    return timescale_sync_url


@pytest.fixture
def test_client(migrated_api_db, timescale_async_url, redis_container):
    """FastAPI TestClient with get_session / get_redis overridden to the containers."""
    from app.deps.db import get_session
    from app.deps.redis import get_redis
    from app.main import create_app

    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    redis_url = f"redis://{host}:{port}/0"

    engine = create_async_engine(timescale_async_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _session_override():
        async with factory() as s:
            yield s

    async def _redis_override():
        r = Redis.from_url(redis_url, decode_responses=False)
        try:
            yield r
        finally:
            await r.aclose()

    app = create_app()
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_redis] = _redis_override

    client = TestClient(app)
    try:
        yield {
            "client": client,
            "app": app,
            "sync_url": migrated_api_db,
            "async_url": timescale_async_url,
            "redis_url": redis_url,
            "factory": factory,
        }
    finally:
        app.dependency_overrides.clear()
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            engine.dispose()
        )


def _exec(sync_url: str, stmt: str, **params) -> None:
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(stmt), params)
    finally:
        engine.dispose()


def _seed_obs(sync_url: str, station_id: str, when: datetime) -> None:
    """Insert one tidal + one weather row at ``when``; refresh the CAGG."""
    _exec(
        sync_url,
        """
        INSERT INTO tidal_observations
            (station_id, time, water_level_m, water_temp_c, raw_payload, source)
        VALUES (:sid, :t, 0.821, 12.5, :raw, 'noaa_co-ops')
        ON CONFLICT DO NOTHING
        """,
        sid=station_id,
        t=when,
        raw=json.dumps({"test": True}),
    )
    _exec(
        sync_url,
        """
        INSERT INTO weather_observations
            (station_id, time, surface_pressure_hpa, temperature_2m_c,
             wind_speed_ms, wind_dir_deg, cloud_cover_pct, raw_payload, source)
        VALUES (:sid, :t, 1014.6, 14.2, 4.1, 218.0, 42,
                :raw, 'open-meteo')
        ON CONFLICT DO NOTHING
        """,
        sid=station_id,
        t=when,
        raw=json.dumps(
            {
                "_pressure_trend": {
                    "delta_1h": -0.4,
                    "delta_3h": -1.2,
                    "delta_6h": -2.5,
                    "pressure_trend_label": "Falling",
                }
            }
        ),
    )
    # Refresh the CAGG so conditions_15min MAX(bucket) reflects the new row.
    _refresh_cagg(sync_url)


def _refresh_cagg(sync_url: str) -> None:
    engine = sa.create_engine(sync_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                sa.text("CALL refresh_continuous_aggregate('conditions_15min', NULL, NULL)")
            )
    finally:
        engine.dispose()


def _clear_station_data(sync_url: str, station_id: str) -> None:
    _exec(
        sync_url,
        "DELETE FROM tidal_observations WHERE station_id = :sid",
        sid=station_id,
    )
    _exec(
        sync_url,
        "DELETE FROM weather_observations WHERE station_id = :sid",
        sid=station_id,
    )
    _exec(
        sync_url,
        "DELETE FROM solunar_values WHERE station_id = :sid",
        sid=station_id,
    )
    _refresh_cagg(sync_url)


def _seed_solunar(sync_url: str, station_id: str, when: datetime) -> None:
    _exec(
        sync_url,
        """
        INSERT INTO solunar_values
            (station_id, time, moon_phase, moon_phase_sin, moon_phase_cos,
             illumination, lunar_day, sunrise, sunset, quality_score)
        VALUES
            (:sid, :t, 0.5, 0.0, -1.0, 0.95, 14.8,
             :sunrise, :sunset, 0.9)
        ON CONFLICT DO NOTHING
        """,
        sid=station_id,
        t=when,
        sunrise=when.replace(hour=10, minute=30, second=0, microsecond=0),
        sunset=when.replace(hour=23, minute=45, second=0, microsecond=0),
    )


def _flush_redis(redis_url: str) -> None:
    async def _f():
        r = Redis.from_url(redis_url, decode_responses=False)
        try:
            await r.flushdb()
        finally:
            await r.aclose()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_f())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_200_fresh(test_client):
    """Fresh observation → 200 with ConditionsResponse body."""
    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])

    when = datetime.now(timezone.utc) - timedelta(minutes=5)
    _seed_obs(sync_url, STATION, when)

    resp = test_client["client"].get(f"/api/v1/conditions/{STATION}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["station_id"] == STATION
    assert body["data_age_seconds"] < 3600
    assert body["tidal"]["current_level_m"] is not None


def test_503_stale(test_client):
    """latest bucket > 35 min → 503 conditions_stale."""
    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])

    when = datetime.now(timezone.utc) - timedelta(minutes=60)
    _seed_obs(sync_url, STATION, when)

    resp = test_client["client"].get(f"/api/v1/conditions/{STATION}")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["detail"]["code"] == "conditions_stale"
    assert body["detail"].get("latest_bucket") is not None


def test_503_no_data(test_client):
    """Station exists, CAGG empty → 503 conditions_unavailable."""
    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])

    resp = test_client["client"].get(f"/api/v1/conditions/{STATION}")
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["code"] == "conditions_unavailable"


def test_404_unknown_station(test_client):
    """Unknown station → gate may 503 first; if it passes, route 404s."""
    _flush_redis(test_client["redis_url"])
    resp = test_client["client"].get("/api/v1/conditions/9999999")
    assert resp.status_code in (404, 503)
    body = resp.json()
    if resp.status_code == 404:
        assert body["detail"]["code"] == "station_not_found"


def test_healthz_returns_l05_shape(test_client):
    """/healthz returns the L-05 4-field readiness shape (REL-01 / plan 05-02).

    Phase 1 stub asserted ``{"status":"ok"}`` always 200. Plan 05-02 promoted
    /healthz to a readiness probe per the L-05 lock — the body now carries
    ``ts_lag_seconds`` + ``qdrant_ok`` + ``model_loaded`` + ``status``, and
    status code maps {200 ok, 503 degraded}. The Cache-Control: no-store
    header (Pitfall P3) is always present.
    """
    resp = test_client["client"].get("/healthz")
    # 200 or 503 depending on freshness / qdrant / model_loaded — both are valid
    # readiness signals; what we regress here is the contract, not the value.
    assert resp.status_code in (200, 503), resp.text
    body = resp.json()
    assert set(body.keys()) == {"ts_lag_seconds", "qdrant_ok", "model_loaded", "status"}
    assert body["status"] in {"ok", "degraded"}
    assert resp.headers.get("Cache-Control") == "no-store"


def test_metrics_scrape(test_client):
    """/metrics responds with text/plain and exposes Tide metric names."""
    resp = test_client["client"].get("/metrics")
    assert resp.status_code == 200
    ctype = resp.headers.get("content-type", "")
    assert "text/plain" in ctype
    body = resp.text
    # data_age_seconds and freshness_gate_503_total are declared in
    # ingest.metrics; they may have zero samples in multiproc mode but the
    # metric name registers in the body once the default registry exports.
    # WR-09: the prior `or body` fallback made this assertion trivially
    # true; drop it and require at least one of the Tide metric names to
    # appear in the Prometheus body.
    assert "data_age_seconds" in body or "freshness_gate_503_total" in body, (
        f"neither Tide metric appeared in /metrics body: {body[:500]!r}"
    )


def test_pressure_trend_in_response(test_client):
    """pressure_trend_label present in WeatherBlock + pressure_delta_3h non-null."""
    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])

    when = datetime.now(timezone.utc) - timedelta(minutes=5)
    _seed_obs(sync_url, STATION, when)
    # The _seed_obs helper writes a _pressure_trend block in raw_payload with
    # the delta_{1,3,6}h / pressure_trend_label keys; the route expects
    # pressure_delta_{1,3,6}h / pressure_trend_label. Plan 05 stored values
    # under delta_* but the conditions query reads pressure_delta_* — write
    # both keys so the route sees something in either schema iteration.
    _exec(
        sync_url,
        """
        UPDATE weather_observations
           SET raw_payload = jsonb_set(
               raw_payload,
               '{_pressure_trend}',
               :trend
           )
         WHERE station_id = :sid AND time = :t
        """,
        sid=STATION,
        t=when,
        trend=json.dumps(
            {
                "delta_1h": -0.4,
                "delta_3h": -1.2,
                "delta_6h": -2.5,
                "pressure_delta_1h": -0.4,
                "pressure_delta_3h": -1.2,
                "pressure_delta_6h": -2.5,
                "pressure_trend_label": "Falling",
            }
        ),
    )
    _refresh_cagg(sync_url)

    resp = test_client["client"].get(f"/api/v1/conditions/{STATION}")
    assert resp.status_code == 200, resp.text
    weather = resp.json()["weather"]
    assert weather["pressure_trend_label"] in {
        "Falling", "Rapid Fall", "Steady", "Rising", "Rapid Rise"
    }
    assert weather["pressure_delta_3h"] is not None


def test_sunrise_sunset_present(test_client):
    """Solunar row present → sunrise/sunset are ISO-8601 tz-aware strings."""
    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])

    when = datetime.now(timezone.utc) - timedelta(minutes=5)
    _seed_obs(sync_url, STATION, when)
    _seed_solunar(sync_url, STATION, when.replace(minute=0, second=0, microsecond=0))

    resp = test_client["client"].get(f"/api/v1/conditions/{STATION}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for key in ("sunrise", "sunset"):
        val = body.get(key)
        assert val is not None, f"{key} missing"
        parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None


def test_data_age_seconds_field(test_client):
    """data_age_seconds is a non-negative int consistent with the seed age."""
    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])

    when = datetime.now(timezone.utc) - timedelta(minutes=5)
    _seed_obs(sync_url, STATION, when)

    resp = test_client["client"].get(f"/api/v1/conditions/{STATION}")
    assert resp.status_code == 200, resp.text
    age = resp.json()["data_age_seconds"]
    assert isinstance(age, int)
    assert 0 <= age <= 35 * 60  # within the freshness window
