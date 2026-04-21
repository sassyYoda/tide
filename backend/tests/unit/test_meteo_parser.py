"""Unit tests for Open-Meteo shape_meteo_row."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest.meteo_client import shape_meteo_row


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
