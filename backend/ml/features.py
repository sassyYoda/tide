"""Temporal-safe feature engineering (M-01, M-14 — PITFALLS.md §1).

Invariant: for every (spot_id, t) row, EVERY lag/rolling/windowed feature uses
only data with ``time <= (t - GUARD)``. Solunar values are read at exactly t
because they are deterministic functions of astronomical time (pure math,
cannot leak label information).

Every windowed query has a hard ``time <= :hi_bound`` filter. The
``_feature_source_times`` field on the returned DataFrame row records the
maximum source timestamps used per block, for post-hoc leakage audits.

ORM-column alignment notes (Rule-3 deviations from PLAN draft):
- ``WeatherObservation`` actually exposes ``surface_pressure_hpa``,
  ``wind_speed_ms``, ``wind_dir_deg``, ``temperature_2m_c`` and
  ``precipitation_prob_pct`` — the plan draft used the older Plan-1 names.
- ``SolunarValue`` already supplies ``moon_phase_sin`` and ``moon_phase_cos``;
  ``is_major_period`` and ``hours_to_next_major`` are derived in this module
  from ``next_major_start`` / ``next_major_end``.
- ``compute_pressure_trend`` returns labels ``Rapid Rise`` / ``Rising`` /
  ``Steady`` / ``Falling`` / ``Rapid Fall``. The one-hot mapping below uses
  these literal labels rather than the plan draft's shorter aliases.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    SolunarValue,
    TidalObservation,
    WeatherObservation,
)
from ingest.pressure import compute_pressure_trend
from ml.species_config import SPECIES_CONFIG

log = logging.getLogger(__name__)

# PITFALLS.md §1 — hard upper-bound shift to avoid right-edge leakage.
GUARD = timedelta(seconds=1)

# Canonical spot_type set (D-13) — mirrors seeds/fishing_spots.json values.
SPOT_TYPES: tuple[str, ...] = ("jetty", "inlet", "flat", "surf", "channel", "pier")

# Pressure-trend categorical → one-hot column names. Labels match the actual
# strings produced by ``ingest.pressure.compute_pressure_trend``.
_PRESSURE_TREND_COLS: dict[str, str] = {
    "Rapid Rise": "pressure_trend_rapid_rise",
    "Rising": "pressure_trend_rise",
    "Steady": "pressure_trend_steady",
    "Falling": "pressure_trend_fall",
    "Rapid Fall": "pressure_trend_rapid_fall",
}

# Stable canonical column order. Downstream training / inference code MUST
# import this constant; never recompute on its own.
FEATURE_NAMES: list[str] = (
    # Tidal
    ["water_level_m", "water_temp_c", "tidal_rising"]
    # Atmospheric
    + ["pressure_hpa", "pressure_delta_1h", "pressure_delta_3h", "pressure_delta_6h"]
    + [
        "pressure_trend_rapid_rise",
        "pressure_trend_rise",
        "pressure_trend_steady",
        "pressure_trend_fall",
        "pressure_trend_rapid_fall",
    ]
    + ["wind_speed_mps", "wind_sin", "wind_cos", "precip_flag", "air_temp_c"]
    # Solunar
    + [
        "moon_phase_sin",
        "moon_phase_cos",
        "illumination",
        "lunar_day",
        "solunar_quality",
        "is_major_period",
        "hours_to_next_major",
    ]
    # Temporal (cyclic encoding)
    + ["hour_sin", "hour_cos", "month_sin", "month_cos", "dow_sin", "dow_cos"]
    # Water (lag features)
    + [
        "water_temp_lag_1h",
        "water_temp_lag_3h",
        "water_temp_lag_6h",
        "water_level_lag_1h",
        "water_level_lag_3h",
        "water_level_lag_6h",
    ]
    # Species-match flags (0/1, depends on the `species` arg per row)
    + ["match_temp_range", "match_tide_phase", "match_pressure"]
    # Spot-type one-hot (D-13)
    + [f"spot_is_{t}" for t in SPOT_TYPES]
)


# ---------------------------------------------------------------------------
# Per-block feature builders
# ---------------------------------------------------------------------------


async def _tidal_block(
    session: AsyncSession, station_id: str, hi_bound: datetime
) -> dict:
    """Tidal observations within [hi_bound - 12h, hi_bound] inclusive."""
    since = hi_bound - timedelta(hours=12)
    q = (
        select(
            TidalObservation.time,
            TidalObservation.water_level_m,
            TidalObservation.water_temp_c,
        )
        .where(TidalObservation.station_id == station_id)
        .where(TidalObservation.time >= since)
        .where(TidalObservation.time <= hi_bound)  # STRICT upper bound — PITFALLS.md §1
        .order_by(TidalObservation.time.desc())
    )
    rows = (await session.execute(q)).all()
    if not rows:
        return {
            "water_level_m": 0.0,
            "water_temp_c": 10.0,
            "tidal_rising": 0,
            "water_temp_lag_1h": 10.0,
            "water_temp_lag_3h": 10.0,
            "water_temp_lag_6h": 10.0,
            "water_level_lag_1h": 0.0,
            "water_level_lag_3h": 0.0,
            "water_level_lag_6h": 0.0,
            "_max_source_time": since,
        }
    newest = rows[0]
    prev = rows[1] if len(rows) > 1 else newest
    tidal_rising = 1 if (newest.water_level_m or 0.0) > (prev.water_level_m or 0.0) else 0

    def _lag(hours: int, col: str) -> float:
        target = hi_bound - timedelta(hours=hours)
        closest = min(rows, key=lambda r: abs((r.time - target).total_seconds()))
        return float(getattr(closest, col) or 0.0)

    return {
        "water_level_m": float(newest.water_level_m or 0.0),
        "water_temp_c": float(newest.water_temp_c or 10.0),
        "tidal_rising": tidal_rising,
        "water_temp_lag_1h": _lag(1, "water_temp_c"),
        "water_temp_lag_3h": _lag(3, "water_temp_c"),
        "water_temp_lag_6h": _lag(6, "water_temp_c"),
        "water_level_lag_1h": _lag(1, "water_level_m"),
        "water_level_lag_3h": _lag(3, "water_level_m"),
        "water_level_lag_6h": _lag(6, "water_level_m"),
        "_max_source_time": newest.time,
    }


async def _weather_block(
    session: AsyncSession, station_id: str, hi_bound: datetime
) -> dict:
    """Most-recent weather observation strictly at-or-before hi_bound."""
    since = hi_bound - timedelta(hours=6)
    q = (
        select(
            WeatherObservation.time,
            WeatherObservation.temperature_2m_c,
            WeatherObservation.surface_pressure_hpa,
            WeatherObservation.wind_speed_ms,
            WeatherObservation.wind_dir_deg,
            WeatherObservation.precipitation_prob_pct,
        )
        .where(WeatherObservation.station_id == station_id)
        .where(WeatherObservation.is_forecast.is_(False))
        .where(WeatherObservation.time >= since)
        .where(WeatherObservation.time <= hi_bound)  # STRICT upper bound
        .order_by(WeatherObservation.time.desc())
    )
    rows = (await session.execute(q)).all()
    if not rows:
        return {
            "pressure_hpa": 1013.0,
            "wind_speed_mps": 0.0,
            "wind_sin": 0.0,
            "wind_cos": 1.0,
            "precip_flag": 0,
            "air_temp_c": 15.0,
            "_max_source_time": since,
        }
    newest = rows[0]
    wind_rad = math.radians(float(newest.wind_dir_deg or 0.0))
    return {
        "pressure_hpa": float(newest.surface_pressure_hpa or 1013.0),
        "wind_speed_mps": float(newest.wind_speed_ms or 0.0),
        "wind_sin": math.sin(wind_rad),
        "wind_cos": math.cos(wind_rad),
        "precip_flag": 1 if (newest.precipitation_prob_pct or 0) > 50 else 0,
        "air_temp_c": float(newest.temperature_2m_c or 15.0),
        "_max_source_time": newest.time,
    }


async def _pressure_deltas(
    session: AsyncSession, station_id: str, hi_bound: datetime
) -> dict:
    """Reuses ``ingest.pressure.compute_pressure_trend``.

    History is loaded STRICTLY below ``hi_bound`` (PITFALLS.md §1 guard).
    """
    since = hi_bound - timedelta(hours=7)
    q = (
        select(WeatherObservation.time, WeatherObservation.surface_pressure_hpa)
        .where(WeatherObservation.station_id == station_id)
        .where(WeatherObservation.is_forecast.is_(False))
        .where(WeatherObservation.time >= since)
        .where(WeatherObservation.time <= hi_bound)  # STRICT upper bound
        .order_by(WeatherObservation.time.desc())
    )
    rows = (await session.execute(q)).all()
    history = [
        (r.time, float(r.surface_pressure_hpa or 1013.0))
        for r in rows
        if r.surface_pressure_hpa is not None
    ]
    if not history:
        return {
            "pressure_delta_1h": 0.0,
            "pressure_delta_3h": 0.0,
            "pressure_delta_6h": 0.0,
            "pressure_trend_rapid_rise": 0,
            "pressure_trend_rise": 0,
            "pressure_trend_steady": 1,
            "pressure_trend_fall": 0,
            "pressure_trend_rapid_fall": 0,
            "_max_source_time": since,
        }
    trend = compute_pressure_trend(history)
    label = trend.get("pressure_trend_label") or "Steady"
    out = {
        "pressure_delta_1h": float(trend.get("delta_1h") or 0.0),
        "pressure_delta_3h": float(trend.get("delta_3h") or 0.0),
        "pressure_delta_6h": float(trend.get("delta_6h") or 0.0),
        "_max_source_time": history[0][0],
    }
    for label_str, col in _PRESSURE_TREND_COLS.items():
        out[col] = 1 if label == label_str else 0
    return out


def _hours_to_next_major(t: datetime, next_major_start: datetime | None) -> float:
    if next_major_start is None:
        return 6.0
    if next_major_start.tzinfo is None:
        next_major_start = next_major_start.replace(tzinfo=timezone.utc)
    delta = next_major_start - t
    return max(delta.total_seconds() / 3600.0, 0.0)


def _is_major_period(
    t: datetime,
    next_major_start: datetime | None,
    next_major_end: datetime | None,
) -> int:
    if next_major_start is None or next_major_end is None:
        return 0
    if next_major_start.tzinfo is None:
        next_major_start = next_major_start.replace(tzinfo=timezone.utc)
    if next_major_end.tzinfo is None:
        next_major_end = next_major_end.replace(tzinfo=timezone.utc)
    return 1 if next_major_start <= t <= next_major_end else 0


async def _solunar_block(
    session: AsyncSession, station_id: str, t: datetime
) -> dict:
    """Solunar values are deterministic functions of astronomical time — NO GUARD.

    Reading solunar at exactly T cannot leak label information because solunar is
    computed from moon/sun ephemerides, not from catch data.
    """
    q = (
        select(SolunarValue)
        .where(SolunarValue.station_id == station_id)
        .where(SolunarValue.time <= t)
        .order_by(SolunarValue.time.desc())
        .limit(1)
    )
    row = (await session.execute(q)).scalars().first()
    if row is None:
        return {
            "moon_phase_sin": 0.0,
            "moon_phase_cos": 1.0,
            "illumination": 0.5,
            "lunar_day": 15.0,
            "solunar_quality": 0.5,
            "is_major_period": 0,
            "hours_to_next_major": 6.0,
            "_max_source_time": t,
        }
    return {
        "moon_phase_sin": float(row.moon_phase_sin),
        "moon_phase_cos": float(row.moon_phase_cos),
        "illumination": float(row.illumination),
        "lunar_day": float(row.lunar_day),
        "solunar_quality": float(row.quality_score),
        "is_major_period": _is_major_period(t, row.next_major_start, row.next_major_end),
        "hours_to_next_major": _hours_to_next_major(t, row.next_major_start),
        "_max_source_time": row.time,
    }


def _temporal_block(t: datetime) -> dict:
    """Cyclic encodings — pure function of t (no leakage risk)."""
    hour_rad = 2 * math.pi * t.hour / 24
    month_rad = 2 * math.pi * (t.month - 1) / 12
    dow_rad = 2 * math.pi * t.weekday() / 7
    return {
        "hour_sin": math.sin(hour_rad),
        "hour_cos": math.cos(hour_rad),
        "month_sin": math.sin(month_rad),
        "month_cos": math.cos(month_rad),
        "dow_sin": math.sin(dow_rad),
        "dow_cos": math.cos(dow_rad),
    }


def _species_match_flags(
    species: str, tidal: dict, weather: dict, pressure_deltas: dict
) -> dict:
    """Per-species binary match flags (M-01) using SPECIES_CONFIG lookup."""
    cfg = SPECIES_CONFIG.get(species)
    if cfg is None:
        return {"match_temp_range": 0, "match_tide_phase": 0, "match_pressure": 0}
    low, high = cfg["optimal_temp_range"]
    match_temp = 1 if low <= tidal["water_temp_c"] <= high else 0

    pref = cfg["preferred_tide_phase"]
    if pref == "outgoing":
        match_tide = 1 if tidal["tidal_rising"] == 0 else 0
    elif pref == "incoming":
        match_tide = 1 if tidal["tidal_rising"] == 1 else 0
    elif pref in ("slack", "moving"):
        match_tide = 1  # permissive for these categories
    else:
        match_tide = 0

    pressure_pref = cfg["pressure_preference"]
    delta_3h = pressure_deltas.get("pressure_delta_3h", 0.0)
    if pressure_pref in ("dropping", "falling"):
        match_pressure = 1 if delta_3h < -1.0 else 0
    elif pressure_pref == "rising":
        match_pressure = 1 if delta_3h > 1.0 else 0
    else:  # "stable" or unknown
        match_pressure = 1 if abs(delta_3h) < 1.0 else 0

    return {
        "match_temp_range": match_temp,
        "match_tide_phase": match_tide,
        "match_pressure": match_pressure,
    }


def _spot_onehot(spot_type: str | None) -> dict:
    """Returns a 0/1 dict with one column per known SPOT_TYPE.

    Unknown spot_type → all zeros (defensive — caller should prefer an explicit
    canonical value from seeds/fishing_spots.json).
    """
    return {f"spot_is_{t}": (1 if spot_type == t else 0) for t in SPOT_TYPES}


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


async def build_features_for_rows(
    session: AsyncSession,
    rows: Iterable[tuple[int, datetime, str]],
    spot_type_by_id: dict[int, str],
    station_id_by_spot: dict[int, str],
) -> pd.DataFrame:
    """Build features for a list of ``(spot_id, time, species)`` tuples.

    Args:
        session: live ``AsyncSession``.
        rows: iterable of ``(spot_id, t, species)``. ``t`` may be naive — it is
            promoted to UTC internally.
        spot_type_by_id: ``{spot_id → spot_type string}``.
        station_id_by_spot: ``{spot_id → tide/weather station_id}``.

    Returns:
        ``pd.DataFrame`` with columns
        ``["spot_id", "label_time", "species", *FEATURE_NAMES, "_feature_source_times"]``.
        ``_feature_source_times`` is a list of max source timestamps (one per
        backward-looking block) for post-hoc leakage audit.
    """
    out_rows: list[dict] = []
    for spot_id, t, species in rows:
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        hi_bound = t - GUARD
        station_id = station_id_by_spot.get(spot_id)
        if station_id is None:
            log.warning("No station_id for spot %s — skipping row", spot_id)
            continue
        tidal = await _tidal_block(session, station_id, hi_bound)
        weather = await _weather_block(session, station_id, hi_bound)
        pressure_d = await _pressure_deltas(session, station_id, hi_bound)
        solunar = await _solunar_block(session, station_id, t)  # solunar uses t, not hi_bound
        temporal = _temporal_block(t)
        species_flags = _species_match_flags(species, tidal, weather, pressure_d)
        spot_oh = _spot_onehot(spot_type_by_id.get(spot_id))

        record: dict = {"spot_id": spot_id, "label_time": t, "species": species}
        record.update({k: v for k, v in tidal.items() if not k.startswith("_")})
        record.update({k: v for k, v in weather.items() if not k.startswith("_")})
        record.update({k: v for k, v in pressure_d.items() if not k.startswith("_")})
        record.update({k: v for k, v in solunar.items() if not k.startswith("_")})
        record.update(temporal)
        record.update(species_flags)
        record.update(spot_oh)
        record["_feature_source_times"] = [
            tidal["_max_source_time"],
            weather["_max_source_time"],
            pressure_d["_max_source_time"],
            # solunar excluded — reads at exactly t by design (deterministic)
        ]
        out_rows.append(record)

    df = pd.DataFrame(out_rows)
    if not df.empty:
        for col in FEATURE_NAMES:
            if col not in df.columns:
                raise RuntimeError(
                    f"FEATURE_NAMES column {col!r} missing from built DataFrame"
                )
    return df


__all__ = ["GUARD", "SPOT_TYPES", "FEATURE_NAMES", "build_features_for_rows"]
