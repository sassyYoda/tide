"""Unit tests for Pydantic response models (``app.models.response``)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.response import (
    ConditionsResponse,
    ErrorEnvelope,
    SolunarBlock,
    TidalBlock,
    WeatherBlock,
)


def _sample_response_dict() -> dict:
    now = datetime(2026, 4, 21, 14, 0, 0, tzinfo=timezone.utc)
    return {
        "station_id": "8534720",
        "station_name": "Atlantic City, NJ",
        "observed_at": now,
        "data_age_seconds": 120,
        "tidal": {
            "current_level_m": 0.84,
            "phase": "incoming",
            "water_temp_c": 14.5,
            "next_high": None,
            "next_high_level_m": None,
            "next_low": None,
            "next_low_level_m": None,
        },
        "weather": {
            "wind_speed_ms": 5.1,
            "wind_direction_deg": 210.0,
            "surface_pressure_hpa": 1015.3,
            "pressure_delta_1h": 0.4,
            "pressure_delta_3h": 1.2,
            "pressure_delta_6h": 2.3,
            "pressure_trend_label": "Rising",
            "air_temperature_c": 18.0,
            "precipitation_prob_pct": 10.0,
            "cloud_cover_pct": 40.0,
        },
        "solunar": {
            "moon_phase": 0.5,
            "illumination": 0.98,
            "lunar_day": 14.3,
            "next_major_start": None,
            "next_major_end": None,
            "next_minor_start": None,
            "next_minor_end": None,
            "quality_score": 0.72,
        },
        "sunrise": now,
        "sunset": now,
    }


def test_conditions_response_roundtrip():
    data = _sample_response_dict()
    resp = ConditionsResponse(**data)
    dumped = resp.model_dump()
    assert dumped["station_id"] == "8534720"
    assert dumped["tidal"]["phase"] == "incoming"
    assert dumped["weather"]["pressure_trend_label"] == "Rising"
    assert dumped["solunar"]["moon_phase"] == 0.5
    # Round-trip back through the model
    ConditionsResponse(**dumped)


def test_error_envelope_code_literal():
    ok = ErrorEnvelope(code="conditions_stale", message="x")
    assert ok.code == "conditions_stale"

    with pytest.raises(ValidationError):
        ErrorEnvelope(code="bogus", message="x")


def test_pressure_trend_label_literal():
    ok = WeatherBlock(pressure_trend_label="Rapid Rise")
    assert ok.pressure_trend_label == "Rapid Rise"

    with pytest.raises(ValidationError):
        WeatherBlock(pressure_trend_label="rapid rise")


def test_partial_blocks_allowed():
    tb = TidalBlock()
    assert tb.current_level_m is None
    assert tb.phase == "unknown"
    wb = WeatherBlock()
    assert wb.wind_speed_ms is None
    sb = SolunarBlock()
    # WR-02: SolunarBlock fields are None by default so a missing solunar
    # row is distinguishable from a genuine new-moon (0.0) reading.
    assert sb.moon_phase is None
    assert sb.illumination is None
    assert sb.quality_score is None
