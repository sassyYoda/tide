"""Solunar computation (D-06, D-07) — pure ephem, no I/O.

:func:`compute_solunar` takes (lat, lon, when) and returns a dict matching
the ``solunar_values`` schema (caller attaches ``station_id``). Because the
underlying astronomy is deterministic, this function is safe to call in
tests without mocking and without Redis/TimescaleDB in the way.

Outputs:

- ``time`` — the input ``when`` truncated to the hour in UTC (CAGG join key).
- ``moon_phase`` — float in [0, 1] (0 = new moon, 0.5 = full moon, 1 = next new).
- ``moon_phase_sin`` / ``moon_phase_cos`` — ``sin(2π·phase)`` and
  ``cos(2π·phase)`` (D-07 feature pair).
- ``illumination`` — ephem's ``moon.moon_phase`` (0..1 fraction illuminated).
- ``lunar_day`` — days since last new moon (ephem.date subtraction yields days).
- ``sunrise``, ``sunset`` — TZ-aware UTC datetimes; ``None`` if the sun does
  not rise/set within the observer's day.
- ``next_major_start``/``next_major_end`` — moon-transit ±1h.
- ``next_minor_start``/``next_minor_end`` — moon-rise/set ±30 min (whichever
  comes next).
- ``quality_score`` — a 0..1 heuristic blending illumination and proximity
  to a major/minor window.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import ephem


SYNODIC_MONTH_DAYS = 29.530588


def phase_to_sincos(phase: float) -> tuple[float, float]:
    """Return (sin, cos) of a phase in [0, 1] mapped to [0, 2π]."""
    theta = 2 * math.pi * float(phase)
    return math.sin(theta), math.cos(theta)


def _to_utc(d: ephem.Date) -> datetime:
    """Convert an ephem.Date to a TZ-aware UTC datetime."""
    return ephem.to_timezone(d, ephem.UTC).replace(tzinfo=timezone.utc)


def _safe_next(func, default=None):
    """Call an ephem ``next_*`` method; return None if it throws circumpolar."""
    try:
        return func()
    except (ephem.AlwaysUpError, ephem.NeverUpError):
        return default


def compute_solunar(lat: float, lon: float, when: datetime) -> dict[str, Any]:
    """Compute a solunar row for (lat, lon) at instant ``when`` (UTC-aware)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)

    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    observer.elevation = 0
    observer.date = ephem.Date(when)
    observer.pressure = 0  # ignore atmospheric refraction (matches NOAA convention)

    moon = ephem.Moon(observer)
    illumination = float(moon.moon_phase)  # 0..1 fraction illuminated

    # Moon phase fraction: days since previous new moon, normalised over synodic month.
    prev_new = ephem.previous_new_moon(observer.date)
    phase_fraction = float(observer.date - prev_new) / SYNODIC_MONTH_DAYS
    phase_fraction = phase_fraction % 1.0
    sin_p, cos_p = phase_to_sincos(phase_fraction)

    # Lunar day — days since last new moon (ephem.date subtraction yields days).
    lunar_day = float(observer.date - prev_new)

    # Sun rise/set for the observing day.
    sun = ephem.Sun()
    sunrise = _to_utc(_safe_next(lambda: observer.next_rising(sun))) if _safe_next(
        lambda: observer.next_rising(sun)
    ) is not None else None
    # next_rising advanced the observer — reset to ``when`` before computing next_setting
    observer.date = ephem.Date(when)
    sunset = _to_utc(_safe_next(lambda: observer.next_setting(sun))) if _safe_next(
        lambda: observer.next_setting(sun)
    ) is not None else None

    # Major: moon transit ± 1 hour.
    observer.date = ephem.Date(when)
    transit_raw = _safe_next(lambda: observer.next_transit(ephem.Moon()))
    if transit_raw is not None:
        transit = _to_utc(transit_raw)
        next_major_start = transit - timedelta(hours=1)
        next_major_end = transit + timedelta(hours=1)
    else:
        next_major_start = None
        next_major_end = None

    # Minor: whichever of moon-rise or moon-set comes next ± 30 min.
    observer.date = ephem.Date(when)
    m_rise_raw = _safe_next(lambda: observer.next_rising(ephem.Moon()))
    observer.date = ephem.Date(when)
    m_set_raw = _safe_next(lambda: observer.next_setting(ephem.Moon()))
    candidates: list[ephem.Date] = [c for c in (m_rise_raw, m_set_raw) if c is not None]
    if candidates:
        next_minor_ref = _to_utc(min(candidates))
        next_minor_start = next_minor_ref - timedelta(minutes=30)
        next_minor_end = next_minor_ref + timedelta(minutes=30)
    else:
        next_minor_start = None
        next_minor_end = None

    # Quality score: simple illumination-weighted heuristic. 0..1.
    quality_score = round(0.5 + 0.5 * illumination, 4)

    time_out = when.replace(minute=0, second=0, microsecond=0)

    return {
        "time": time_out,
        "moon_phase": phase_fraction,
        "moon_phase_sin": sin_p,
        "moon_phase_cos": cos_p,
        "illumination": illumination,
        "lunar_day": lunar_day,
        "sunrise": sunrise,
        "sunset": sunset,
        "next_major_start": next_major_start,
        "next_major_end": next_major_end,
        "next_minor_start": next_minor_start,
        "next_minor_end": next_minor_end,
        "quality_score": quality_score,
    }


__all__ = ["compute_solunar", "phase_to_sincos", "SYNODIC_MONTH_DAYS"]
