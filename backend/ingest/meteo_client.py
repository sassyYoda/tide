"""Async Open-Meteo API client.

Open-Meteo is a free (attribution-only) weather API. We fetch the ``current``
block (instantaneous values at the lat/lon) plus a 7-day hourly forecast
(168 rows) from the same endpoint in a single round-trip.

``fetch_open_meteo`` returns the raw response dict; ``shape_meteo_row``
projects the ``current`` block into an observation row (``is_forecast=False``);
``shape_meteo_forecast_rows`` pivots the ``hourly`` arrays into per-hour
forecast rows (``is_forecast=True``) where ``time`` carries the forecast's
target hour. Pressure-trend computation lives in ``ingest/pressure.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class WeatherObservationRow(TypedDict, total=False):
    station_id: str
    time: datetime
    is_forecast: bool
    wind_speed_ms: float | None
    wind_dir_deg: float | None
    surface_pressure_hpa: float | None
    temperature_2m_c: float | None
    precipitation_prob_pct: float | None
    cloud_cover_pct: float | None
    source: str
    raw_payload: dict[str, Any]


# Open-Meteo free tier supports up to 16 forecast_days; we pull 7 (168h) to
# cover a typical "stripers Saturday morning?" question without burning quota.
FORECAST_DAYS = 7


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def fetch_open_meteo(
    lat: float,
    lon: float,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetch the combined current + hourly Open-Meteo forecast for (lat, lon)."""
    params = {
        "latitude": str(lat),
        "longitude": str(lon),
        "current": (
            "wind_speed_10m,wind_direction_10m,surface_pressure,"
            "temperature_2m,precipitation,cloud_cover"
        ),
        "hourly": (
            "wind_speed_10m,wind_direction_10m,surface_pressure,"
            "temperature_2m,precipitation_probability,cloud_cover"
        ),
        # 7-day hourly forecast (168 rows). Free tier allows up to 16 days.
        "forecast_days": str(FORECAST_DAYS),
        "timezone": "UTC",
        "windspeed_unit": "ms",
    }
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        resp = await client.get(OPEN_METEO_BASE, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns:
            await client.aclose()


def _parse_iso_utc(raw: str) -> datetime:
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _hourly_precip_prob_for(
    raw: dict[str, Any], obs_time: datetime
) -> float | None:
    """Look up ``precipitation_probability`` from the hourly forecast block.

    Open-Meteo's ``current`` block does NOT expose ``precipitation_probability``
    (that field is ``hourly``-only); ``current.precipitation`` is millimetres
    of precipitation, a different physical quantity. To populate
    ``precipitation_prob_pct`` correctly we have to index into the hourly
    arrays at the hour matching ``obs_time``. Returns ``None`` if the lookup
    fails for any reason (missing block, missing hour, non-numeric value).
    """
    hourly = raw.get("hourly") or {}
    hourly_times = hourly.get("time") or []
    probs = hourly.get("precipitation_probability") or []
    if not hourly_times or not probs:
        return None
    # Open-Meteo hourly keys are like "2026-04-20T15:00" — strip minutes/secs.
    key = obs_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
    try:
        idx = hourly_times.index(key)
    except ValueError:
        return None
    if idx >= len(probs):
        return None
    return _coerce_float(probs[idx])


def shape_meteo_row(
    station_id: str,
    raw: dict[str, Any],
    when: datetime | None = None,
) -> WeatherObservationRow:
    """Project the ``current`` block of ``raw`` to a WeatherObservationRow."""
    current = raw.get("current") or {}
    obs_time: datetime
    raw_time = current.get("time")
    if raw_time:
        obs_time = _parse_iso_utc(raw_time)
    elif when is not None:
        obs_time = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    else:
        obs_time = datetime.now(timezone.utc)

    # precipitation_prob_pct MUST be sourced from hourly.precipitation_probability
    # (percent), not current.precipitation (millimetres) — different quantities
    # with different units. See CR-02.
    precipitation_prob_pct = _hourly_precip_prob_for(raw, obs_time)

    return {
        "station_id": station_id,
        "time": obs_time,
        "is_forecast": False,
        "wind_speed_ms": _coerce_float(current.get("wind_speed_10m")),
        "wind_dir_deg": _coerce_float(current.get("wind_direction_10m")),
        "surface_pressure_hpa": _coerce_float(current.get("surface_pressure")),
        "temperature_2m_c": _coerce_float(current.get("temperature_2m")),
        "precipitation_prob_pct": precipitation_prob_pct,
        "cloud_cover_pct": _coerce_float(current.get("cloud_cover")),
        "source": "open_meteo",
        "raw_payload": raw,
    }


def shape_meteo_forecast_rows(
    station_id: str,
    raw: dict[str, Any],
) -> list[WeatherObservationRow]:
    """Pivot the ``hourly`` block of ``raw`` into one row per forecast hour.

    Each returned row has ``is_forecast=True`` and ``time`` set to the hour's
    target wall-clock time (as parsed from ``hourly.time[i]``, treated as UTC
    because the request specified ``timezone=UTC``).

    Returns an empty list if the hourly block is missing or empty — the
    observation path remains independent. ``raw_payload`` on each row carries
    a thin per-hour dict (not the full response) to keep storage costs bounded
    when N stations × 168 rows write per beat tick.
    """
    hourly = raw.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return []
    wind_speed = hourly.get("wind_speed_10m") or []
    wind_dir = hourly.get("wind_direction_10m") or []
    pressure = hourly.get("surface_pressure") or []
    temperature = hourly.get("temperature_2m") or []
    precip_prob = hourly.get("precipitation_probability") or []
    cloud = hourly.get("cloud_cover") or []

    out: list[WeatherObservationRow] = []
    for idx, t_str in enumerate(times):
        try:
            target_time = _parse_iso_utc(t_str)
        except (ValueError, TypeError):
            continue
        row: WeatherObservationRow = {
            "station_id": station_id,
            "time": target_time,
            "is_forecast": True,
            "wind_speed_ms": _coerce_float(
                wind_speed[idx] if idx < len(wind_speed) else None
            ),
            "wind_dir_deg": _coerce_float(
                wind_dir[idx] if idx < len(wind_dir) else None
            ),
            "surface_pressure_hpa": _coerce_float(
                pressure[idx] if idx < len(pressure) else None
            ),
            "temperature_2m_c": _coerce_float(
                temperature[idx] if idx < len(temperature) else None
            ),
            "precipitation_prob_pct": _coerce_float(
                precip_prob[idx] if idx < len(precip_prob) else None
            ),
            "cloud_cover_pct": _coerce_float(
                cloud[idx] if idx < len(cloud) else None
            ),
            "source": "open_meteo_forecast",
            # Store per-hour slice plus a back-reference to the request — keeps
            # the row replayable per D-09 without bloating 168 rows × N stations
            # with the full hourly array.
            "raw_payload": {
                "hour_index": idx,
                "target_time": t_str,
                "wind_speed_10m": wind_speed[idx] if idx < len(wind_speed) else None,
                "wind_direction_10m": (
                    wind_dir[idx] if idx < len(wind_dir) else None
                ),
                "surface_pressure": (
                    pressure[idx] if idx < len(pressure) else None
                ),
                "temperature_2m": (
                    temperature[idx] if idx < len(temperature) else None
                ),
                "precipitation_probability": (
                    precip_prob[idx] if idx < len(precip_prob) else None
                ),
                "cloud_cover": cloud[idx] if idx < len(cloud) else None,
                "latitude": raw.get("latitude"),
                "longitude": raw.get("longitude"),
                "generationtime_ms": raw.get("generationtime_ms"),
            },
        }
        out.append(row)
    return out


__all__ = [
    "OPEN_METEO_BASE",
    "FORECAST_DAYS",
    "WeatherObservationRow",
    "fetch_open_meteo",
    "shape_meteo_row",
    "shape_meteo_forecast_rows",
]
