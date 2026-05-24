"""Integration tests for ``data_fetcher_node``.

Requires a live Timescale testcontainer (via ``migrated_ingest_db``) +
the Wave-1 spot resolver fixtures. SPECIES_MODELS load is opted-out via
``lazy_models`` — Phase 2 promoted no models, so the persisted-score
path is the realistic source of truth for the integration check.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers — repoint the data fetcher's DB session at the testcontainer.
# ---------------------------------------------------------------------------


@pytest.fixture
def fetcher_urls(
    migrated_ingest_db, timescale_async_url, redis_container, monkeypatch,
):
    """Repoint the data fetcher's DB session at the live Timescale + Redis containers.

    Mirrors ``tests/tasks/test_scorer_writes_activity.py::scorer_urls``: NullPool
    so each checkout binds a fresh asyncpg connection to the current event loop.
    """
    from app import config as app_config
    from db import session as db_session
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    redis_url = f"redis://{host}:{port}/0"

    monkeypatch.setattr(app_config.settings, "database_url", timescale_async_url)
    monkeypatch.setattr(app_config.settings, "database_sync_url", migrated_ingest_db)
    monkeypatch.setattr(app_config.settings, "redis_url", redis_url)

    new_engine = create_async_engine(timescale_async_url, poolclass=NullPool)
    new_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "async_engine", new_engine)
    monkeypatch.setattr(db_session, "async_session_factory", new_factory)

    yield {
        "sync_url": migrated_ingest_db,
        "async_url": timescale_async_url,
        "redis_url": redis_url,
    }


@pytest.fixture
def seed_spot_and_score(fetcher_urls):
    """Insert one NoaaStation + FishingSpot + a fresh ActivityScore for striper.

    Returns the seeded spot_id (BigInt) for caller assertions.
    """
    sync_url = fetcher_urls["sync_url"]
    engine = sa.create_engine(sync_url)
    spot_id_holder: dict[str, int] = {}
    try:
        with engine.begin() as conn:
            # Wipe relevant tables for test isolation (mirrors scorer test).
            conn.execute(sa.text("DELETE FROM activity_scores"))
            conn.execute(sa.text("DELETE FROM tidal_observations"))
            conn.execute(sa.text("DELETE FROM weather_observations"))
            conn.execute(sa.text("DELETE FROM noaa_harmonic_forecasts"))
            conn.execute(sa.text("DELETE FROM solunar_values"))
            conn.execute(sa.text("DELETE FROM fishing_spots"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
            conn.execute(
                sa.text(
                    "INSERT INTO noaa_stations (station_id, name, lat, lon, products, source_url) "
                    "VALUES (:sid, :name, :lat, :lon, :products, :url)"
                ),
                {
                    "sid": "DF_TEST_STATION_1",
                    "name": "DF Test Station 1",
                    "lat": 39.7659,
                    "lon": -74.1098,
                    "products": ["water_level", "water_temperature"],
                    "url": "https://example.test/stations/DF_TEST_STATION_1",
                },
            )
            row = conn.execute(
                sa.text(
                    "INSERT INTO fishing_spots "
                    "(name, lat, lon, water_body, spot_type, species, "
                    "nearest_station, access_type) "
                    "VALUES (:name, :lat, :lon, :wb, :st, :sp, :ns, :at) "
                    "RETURNING spot_id"
                ),
                {
                    "name": "Barnegat Inlet — North Jetty",
                    "lat": 39.7659,
                    "lon": -74.1098,
                    "wb": "Barnegat Bay",
                    "st": "jetty",
                    "sp": ["striper", "fluke"],
                    "ns": "DF_TEST_STATION_1",
                    "at": "shore",
                },
            ).first()
            spot_id = int(row[0])
            spot_id_holder["spot_id"] = spot_id

            # Fresh ActivityScore (~60s old) for striper.
            now = datetime.now(timezone.utc)
            conn.execute(
                sa.text(
                    "INSERT INTO activity_scores "
                    "(spot_id, species, time, score, shap_values, model_version, "
                    "confidence, is_forecast, raw_payload) "
                    "VALUES (:spot_id, :species, :time, :score, "
                    "CAST(:shap AS JSONB), :mv, :conf, :is_f, CAST(:rp AS JSONB))"
                ),
                {
                    "spot_id": spot_id,
                    "species": "striper",
                    "time": now - timedelta(seconds=60),
                    "score": 0.78,
                    "shap": '{"top_features": ['
                            '{"feature": "tide_phase_incoming", "value": 0.35}, '
                            '{"feature": "wind_speed_mps", "value": -0.20}, '
                            '{"feature": "tide_height_m", "value": 0.15}]}',
                    "mv": "test-1.0",
                    "conf": "moderate",
                    "is_f": False,
                    "rp": '{"features": {'
                          '"tide_height_m": 0.4, "wind_speed_mps": 5.0, '
                          '"tide_phase": "incoming", "water_temp_c": 12.5, '
                          '"pressure_hpa": 1013.0}, '
                          '"model_run_id": "abc123"}',
                },
            )

            # Fresh tidal + weather + solunar rows — post-refactor data_fetcher
            # reads conditions from these tables directly (not ActivityScore).
            conn.execute(
                sa.text(
                    "INSERT INTO tidal_observations "
                    "(station_id, time, water_level_m, water_temp_c, "
                    "wind_speed_ms, wind_dir_deg, raw_payload) "
                    "VALUES (:sid, :t, 0.42, 14.1, 4.8, 90, CAST('{}' AS JSONB))"
                ),
                {"sid": "DF_TEST_STATION_1", "t": now - timedelta(seconds=60)},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO weather_observations "
                    "(station_id, time, wind_speed_ms, wind_dir_deg, "
                    "surface_pressure_hpa, temperature_2m_c, "
                    "precipitation_prob_pct, cloud_cover_pct, raw_payload) "
                    "VALUES (:sid, :t, 5.1, 92, 1015.3, 13.2, 14.0, 22.0, "
                    "CAST('{}' AS JSONB))"
                ),
                {"sid": "DF_TEST_STATION_1", "t": now - timedelta(seconds=120)},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO solunar_values "
                    "(station_id, time, moon_phase, moon_phase_sin, "
                    "moon_phase_cos, illumination, lunar_day, quality_score) "
                    "VALUES (:sid, :t, 0.26, 0.99, 0.07, 0.61, 7.7, 0.81)"
                ),
                {"sid": "DF_TEST_STATION_1", "t": now - timedelta(minutes=5)},
            )
        yield spot_id_holder["spot_id"]
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM activity_scores"))
            conn.execute(sa.text("DELETE FROM tidal_observations"))
            conn.execute(sa.text("DELETE FROM weather_observations"))
            conn.execute(sa.text("DELETE FROM solunar_values"))
            conn.execute(sa.text("DELETE FROM fishing_spots"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
        engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_fetcher_resolves_and_reads_persisted_score(
    seed_spot_and_score, lazy_models, lazy_spots,
):
    """Fresh ActivityScore present → persisted score surfaced; not stale."""
    from agent.nodes.data_fetcher import data_fetcher_node
    from agent.spot_resolver import reset_for_test

    spot_id = seed_spot_and_score
    reset_for_test([{
        "id": spot_id,
        "name": "Barnegat Inlet — North Jetty",
        "lat": 39.7659,
        "lon": -74.1098,
    }])

    out = await data_fetcher_node({
        "query": "stripers at Barnegat Inlet",
        "species_canonical": "striper",
        "location_hint_raw": "Barnegat Inlet",
    })
    assert out["spot_id"] == spot_id
    assert out["spot_resolution_strategy"] == "fuzzy_name"
    assert out["spot_name"] == "Barnegat Inlet — North Jetty"
    assert out["conditions"] is not None
    assert out["conditions"]["water_level_m"] == 0.42
    assert out["conditions"]["water_temp_c"] == 14.1
    assert out["conditions"]["surface_pressure_hpa"] == 1015.3
    assert out["conditions"]["air_temperature_c"] == 13.2
    assert out["conditions"]["moon_phase"] == 0.26
    assert out["conditions_stale"] is False
    assert out["data_age_seconds"] is not None and out["data_age_seconds"] < 600
    assert out["ml_score"] == pytest.approx(0.78)
    assert out["shap_top3"] is not None
    assert len(out["shap_top3"]) == 3
    assert out["shap_top3"][0] == "tide_phase_incoming"
    assert out["ml_score_available"] is True
    assert out["data_fetcher_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_data_fetcher_stale_flag(
    fetcher_urls, lazy_models, lazy_spots,
):
    """ActivityScore older than 35min sets ``conditions_stale=True`` (D-03.2)."""
    from agent.nodes.data_fetcher import data_fetcher_node
    from agent.spot_resolver import reset_for_test

    sync_url = fetcher_urls["sync_url"]
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM activity_scores"))
            conn.execute(sa.text("DELETE FROM fishing_spots"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
            conn.execute(
                sa.text(
                    "INSERT INTO noaa_stations (station_id, name, lat, lon, products, source_url) "
                    "VALUES (:sid, 'Stale Stn', 40.0, -74.0, :prods, 'https://test')"
                ),
                {"sid": "STALE_STN", "prods": ["water_level"]},
            )
            row = conn.execute(
                sa.text(
                    "INSERT INTO fishing_spots "
                    "(name, lat, lon, water_body, spot_type, species, "
                    "nearest_station, access_type) "
                    "VALUES ('Stale Spot', 40.0, -74.0, 'Test', 'jetty', "
                    "ARRAY['striper'], :ns, 'shore') RETURNING spot_id"
                ),
                {"ns": "STALE_STN"},
            ).first()
            spot_id = int(row[0])
            conn.execute(
                sa.text(
                    "INSERT INTO activity_scores "
                    "(spot_id, species, time, score, shap_values, model_version, "
                    "confidence, is_forecast, raw_payload) "
                    "VALUES (:sid, 'striper', :t, 0.5, "
                    "CAST(:shap AS JSONB), 'test-1.0', 'low', false, "
                    "CAST(:rp AS JSONB))"
                ),
                {
                    "sid": spot_id,
                    "t": datetime.now(timezone.utc) - timedelta(minutes=60),
                    "shap": '{"top_features": []}',
                    "rp": '{"features": {"tide_height_m": 0.1}}',
                },
            )
            # Stale tidal observation — drives the conditions_stale flag now
            # that conditions are read from raw tables rather than ActivityScore.
            conn.execute(
                sa.text(
                    "INSERT INTO tidal_observations "
                    "(station_id, time, water_level_m, raw_payload) "
                    "VALUES ('STALE_STN', :t, 0.1, CAST('{}' AS JSONB))"
                ),
                {"t": datetime.now(timezone.utc) - timedelta(minutes=60)},
            )

        reset_for_test([
            {"id": spot_id, "name": "Stale Spot", "lat": 40.0, "lon": -74.0},
        ])
        out = await data_fetcher_node({
            "query": "stale",
            "species_canonical": "striper",
            "location_hint_raw": "Stale Spot",
        })
        assert out["conditions_stale"] is True
        assert out["data_age_seconds"] is not None
        assert out["data_age_seconds"] > 1800
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM activity_scores"))
            conn.execute(sa.text("DELETE FROM tidal_observations"))
            conn.execute(sa.text("DELETE FROM fishing_spots"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
        engine.dispose()


@pytest.mark.asyncio
async def test_data_fetcher_no_pin_topn_fallback(
    fetcher_urls, lazy_models, lazy_spots,
):
    """Unresolvable hint + species → top-N fallback hits the highest-scored spot (D-05.3)."""
    from agent.nodes.data_fetcher import data_fetcher_node
    from agent.spot_resolver import reset_for_test

    sync_url = fetcher_urls["sync_url"]
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM activity_scores"))
            conn.execute(sa.text("DELETE FROM fishing_spots"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
            conn.execute(
                sa.text(
                    "INSERT INTO noaa_stations (station_id, name, lat, lon, products, source_url) "
                    "VALUES ('TOPN_STN', 'TopN Stn', 39.5, -74.5, :prods, 'https://test')"
                ),
                {"prods": ["water_level"]},
            )
            row = conn.execute(
                sa.text(
                    "INSERT INTO fishing_spots "
                    "(name, lat, lon, water_body, spot_type, species, "
                    "nearest_station, access_type) "
                    "VALUES ('High Score Spot', 39.5, -74.5, 'Test', 'jetty', "
                    "ARRAY['striper'], 'TOPN_STN', 'shore') RETURNING spot_id"
                ),
            ).first()
            spot_id = int(row[0])
            conn.execute(
                sa.text(
                    "INSERT INTO activity_scores "
                    "(spot_id, species, time, score, shap_values, model_version, "
                    "confidence, is_forecast, raw_payload) "
                    "VALUES (:sid, 'striper', :t, 0.95, "
                    "CAST(:shap AS JSONB), 'test-1.0', 'high', false, "
                    "CAST(:rp AS JSONB))"
                ),
                {
                    "sid": spot_id,
                    "t": datetime.now(timezone.utc),
                    "shap": '{"top_features": []}',
                    "rp": '{"features": {}}',
                },
            )

        # IMPORTANT: reset the resolver with a SPOT NOT in the user query
        # AND the user gives a hint that won't fuzzy-match.
        reset_for_test([
            {"id": spot_id, "name": "Totally Unrelated Place", "lat": 39.5, "lon": -74.5},
        ])

        out = await data_fetcher_node({
            "query": "striper somewhere unknown",
            "species_canonical": "striper",
            "location_hint_raw": "ZZTOPVILLE",  # won't fuzzy-match
        })
        # Either fuzzy_name (rare false-positive) or no_pin → top-N hit.
        # The contract is: spot_id ends up as our seeded spot_id.
        assert out.get("spot_id") == spot_id, (
            f"expected top-N fallback to spot {spot_id}; got {out!r}"
        )
        # If no_pin path was taken, ml_score_available True from persisted.
        assert out["ml_score"] == pytest.approx(0.95)
        assert out["ml_score_available"] is True
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM activity_scores"))
            conn.execute(sa.text("DELETE FROM fishing_spots"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
        engine.dispose()


@pytest.mark.asyncio
async def test_xgb_under_50ms(lazy_models):
    """P-06: XGBoost inference per call ≤ 50 ms.

    No-op when no production model is loaded (Phase 2 0/5 promoted) — the
    test exists so a future plan that promotes a real model has a green
    baseline. Skipped when ``SPECIES_MODELS`` is empty.
    """
    from ml.model import SPECIES_MODELS, score_one

    if not SPECIES_MODELS:
        pytest.skip("no production model loaded — P-06 deferred to integration env")

    import numpy as np

    from ml.features import FEATURE_NAMES

    species = next(iter(SPECIES_MODELS.keys()))
    x_row = np.zeros(len(FEATURE_NAMES), dtype=float)
    t0 = time.perf_counter()
    score_one(species, x_row)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms <= 50, (
        f"XGBoost inference {elapsed_ms:.1f}ms exceeds 50ms gate (P-06)"
    )
