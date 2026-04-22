"""Async Open-Meteo API client.

Open-Meteo is a free (attribution-only) weather API. We fetch the ``current``
block (instantaneous values at the lat/lon) plus a 48h hourly forecast.

``fetch_open_meteo`` returns the raw response dict; ``shape_meteo_row``
projects the ``current`` block into a ``WeatherObservation``-shaped dict.
Pressure-trend computation lives in ``ingest/pressure.py``.
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
    wind_speed_ms: float | None
    wind_dir_deg: float | None
    surface_pressure_hpa: float | None
    temperature_2m_c: float | None
    precipitation_prob_pct: float | None
    cloud_cover_pct: float | None
    source: str
    raw_payload: dict[str, Any]


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
        "wind_speed_ms": _coerce_float(current.get("wind_speed_10m")),
        "wind_dir_deg": _coerce_float(current.get("wind_direction_10m")),
        "surface_pressure_hpa": _coerce_float(current.get("surface_pressure")),
        "temperature_2m_c": _coerce_float(current.get("temperature_2m")),
        "precipitation_prob_pct": precipitation_prob_pct,
        "cloud_cover_pct": _coerce_float(current.get("cloud_cover")),
        "source": "open_meteo",
        "raw_payload": raw,
    }


__all__ = [
    "OPEN_METEO_BASE",
    "WeatherObservationRow",
    "fetch_open_meteo",
    "shape_meteo_row",
]
