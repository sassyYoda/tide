"""Unit tests for scripts.backfill_history (no real network, no real DB)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
import respx
from httpx import Response


_NOAA_HOURLY_HEIGHT = {
    "data": [
        {"t": "2026-01-01 00:00", "v": "1.234", "s": "0.0", "f": "0,0,0,0", "q": "v"},
        {"t": "2026-01-01 01:00", "v": "1.456", "s": "0.0", "f": "0,0,0,0", "q": "v"},
    ]
}
_NOAA_WATER_TEMP = {
    "data": [
        {"t": "2026-01-01 00:00", "v": "5.6", "f": "0,0,0,0"},
        {"t": "2026-01-01 01:00", "v": "5.7", "f": "0,0,0,0"},
    ]
}
_NOAA_WIND = {
    "data": [
        {"t": "2026-01-01 00:00", "s": "3.2", "d": "180", "g": "5.0", "dr": "S", "f": "0,0"},
    ]
}
_NOAA_PRED = {
    "predictions": [
        {"t": "2026-01-01 02:00", "v": "1.5", "type": "H"},
        {"t": "2026-01-01 08:00", "v": "0.2", "type": "L"},
    ]
}
_METEO_HISTORICAL = {
    "hourly": {
        "time": ["2026-01-01T00:00", "2026-01-01T01:00", "2026-01-01T02:00"],
        "wind_speed_10m": [3.0, 3.5, 4.0],
        "wind_direction_10m": [180.0, 185.0, 190.0],
        "surface_pressure": [1015.0, 1014.5, 1014.0],
        "temperature_2m": [4.0, 4.5, 5.0],
        "precipitation_probability": [10.0, 15.0, 20.0],
        "cloud_cover": [40.0, 50.0, 55.0],
    }
}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_noaa_observations_merges_three_products():
    from scripts.backfill_history import fetch_noaa_observations
    import httpx

    respx.get("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter").mock(
        side_effect=lambda req: _route(req)
    )

    async with httpx.AsyncClient() as client:
        obs, preds = await fetch_noaa_observations(
            client, "8531680", ["water_level", "water_temperature", "wind"],
            date(2026, 1, 1), date(2026, 1, 1),
        )

    assert len(obs) == 2  # two distinct hourly timestamps
    sample = obs[datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)]
    assert sample["station_id"] == "8531680"
    assert sample["water_level_m"] == pytest.approx(1.234)
    assert sample["water_temp_c"] == pytest.approx(5.6)
    assert sample["wind_speed_ms"] == pytest.approx(3.2)
    assert sample["wind_dir_deg"] == pytest.approx(180.0)
    assert len(preds) == 2
    assert preds[0]["station_id"] == "8531680"
    assert preds[0]["hi_lo"] in ("H", "L")


@pytest.mark.asyncio
@respx.mock
async def test_hourly_height_no_data_falls_back_to_water_level():
    """When hourly_height returns 'No data was found' (recent dates not yet in
    the verified-archival product), the scraper retries with water_level and
    samples on the hour."""
    from scripts.backfill_history import fetch_noaa_observations
    import httpx

    no_data_payload = {
        "error": {"message": "No data was found. This product may not be offered."}
    }
    water_level_6min = {
        "data": [
            {"t": "2026-01-01 00:00", "v": "1.10", "f": "0,0,0,0", "q": "p"},
            {"t": "2026-01-01 00:06", "v": "1.12", "f": "0,0,0,0", "q": "p"},  # off-hour, dropped
            {"t": "2026-01-01 01:00", "v": "1.40", "f": "0,0,0,0", "q": "p"},
        ]
    }

    def _route_with_fallback(req):
        qp = dict(req.url.params)
        product = qp.get("product")
        if product == "hourly_height":
            return Response(200, json=no_data_payload)
        if product == "water_level":
            return Response(200, json=water_level_6min)
        if product == "water_temperature":
            return Response(200, json=_NOAA_WATER_TEMP)
        if product == "predictions":
            return Response(200, json=_NOAA_PRED)
        return Response(404, json={"error": {"message": "unexpected"}})

    respx.get("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter").mock(
        side_effect=_route_with_fallback
    )

    async with httpx.AsyncClient() as client:
        obs, _ = await fetch_noaa_observations(
            client, "8531680", ["water_level", "water_temperature"],
            date(2026, 1, 1), date(2026, 1, 1),
        )

    # Off-hour 00:06 must be filtered; only :00 timestamps survive
    times = sorted(obs.keys())
    assert datetime(2026, 1, 1, 0, 6, tzinfo=timezone.utc) not in times
    assert obs[datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)]["water_level_m"] == pytest.approx(1.10)
    assert obs[datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)]["water_level_m"] == pytest.approx(1.40)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_noaa_skips_wind_when_station_lacks_product():
    from scripts.backfill_history import fetch_noaa_observations
    import httpx

    respx.get("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter").mock(
        side_effect=lambda req: _route(req)
    )
    async with httpx.AsyncClient() as client:
        obs, _ = await fetch_noaa_observations(
            client, "8534720", ["water_level", "water_temperature"],
            date(2026, 1, 1), date(2026, 1, 1),
        )
    sample = obs[datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)]
    assert sample["wind_speed_ms"] is None
    assert sample["wind_dir_deg"] is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_meteo_historical_and_shape_rows():
    from scripts.backfill_history import fetch_meteo_historical, shape_meteo_rows
    import httpx

    respx.get("https://archive-api.open-meteo.com/v1/archive").mock(
        return_value=Response(200, json=_METEO_HISTORICAL)
    )
    async with httpx.AsyncClient() as client:
        raw = await fetch_meteo_historical(client, 40.46, -74.0, date(2026, 1, 1), date(2026, 1, 1))
    rows = shape_meteo_rows("8531680", raw)
    assert len(rows) == 3
    first = rows[0]
    assert first["station_id"] == "8531680"
    assert first["time"] == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert first["surface_pressure_hpa"] == pytest.approx(1015.0)
    assert first["precipitation_prob_pct"] == pytest.approx(10.0)
    assert first["source"] == "open_meteo_historical"


def test_compute_solunar_hours_emits_one_row_per_hour():
    from scripts.backfill_history import compute_solunar_hours

    rows = compute_solunar_hours(
        "8531680", 40.46, -74.0, date(2026, 1, 1), date(2026, 1, 1)
    )
    # 24 hours from 00:00 to 23:00 inclusive
    assert len(rows) == 24
    assert all(r["station_id"] == "8531680" for r in rows)
    # Validate solunar field shape — pure-ephem schema from ingest.solunar
    sample = rows[0]
    for key in (
        "moon_phase", "moon_phase_sin", "moon_phase_cos", "illumination",
        "lunar_day", "quality_score",
    ):
        assert key in sample
    assert 0.0 <= sample["moon_phase"] <= 1.0
    assert 0.0 <= sample["illumination"] <= 1.0


def test_noaa_chunks_walks_full_window_inclusive():
    from datetime import timedelta
    from scripts.backfill_history import _noaa_chunks

    chunks = _noaa_chunks(date(2026, 1, 1), date(2026, 4, 30), timedelta(days=90))
    # Should partition the 120-day window into 90+30
    assert chunks[0] == (date(2026, 1, 1), date(2026, 3, 31))
    assert chunks[1] == (date(2026, 4, 1), date(2026, 4, 30))
    # Re-merge must equal original
    assert chunks[0][0] == date(2026, 1, 1)
    assert chunks[-1][1] == date(2026, 4, 30)


def test_normalize_psycopg_url_strips_sqlalchemy_drivers():
    from scripts.backfill_history import _normalize_psycopg_url

    assert _normalize_psycopg_url("postgresql+psycopg2://u:p@h:5432/d") == \
        "postgresql://u:p@h:5432/d"
    assert _normalize_psycopg_url("postgresql+asyncpg://u:p@h:5432/d") == \
        "postgresql://u:p@h:5432/d"
    assert _normalize_psycopg_url("postgresql://u:p@h:5432/d") == \
        "postgresql://u:p@h:5432/d"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _route(req) -> Response:
    """Dispatch NOAA datagetter mock by ?product=..."""
    qp = dict(req.url.params)
    product = qp.get("product")
    if product == "hourly_height":
        return Response(200, json=_NOAA_HOURLY_HEIGHT)
    if product == "water_temperature":
        return Response(200, json=_NOAA_WATER_TEMP)
    if product == "wind":
        return Response(200, json=_NOAA_WIND)
    if product == "predictions":
        return Response(200, json=_NOAA_PRED)
    return Response(404, json={"error": {"message": f"unknown product {product}"}})
