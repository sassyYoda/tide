"""Unit tests for Open-Meteo shape_meteo_row + shape_meteo_forecast_rows."""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import pytest

from ingest.meteo_client import shape_meteo_forecast_rows, shape_meteo_row


FIXTURE = (
    Path(__file__).parent.parent
    / "fixtures"
    / "open_meteo_responses"
    / "forecast.json"
)


def test_shape_current():
    raw = json.loads(FIXTURE.read_text())
    row = shape_meteo_row("8534720", raw)
    assert row["station_id"] == "8534720"
    assert row["source"] == "open_meteo"
    assert row["is_forecast"] is False
    assert row["surface_pressure_hpa"] == pytest.approx(1014.6)
    assert row["wind_speed_ms"] == pytest.approx(4.1)
    assert row["wind_dir_deg"] == pytest.approx(218.0)
    assert row["temperature_2m_c"] == pytest.approx(14.2)
    assert row["cloud_cover_pct"] == pytest.approx(42.0)
    assert row["raw_payload"] is raw  # exact object for D-09 replay
    assert row["time"].tzinfo is not None


def test_coerces_none():
    raw = {"current": {"time": "2026-04-20T15:00", "surface_pressure": None}}
    row = shape_meteo_row("8534720", raw)
    assert row["surface_pressure_hpa"] is None
    assert row["wind_speed_ms"] is None
    assert row["is_forecast"] is False


def test_shape_forecast_rows_basic():
    """Hourly block in the fixture has 3 hours → 3 forecast rows, all tagged."""
    raw = json.loads(FIXTURE.read_text())
    rows = shape_meteo_forecast_rows("8534720", raw)
    assert len(rows) == 3
    for r in rows:
        assert r["station_id"] == "8534720"
        assert r["is_forecast"] is True
        assert r["source"] == "open_meteo_forecast"
        assert r["time"].tzinfo is not None
    # Spot check first hour values match the fixture index 0.
    first = rows[0]
    assert first["wind_speed_ms"] == pytest.approx(4.1)
    assert first["surface_pressure_hpa"] == pytest.approx(1014.6)
    assert first["precipitation_prob_pct"] == pytest.approx(5.0)
    assert first["cloud_cover_pct"] == pytest.approx(42.0)
    # raw_payload is the thin per-hour slice (not the full response).
    assert first["raw_payload"]["hour_index"] == 0
    assert first["raw_payload"]["latitude"] == raw["latitude"]


def test_shape_forecast_rows_168h_synthetic():
    """A synthetic 168-hour response yields exactly 168 forecast rows + 1 obs."""
    base = "2026-05-01T00:00"
    from datetime import datetime, timedelta

    base_dt = datetime.fromisoformat(base).replace(tzinfo=timezone.utc)
    times = [
        (base_dt + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(168)
    ]
    raw = {
        "latitude": 40.0,
        "longitude": -74.0,
        "current": {
            "time": base,
            "wind_speed_10m": 5.0,
            "wind_direction_10m": 180.0,
            "surface_pressure": 1013.0,
            "temperature_2m": 15.0,
            "precipitation": 0.0,
            "cloud_cover": 30,
        },
        "hourly": {
            "time": times,
            "wind_speed_10m": [5.0] * 168,
            "wind_direction_10m": [180.0] * 168,
            "surface_pressure": [1013.0 + i * 0.1 for i in range(168)],
            "temperature_2m": [15.0] * 168,
            "precipitation_probability": [10] * 168,
            "cloud_cover": [30] * 168,
        },
    }
    obs = shape_meteo_row("S1", raw)
    fcs = shape_meteo_forecast_rows("S1", raw)
    assert obs["is_forecast"] is False
    assert len(fcs) == 168
    assert all(r["is_forecast"] is True for r in fcs)
    # Last forecast hour is +167h from base; pressure ramps with index.
    assert fcs[-1]["surface_pressure_hpa"] == pytest.approx(1013.0 + 167 * 0.1)
    # Times are unique → no PK collisions when merged.
    seen = {r["time"] for r in fcs}
    assert len(seen) == 168


def test_shape_forecast_rows_empty_hourly():
    raw = {"current": {"time": "2026-04-20T15:00"}, "hourly": {}}
    assert shape_meteo_forecast_rows("S1", raw) == []


def test_fetch_open_meteo_includes_forecast_days_param():
    """The endpoint call must include forecast_days=9 so hourly arrays overshoot the 7d sweep."""
    import httpx
    import respx

    from ingest.meteo_client import OPEN_METEO_BASE, fetch_open_meteo, FORECAST_DAYS

    assert FORECAST_DAYS == 9

    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"current": {"time": "2026-04-20T15:00"}, "hourly": {"time": []}},
        )

    import asyncio

    async def _go():
        with respx.mock() as router:
            router.get(OPEN_METEO_BASE).mock(side_effect=_handler)
            return await fetch_open_meteo(40.0, -74.0)

    asyncio.run(_go())
    assert captured["params"].get("forecast_days") == "9"
