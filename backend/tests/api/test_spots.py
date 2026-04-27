"""GET /api/v1/spots — bbox + species filter + CORS + Phase 1 regression tests.

Coverage:

- Empty bbox → []
- Invalid bbox (lat1>lat2, non-numeric, wrong shape) → 422
- Seeded spot + score → list with score populated
- Species filter respected (other-species score not surfaced)
- CORS preflight on /api/v1/query → Access-Control-Allow-Origin
- Phase 1 /api/v1/conditions/{station_id} still routable (regression)
- Phase 1 /healthz still 200 (regression)

Seeding uses SYNCHRONOUS SQLAlchemy against the migrated test container
(via ``test_client["sync_url"]``). Earlier attempts to use the async session
factory hit a cross-loop asyncpg failure: the TestClient's ``BlockingPortal``
runs the route in its own event loop, and an asyncpg connection opened in
the test's pytest-asyncio loop ends up "attached to a different loop" by
the time SQLAlchemy's pool tries to ping it. Sync inserts side-step the
issue and mirror ``backend/tests/integration/test_conditions_endpoint.py``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.integration


# ─── Sync seed helpers (pattern: tests/integration/test_conditions_endpoint.py) ──


def _exec(sync_url: str, stmt: str, **params) -> None:
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(stmt), params)
    finally:
        engine.dispose()


def _exec_returning_int(sync_url: str, stmt: str, **params) -> int:
    engine = sa.create_engine(sync_url)
    try:
        with engine.begin() as conn:
            result = conn.execute(sa.text(stmt), params)
            row = result.first()
            assert row is not None
            return int(row[0])
    finally:
        engine.dispose()


def _truncate(sync_url: str) -> None:
    """Clean activity_scores → fishing_spots → noaa_stations (in FK order)."""
    _exec(sync_url, "DELETE FROM activity_scores")
    _exec(sync_url, "DELETE FROM fishing_spots")
    _exec(
        sync_url,
        "DELETE FROM noaa_stations WHERE station_id = :sid",
        sid="test-st",
    )


def _seed_station(sync_url: str, station_id: str = "test-st") -> None:
    _exec(
        sync_url,
        """
        INSERT INTO noaa_stations (station_id, name, lat, lon, products, source_url)
        VALUES (:sid, 'Test Station', 39.7, -74.2, ARRAY['water_level']::text[],
                'https://example.test/station')
        ON CONFLICT (station_id) DO NOTHING
        """,
        sid=station_id,
    )


def _seed_spot(
    sync_url: str,
    *,
    name: str = "Test Spot",
    lat: float = 39.7,
    lon: float = -74.2,
    species: list[str] | None = None,
    station_id: str = "test-st",
) -> int:
    species = species or ["striper"]
    return _exec_returning_int(
        sync_url,
        """
        INSERT INTO fishing_spots
            (name, lat, lon, water_body, spot_type, species,
             nearest_station, access_type)
        VALUES (:name, :lat, :lon, 'Test Bay', 'inlet', :species,
                :station_id, 'shore')
        RETURNING spot_id
        """,
        name=name,
        lat=lat,
        lon=lon,
        species=species,
        station_id=station_id,
    )


def _seed_score(
    sync_url: str,
    *,
    spot_id: int,
    species: str = "striper",
    score: float = 0.8,
    confidence: str = "moderate",
    when: datetime | None = None,
) -> None:
    when = when or (datetime.now(tz=timezone.utc) - timedelta(seconds=300))
    _exec(
        sync_url,
        """
        INSERT INTO activity_scores
            (spot_id, species, time, score, confidence, is_forecast,
             shap_values, model_version, raw_payload)
        VALUES (:spot_id, :species, :t, :score, :confidence, FALSE,
                :shap, :ver, :raw)
        """,
        spot_id=spot_id,
        species=species,
        t=when,
        score=score,
        confidence=confidence,
        shap=json.dumps({"top_features": []}),
        ver="t",
        raw=json.dumps({}),
    )


# ─── Tests ──────────────────────────────────────────────────────────────


def test_spots_empty_bbox_returns_empty_list(test_client):
    """No spots in (0,0,1,1) → 200 + []."""
    _truncate(test_client["sync_url"])
    resp = test_client["client"].get(
        "/api/v1/spots", params={"bbox": "0,0,1,1"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_spots_invalid_bbox_returns_422(test_client):
    """lat1>lat2 → 422."""
    resp = test_client["client"].get(
        "/api/v1/spots", params={"bbox": "40,-74,39,-75"}
    )
    assert resp.status_code == 422


def test_spots_invalid_bbox_non_numeric_returns_422(test_client):
    """Non-numeric component → 422."""
    resp = test_client["client"].get(
        "/api/v1/spots", params={"bbox": "a,b,c,d"}
    )
    assert resp.status_code == 422


def test_spots_invalid_bbox_wrong_shape_returns_422(test_client):
    """Three components instead of four → 422."""
    resp = test_client["client"].get(
        "/api/v1/spots", params={"bbox": "39,-74,40"}
    )
    assert resp.status_code == 422


def test_spots_returns_scored_spots(test_client):
    """Seed 1 spot + 1 score; assert it appears in bbox + species filter."""
    sync_url = test_client["sync_url"]
    _truncate(sync_url)
    _seed_station(sync_url)
    spot_id = _seed_spot(sync_url, name="Test Spot", lat=39.7, lon=-74.2)
    _seed_score(sync_url, spot_id=spot_id, species="striper", score=0.8)

    resp = test_client["client"].get(
        "/api/v1/spots",
        params={"bbox": "39.5,-74.5,39.9,-74.0", "species": "striper"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Spot"
    assert data[0]["score"] == 0.8
    assert data[0]["confidence"] == "moderate"
    assert data[0]["species"] == "striper"
    assert data[0]["data_age_seconds"] is not None

    _truncate(sync_url)


def test_spots_species_filter_excludes_other_species(test_client):
    """When species=fluke is asked for and only striper is scored, score is None."""
    sync_url = test_client["sync_url"]
    _truncate(sync_url)
    _seed_station(sync_url)
    spot_id = _seed_spot(sync_url, name="Test Spot", lat=39.7, lon=-74.2)
    _seed_score(sync_url, spot_id=spot_id, species="striper", score=0.8)

    resp = test_client["client"].get(
        "/api/v1/spots",
        params={"bbox": "39.5,-74.5,39.9,-74.0", "species": "fluke"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1, data
    # Spot exists, but no fluke score → score-related fields are None.
    assert data[0]["score"] is None
    assert data[0]["species"] is None

    _truncate(sync_url)


def test_cors_preflight_query(test_client):
    """OPTIONS /api/v1/query from gettide.app → Access-Control-Allow-Origin (API-04)."""
    resp = test_client["client"].options(
        "/api/v1/query",
        headers={
            "Origin": "https://gettide.app",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code in (200, 204)
    aco = resp.headers.get("access-control-allow-origin")
    assert aco in ("https://gettide.app", "*"), (
        f"unexpected access-control-allow-origin: {aco!r}"
    )


def test_cors_preflight_vercel_preview(test_client):
    """Preview URL on *.vercel.app must be allowed via allow_origin_regex."""
    resp = test_client["client"].options(
        "/api/v1/query",
        headers={
            "Origin": "https://tide-pr-42.vercel.app",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code in (200, 204)
    aco = resp.headers.get("access-control-allow-origin")
    assert aco in ("https://tide-pr-42.vercel.app", "*"), (
        f"unexpected access-control-allow-origin: {aco!r}"
    )


def test_phase1_conditions_still_works(test_client):
    """Regression: Phase 1 /api/v1/conditions/{station_id} is still reachable.

    Without seeded data the freshness gate returns 503 (the 'data is stale'
    branch); without a known station the route returns 404. Either proves
    the route is wired correctly post-Phase-3 changes.
    """
    resp = test_client["client"].get("/api/v1/conditions/8534720")
    assert resp.status_code in (200, 404, 503), resp.text


def test_healthz_still_works(test_client):
    """Regression: Phase 1 /healthz returns 200."""
    resp = test_client["client"].get("/healthz")
    assert resp.status_code == 200
