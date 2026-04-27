"""M-10 + M-11 — scorer writes one ActivityScore per (spot, species) tick.

Integration test against the live Timescale testcontainer. ``ml.model``'s
``SPECIES_MODELS`` is monkeypatched with a deterministic stub so this test
verifies the pipeline plumbing (feature build → score → SHAP → DB write)
without depending on a real production-aliased MLflow artifact.

The Plan 02-05 production path is gated for every species, so a non-stubbed
run would skip every cell — this test deliberately asserts the happy-path
contract (M-10 / M-11) so a future plan that promotes a real model has a
green-baseline reference.
"""
from __future__ import annotations

import numpy as np
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scorer_urls(
    migrated_ingest_db, timescale_async_url, redis_container, monkeypatch
):
    """Repoint scorer code at the live Timescale + Redis testcontainers.

    Sync fixture form (parallel to ``test_ingest_e2e.ingest_urls``) so other
    sync fixtures (``seed_one_spot``) can depend on it without async-vs-sync
    fixture-mixing pitfalls. NullPool is used so every checkout is a fresh
    asyncpg connection bound to the current event loop — without it,
    pool_pre_ping intermittently triggers 'attached to a different loop'
    when the third test in this module runs (cached connection from a prior
    test's loop). No explicit dispose: NullPool has nothing to dispose.
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
    # No dispose needed — NullPool holds no idle connections.


@pytest.fixture
def seed_one_spot(scorer_urls):
    """Insert one NoaaStation + one FishingSpot so the scorer has work to do.

    Cleans up the rows after the test so re-runs aren't polluted by stale
    seed data. No environmental observations are seeded — the feature builder
    has graceful empty-row fallbacks (PITFALLS.md §1 strict-bound semantics
    return canonical defaults rather than crashing).
    """
    sync_url = scorer_urls["sync_url"]
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            # Wipe potentially-stale state from prior tests. Order matters
            # because of the FK chain: observations + activity_scores +
            # fishing_spots all reference noaa_stations.station_id, and
            # noaa_harmonic_forecasts also references it. Earlier integration
            # tests (e.g., tests/integration/test_ingest_e2e.py) populate
            # tidal_observations / weather_observations against the SAME
            # session-scoped Timescale container, so we must clear them
            # before deleting the parent station rows.
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
                    "sid": "TEST_STATION_1",
                    "name": "Test Station 1",
                    "lat": 40.0,
                    "lon": -74.0,
                    "products": ["water_level", "water_temperature"],
                    "url": "https://example.test/stations/TEST_STATION_1",
                },
            )
            conn.execute(
                sa.text(
                    "INSERT INTO fishing_spots "
                    "(name, lat, lon, water_body, spot_type, species, "
                    "nearest_station, access_type) "
                    "VALUES (:name, :lat, :lon, :wb, :st, :sp, :ns, :at)"
                ),
                {
                    "name": "Test Spot",
                    "lat": 40.0,
                    "lon": -74.0,
                    "wb": "Atlantic Ocean",
                    "st": "jetty",
                    "sp": ["striper", "fluke", "bluefish", "weakfish", "tautog"],
                    "ns": "TEST_STATION_1",
                    "at": "shore",
                },
            )
        yield "TEST_STATION_1"
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM activity_scores"))
            conn.execute(sa.text("DELETE FROM tidal_observations"))
            conn.execute(sa.text("DELETE FROM weather_observations"))
            conn.execute(sa.text("DELETE FROM noaa_harmonic_forecasts"))
            conn.execute(sa.text("DELETE FROM solunar_values"))
            conn.execute(sa.text("DELETE FROM fishing_spots"))
            conn.execute(sa.text("DELETE FROM noaa_stations"))
        engine.dispose()


@pytest_asyncio.fixture
async def stubbed_models(monkeypatch):
    """Monkeypatch SPECIES_MODELS + top_k_shap with deterministic stubs.

    The scorer test is inference-agnostic; we want to assert that the
    pipeline writes the right rows with the right shape, not that a real
    production model returns sensible numbers (Plan 02-05's gated outcome
    means there are no real production models to test against).
    """
    from ml import model as ml_model
    from ml import shap_utils as shap_utils

    class _StubCal:
        def predict_proba(self, X):
            # Return a fixed positive class probability of 0.7.
            n = X.shape[0]
            return np.tile(np.array([0.3, 0.7]), (n, 1))

    class _StubBase:
        pass

    stub = {
        sp: {
            "calibrated": _StubCal(),
            "base": _StubBase(),
            "model_version": "test-v0",
            "run_id": "abc123",
        }
        for sp in ("striper", "fluke", "bluefish", "weakfish", "tautog")
    }
    monkeypatch.setattr(ml_model, "SPECIES_MODELS", stub)
    # The scorer imports `from ml.model import SPECIES_MODELS` inside its
    # async helper. Patching the attribute on the module is sufficient —
    # the import is a deferred call site so it sees the patched dict.
    monkeypatch.setattr(
        shap_utils,
        "top_k_shap",
        lambda *a, **kw: [
            {"feature": "water_temp_c", "value": 0.5},
            {"feature": "pressure_delta_3h", "value": -0.3},
            {"feature": "spot_is_jetty", "value": 0.2},
        ],
    )
    yield stub


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scorer_writes_one_row_per_spot_species(
    seed_one_spot, stubbed_models
):
    """One ActivityScore per (spot, species) — 1 spot × 5 species = 5 rows."""
    from celery_app.tasks.scorer import _score_all_async
    from db.models import ActivityScore
    from db.session import async_session_factory

    result = await _score_all_async()
    assert result["success"] == 5, f"expected 5 writes, got {result}"
    assert result["failure"] == 0

    async with async_session_factory() as session:
        rows = (await session.execute(select(ActivityScore))).scalars().all()
    assert len(rows) == 5
    species_seen = {r.species for r in rows}
    assert species_seen == {"striper", "fluke", "bluefish", "weakfish", "tautog"}
    for r in rows:
        assert 0.0 <= r.score <= 1.0
        assert r.score == pytest.approx(0.7)
        assert "top_features" in r.shap_values
        assert len(r.shap_values["top_features"]) == 3
        assert r.model_version == "test-v0"
        assert r.confidence in ("high", "moderate", "low")
        assert r.is_forecast is False
        assert "features" in r.raw_payload
        # Feature dict must contain every FEATURE_NAMES entry.
        from ml.features import FEATURE_NAMES

        for feat in FEATURE_NAMES:
            assert feat in r.raw_payload["features"]


@pytest.mark.asyncio
async def test_scorer_shap_top_features_structure(
    seed_one_spot, stubbed_models
):
    """SHAP values JSONB has exactly 3 entries with feature/value keys."""
    from celery_app.tasks.scorer import _score_all_async
    from db.models import ActivityScore
    from db.session import async_session_factory

    await _score_all_async()
    async with async_session_factory() as session:
        first = (await session.execute(select(ActivityScore))).scalars().first()
    assert first is not None
    top = first.shap_values["top_features"]
    assert len(top) == 3
    for entry in top:
        assert set(entry.keys()) == {"feature", "value"}
        assert isinstance(entry["value"], float)


@pytest.mark.asyncio
async def test_scorer_is_idempotent_on_same_time_key(
    seed_one_spot, stubbed_models, monkeypatch
):
    """Composite PK (spot_id, species, time) — rerun at same `now` overwrites.

    Pins ``datetime.now`` inside the scorer module via a small wrapper so two
    consecutive ``_score_all_async`` calls land on the same composite-PK key.
    Using a wrapper class instead of subclassing the stdlib datetime keeps
    sqlalchemy's asyncpg adapter happy (subclassed datetimes have caused
    'attached to a different loop' errors in other test runs).
    """
    from datetime import datetime, timezone

    from celery_app.tasks import scorer as scorer_mod
    from db.models import ActivityScore
    from db.session import async_session_factory

    fixed_now = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)

    class _DatetimeProxy:
        """Forward all attrs to real datetime, override ``now``."""

        def __getattr__(self, name):
            return getattr(datetime, name)

        @staticmethod
        def now(tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(scorer_mod, "datetime", _DatetimeProxy())

    r1 = await scorer_mod._score_all_async()
    r2 = await scorer_mod._score_all_async()
    async with async_session_factory() as session:
        rows = (await session.execute(select(ActivityScore))).scalars().all()
    assert r1["success"] == r2["success"] == 5
    # Same composite PK on rerun → merge overwrites; row count stays at 5.
    assert len(rows) == 5
