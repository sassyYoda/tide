"""Unit tests for NOAA response shaping (`_shape_rows`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest.noaa_client import NoaaAPIError, _shape_rows


FIXTURES = Path(__file__).parent.parent / "fixtures" / "noaa_responses"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_shape_all_products_present():
    wl = _load("water_level.json")
    wt = _load("water_temperature.json")
    wind = _load("wind.json")
    preds = _load("predictions.json")

    tidal, forecast = _shape_rows("8534720", wl, wt, wind, preds)

    assert len(tidal) == 1
    row = tidal[0]
    assert row["water_level_m"] == pytest.approx(0.845)
    assert row["water_temp_c"] == pytest.approx(11.5)
    assert row["wind_speed_ms"] == pytest.approx(4.2)
    assert row["source"] == "noaa_co-ops"
    assert "water_level" in row["raw_payload"]
    assert "water_temperature" in row["raw_payload"]
    assert "wind" in row["raw_payload"]
    assert len(forecast) == 48


def test_predictions_parse():
    wl = _load("water_level.json")
    wt = _load("water_temperature.json")
    preds = _load("predictions.json")
    _, forecast = _shape_rows("8534720", wl, wt, None, preds)
    assert len(forecast) == 48
    for f in forecast:
        assert f["station_id"] == "8534720"
        assert f["target_time"].tzinfo is not None
        assert f["target_time"].minute == 0  # hour-aligned
        assert isinstance(f["predicted_level_m"], float)
        assert f["source"] == "noaa_co-ops"


def test_partial_failure_returns_partial_row():
    """water_level fails but water_temperature succeeds → row emitted, water_level_m=None."""
    wt = _load("water_temperature.json")
    tidal, forecast = _shape_rows(
        "8534720",
        RuntimeError("boom"),
        wt,
        None,
        None,
    )
    assert len(tidal) == 1
    row = tidal[0]
    assert row["water_level_m"] is None
    assert row["water_temp_c"] == pytest.approx(11.5)
    assert forecast == []


def test_both_primary_products_fail_raises():
    with pytest.raises(NoaaAPIError):
        _shape_rows(
            "8534720",
            RuntimeError("wl"),
            RuntimeError("wt"),
            None,
            None,
        )
