"""Unit tests for the NOAA CO-OPS async client — no live internet."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
import respx

# Ensure tenacity does not sleep real time during tests.
os.environ["NOAA_TEST_NO_JITTER"] = "1"


from ingest.noaa_client import (  # noqa: E402
    NOAA_BASE,
    _fetch_product,
    fetch_all_products_for_station,
)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "noaa_responses"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class _FakeStation:
    def __init__(self, station_id: str, products: list[str]) -> None:
        self.station_id = station_id
        self.products = products


@pytest.mark.asyncio
async def test_retry_backoff(monkeypatch):
    """3 consecutive 500s → tenacity re-raises after exactly 3 attempts."""
    import tenacity

    # Neutralise real sleeps between tenacity attempts.
    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda *_args, **_kw: None)

    async def _no_async_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(tenacity.nap, "asleep", _no_async_sleep, raising=False)

    with respx.mock(assert_all_called=False) as router:
        route = router.get(NOAA_BASE).mock(
            side_effect=[
                httpx.Response(500, text="err1"),
                httpx.Response(500, text="err2"),
                httpx.Response(500, text="err3"),
            ]
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await _fetch_product(client, "8534720", "water_level")
        assert route.call_count == 3


@pytest.mark.asyncio
async def test_success_single_try():
    """One 200 → returns the parsed body without retries."""
    wl = _load("water_level.json")
    with respx.mock(assert_all_called=False) as router:
        route = router.get(NOAA_BASE).mock(return_value=httpx.Response(200, json=wl))
        async with httpx.AsyncClient() as client:
            data = await _fetch_product(client, "8534720", "water_level")
        assert route.call_count == 1
        assert data["data"][-1]["v"] == "0.845"


@pytest.mark.asyncio
async def test_fetch_all_products_for_station_shape():
    """Full station fetch returns one tidal row + N forecast rows.

    The forecast count is bounded by the static fixture (48 entries); the
    actual HTTP request uses ``range=168`` so the future-window covers a multi-day
    full 7-day horizon. We verify the ``range`` param explicitly below.
    """
    wl = _load("water_level.json")
    wt = _load("water_temperature.json")
    wind = _load("wind.json")
    preds = _load("predictions.json")

    captured_predictions_params: dict[str, str] = {}

    def _handler(request):
        product = request.url.params.get("product")
        if product == "water_level":
            return httpx.Response(200, json=wl)
        if product == "water_temperature":
            return httpx.Response(200, json=wt)
        if product == "wind":
            return httpx.Response(200, json=wind)
        if product == "predictions":
            captured_predictions_params.update(dict(request.url.params))
            return httpx.Response(200, json=preds)
        return httpx.Response(404)

    with respx.mock(assert_all_called=False) as router:
        router.get(NOAA_BASE).mock(side_effect=_handler)
        station = _FakeStation("8534720", ["water_level", "water_temperature", "wind"])
        tidal, forecast = await fetch_all_products_for_station(station)

    assert len(tidal) == 1
    row = tidal[0]
    assert row["station_id"] == "8534720"
    assert row["water_level_m"] == pytest.approx(0.845)
    assert row["water_temp_c"] == pytest.approx(11.5)
    assert row["wind_speed_ms"] == pytest.approx(4.2)
    assert row["source"] == "noaa_co-ops"
    assert row["time"].tzinfo is not None
    # Forecast row count equals what the fixture provides; the production
    # call requests 216h (9d) of harmonic predictions, verified below.
    assert len(forecast) == len(preds["predictions"])
    assert all(f["station_id"] == "8534720" for f in forecast)
    assert all(f["target_time"].tzinfo is not None for f in forecast)
    assert captured_predictions_params.get("range") == "216"


@pytest.mark.asyncio
async def test_water_level_request_sends_datum():
    """NOAA CO-OPS rejects ``water_level`` without a datum (400 "Wrong Datum").

    Regression for the Sep 2026 outage where every water_level poll 400'd and
    ``water_level_m`` went null across all stations. The observed-level request
    must carry ``datum=MLLW`` to match the predictions product.
    """
    wl = _load("water_level.json")
    captured: dict[str, str] = {}

    def _handler(request):
        captured.update(dict(request.url.params))
        return httpx.Response(200, json=wl)

    with respx.mock(assert_all_called=False) as router:
        router.get(NOAA_BASE).mock(side_effect=_handler)
        async with httpx.AsyncClient() as client:
            await _fetch_product(client, "8534720", "water_level")

    assert captured.get("product") == "water_level"
    assert captured.get("datum") == "MLLW"
