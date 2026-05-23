"""REL-01 / Pitfall P3 readiness-probe tests for ``/healthz``.

Wave 1 (plan 05-02) replaces the existing ``/healthz`` stub with the L-05
shape (``{ts_lag_seconds, qdrant_ok, model_loaded, status}``) and adds the
required ``Cache-Control: no-store`` header (Pitfall P3).

All tests are integration-marked (require Timescale + Redis testcontainers).
The Qdrant probe in /healthz is monkeypatched per-test so this file does
NOT require the Qdrant testcontainer.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest
import sqlalchemy as sa
from redis.asyncio import Redis

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers — mirror tests/integration/test_conditions_endpoint.py seed pattern.
# ---------------------------------------------------------------------------

STATION = "8534720"  # Atlantic City — always in the seed set


def _exec(sync_url: str, stmt: str, **params) -> None:
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(stmt), params)
    finally:
        engine.dispose()


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
    _refresh_cagg(sync_url)


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
        VALUES (:sid, :t, 1014.6, 14.2, 4.1, 218.0, 42, :raw, 'open-meteo')
        ON CONFLICT DO NOTHING
        """,
        sid=station_id,
        t=when,
        raw=json.dumps({}),
    )
    _refresh_cagg(sync_url)


def _flush_redis(redis_url: str) -> None:
    async def _f():
        r = Redis.from_url(redis_url, decode_responses=False)
        try:
            await r.flushdb()
        finally:
            await r.aclose()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_f())


@pytest.fixture(autouse=True)
def _reset_model_flag() -> Iterator[None]:
    """Reset module-level model_loaded flag before + after each test."""
    from app.api.health import reset_model_loaded_for_tests

    reset_model_loaded_for_tests()
    yield
    reset_model_loaded_for_tests()


@pytest.fixture
def stub_qdrant_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch get_qdrant() in app.api.health to return a stub with healthy
    ``get_collections``. Avoids requiring the Qdrant testcontainer for /healthz
    tests (the L-05 probe just needs a positive client roundtrip)."""

    class _StubAsync:
        async def get_collections(self):
            return type("Collections", (), {"collections": []})()

    monkeypatch.setattr("app.api.health.get_qdrant", lambda: _StubAsync())


@pytest.fixture
def stub_qdrant_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch get_qdrant() to raise ConnectionError on probe."""

    class _Boom:
        async def get_collections(self):
            raise ConnectionError("qdrant unreachable")

    monkeypatch.setattr("app.api.health.get_qdrant", lambda: _Boom())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_healthz_returns_200_when_healthy(test_client, stub_qdrant_ok):
    """Fresh CAGG bucket + Qdrant up + model_loaded flag set → 200 with all 4 keys."""
    from app.api.health import mark_model_loaded

    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])

    # Seed a row inside the freshness threshold.
    _seed_obs(sync_url, STATION, datetime.now(timezone.utc) - timedelta(minutes=5))

    mark_model_loaded()

    resp = test_client["client"].get("/healthz")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"ts_lag_seconds", "qdrant_ok", "model_loaded", "status"}
    assert body["status"] == "ok"
    assert body["qdrant_ok"] is True
    assert body["model_loaded"] is True
    assert 0 <= body["ts_lag_seconds"] < 1800


def test_healthz_returns_503_when_qdrant_down(test_client, stub_qdrant_down):
    """Qdrant probe raises → 503 with status='degraded' and qdrant_ok=false."""
    from app.api.health import mark_model_loaded

    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])
    _seed_obs(sync_url, STATION, datetime.now(timezone.utc) - timedelta(minutes=5))
    mark_model_loaded()

    resp = test_client["client"].get("/healthz")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["qdrant_ok"] is False


def test_healthz_has_no_store_cache_header(test_client, stub_qdrant_ok):
    """Pitfall P3: Cache-Control: no-store on every response (200 OR 503)."""
    resp = test_client["client"].get("/healthz")
    assert resp.headers.get("Cache-Control") == "no-store"


def test_healthz_returns_503_when_ts_lag_above_threshold(test_client, stub_qdrant_ok):
    """Seed a stale CAGG bucket (1h old) → 503 with ts_lag_seconds > 1800."""
    from app.api.health import mark_model_loaded

    sync_url = test_client["sync_url"]
    _clear_station_data(sync_url, STATION)
    _flush_redis(test_client["redis_url"])

    # 1 hour stale — past the 1800s (30 min) threshold.
    _seed_obs(sync_url, STATION, datetime.now(timezone.utc) - timedelta(hours=1))
    mark_model_loaded()

    resp = test_client["client"].get("/healthz")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["ts_lag_seconds"] > 1800
    assert body["status"] == "degraded"
