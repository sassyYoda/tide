"""Pydantic response models for the ``/conditions`` endpoint.

Structure mirrors RESEARCH.md §12 (canonical conditions contract).

Phase 1 deferral — ``TidalBlock.next_high`` / ``next_low`` /
``next_high_level_m`` / ``next_low_level_m`` are schema-reserved but always
None at Phase 1. Plan 05 pre-stages the underlying data in
``noaa_harmonic_forecasts``; the Phase 3 LangGraph agent populates them
without a breaking schema change. See 01-RESEARCH.md Open Question #2
(RESOLVED: deferred) and 01-CONTEXT.md <deferred> block.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PressureTrendLabel = Literal[
    "Rapid Rise", "Rising", "Steady", "Falling", "Rapid Fall"
]

TidalPhase = Literal["incoming", "outgoing", "slack", "unknown"]

ErrorCode = Literal[
    "conditions_stale", "conditions_unavailable", "station_not_found"
]


class TidalBlock(BaseModel):
    """Tidal block — every field optional (sensors may be offline)."""

    model_config = ConfigDict(from_attributes=True)

    current_level_m: float | None = None
    phase: TidalPhase = "unknown"
    water_temp_c: float | None = None
    # next_high / next_low are INTENTIONALLY None at Phase 1 — reserved
    # for Phase 3 LangGraph agent to populate from noaa_harmonic_forecasts.
    next_high: datetime | None = None
    next_high_level_m: float | None = None
    next_low: datetime | None = None
    next_low_level_m: float | None = None


class WeatherBlock(BaseModel):
    """Weather block — all sensor fields optional."""

    model_config = ConfigDict(from_attributes=True)

    wind_speed_ms: float | None = None
    wind_direction_deg: float | None = None
    surface_pressure_hpa: float | None = None
    pressure_delta_1h: float | None = None
    pressure_delta_3h: float | None = None
    pressure_delta_6h: float | None = None
    pressure_trend_label: PressureTrendLabel | None = None
    air_temperature_c: float | None = None
    precipitation_prob_pct: float | None = None
    cloud_cover_pct: float | None = None


class SolunarBlock(BaseModel):
    """Solunar block — computed values. Fields are Optional because the
    solunar beat task may not have run yet for a given station; see WR-02.
    Silent ``0.0`` substitution (``None or 0.0``) was removed — a genuine
    new-moon reading of 0.0 is distinguishable from a missing row at the
    cost of a nullable contract.
    """

    model_config = ConfigDict(from_attributes=True)

    moon_phase: float | None = None
    illumination: float | None = None
    lunar_day: float | None = None
    next_major_start: datetime | None = None
    next_major_end: datetime | None = None
    next_minor_start: datetime | None = None
    next_minor_end: datetime | None = None
    quality_score: float | None = None


class ConditionsResponse(BaseModel):
    """Full ``/conditions/{station_id}`` response payload."""

    model_config = ConfigDict(from_attributes=True)

    station_id: str
    station_name: str
    observed_at: datetime = Field(..., description="CAGG bucket start time")
    data_age_seconds: int
    tidal: TidalBlock
    weather: WeatherBlock
    solunar: SolunarBlock
    sunrise: datetime | None = None
    sunset: datetime | None = None


class ErrorEnvelope(BaseModel):
    """Canonical error body for 503 / 404 responses."""

    model_config = ConfigDict(from_attributes=True)

    code: ErrorCode
    message: str
    latest_bucket: datetime | None = None


__all__ = [
    "TidalBlock",
    "WeatherBlock",
    "SolunarBlock",
    "ConditionsResponse",
    "ErrorEnvelope",
    "PressureTrendLabel",
    "TidalPhase",
    "ErrorCode",
]
