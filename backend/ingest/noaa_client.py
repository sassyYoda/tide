"""Async NOAA CO-OPS API client.

Calls the ``api.tidesandcurrents.noaa.gov/api/prod/datagetter`` endpoint for
the four products that matter to MVP fishing context:

- ``water_level`` — 6-minute tidal observations
- ``water_temperature`` — 6-minute surface temperature
- ``wind`` — surface wind (only at stations that publish it)
- ``predictions`` — 48h hourly harmonic tide predictions

One call to :func:`fetch_all_products_for_station` yields two lists:

- ``tidal_rows``: rows for the ``tidal_observations`` hypertable (one row per
  6-minute tick, with water_level / water_temp / wind merged).
- ``forecast_rows``: 48 rows for ``noaa_harmonic_forecasts`` (one per hour).

Retry policy (D-08): each ``_fetch_product`` call retries 3 times with
exponential backoff (1s, 4s, 16s) plus 0–2s random jitter. After the third
failure tenacity re-raises. ``_shape_rows`` handles partial failures — if
water_level OR water_temperature comes back but the other fails, a row is
still emitted with the failed field set to None. If BOTH fail, the per-station
poll is treated as a total failure and :class:`NoaaAPIError` is raised.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, TypedDict

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)


NOAA_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


class NoaaAPIError(RuntimeError):
    """Raised when the NOAA API returns malformed or unusable data."""


class TidalObservationRow(TypedDict, total=False):
    station_id: str
    time: datetime
    water_level_m: float | None
    water_temp_c: float | None
    wind_speed_ms: float | None
    wind_dir_deg: float | None
    current_speed_ms: float | None
    current_dir_deg: float | None
    source: str
    raw_payload: dict[str, Any]


class HarmonicForecastRow(TypedDict, total=False):
    station_id: str
    issued_at: datetime
    target_time: datetime
    predicted_level_m: float | None
    hi_lo: str | None
    source: str
    raw_payload: dict[str, Any]


# ---------------------------------------------------------------------------
# tenacity wait factory — respects NOAA_TEST_NO_JITTER=1 so unit tests can
# skip real backoff without monkeypatching tenacity internals.
#
# IMPORTANT (WR-08): ``NOAA_TEST_NO_JITTER`` is captured ONCE at module
# import time via the module-level constant ``_NOAA_TEST_NO_JITTER`` below.
# The env-var must be set BEFORE ``backend.ingest.noaa_client`` is imported
# for the no-jitter policy to take effect. Mutating the env-var from a
# pytest fixture AFTER import has no runtime effect on the retry policy —
# unit tests that need deterministic sleeps also monkeypatch
# ``tenacity.nap.time.sleep``. Migrating to a per-call ``Retrying`` object
# would make the flag dynamic but also changes the decorator contract, so
# we keep the import-time capture and document it explicitly.
# ---------------------------------------------------------------------------
_NOAA_TEST_NO_JITTER = os.environ.get("NOAA_TEST_NO_JITTER") == "1"


def _wait_policy():
    base = wait_exponential(multiplier=1, min=1, max=16)
    if _NOAA_TEST_NO_JITTER:
        return base
    return base + wait_random(0, 2)


_NOAA_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@retry(
    stop=stop_after_attempt(3),
    wait=_wait_policy(),
    retry=retry_if_exception_type((httpx.HTTPError, NoaaAPIError)),
    reraise=True,
)
async def _fetch_product(
    client: httpx.AsyncClient,
    station_id: str,
    product: str,
    extra_params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Hit the CO-OPS datagetter for one product. Retries on transient errors."""
    params: dict[str, str] = {
        "station": station_id,
        "product": product,
        "units": "metric",
        "time_zone": "gmt",
        "application": "tide-mvp",
        "format": "json",
    }
    # Per-product required kwargs
    if product == "predictions":
        params["interval"] = "h"
        params["datum"] = "MLLW"
        params["date"] = "today"
        params["range"] = "48"
    else:
        params["date"] = "latest"
    if extra_params:
        params.update(extra_params)
    resp = await client.get(NOAA_BASE, params=params, timeout=_NOAA_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        # Treat NOAA's structured error payloads as a retriable API error.
        raise NoaaAPIError(f"NOAA error for {station_id}/{product}: {data['error']}")
    return data


def _parse_iso_utc(raw: str) -> datetime:
    """Parse a NOAA timestamp string to a UTC-aware datetime.

    NOAA returns strings like ``2026-04-20 15:18`` (GMT implied) or ISO-ish
    strings. We normalise to ``datetime.fromisoformat`` by swapping the space
    for a ``T``, then force UTC if tzinfo is missing.
    """
    s = raw.strip().replace(" ", "T")
    # ISO parser can't handle a trailing Z in 3.11- but 3.12 can; be defensive.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _shape_rows(
    station_id: str,
    water_level: dict[str, Any] | BaseException,
    water_temperature: dict[str, Any] | BaseException,
    wind: dict[str, Any] | BaseException | None,
    predictions: dict[str, Any] | BaseException | None,
) -> tuple[list[TidalObservationRow], list[HarmonicForecastRow]]:
    """Merge up to four product payloads into tidal + forecast rows.

    Partial-failure semantics:

    - If water_level AND water_temperature both failed, raise ``NoaaAPIError``.
    - Otherwise the observation row carries whichever fields succeeded;
      missing ones are ``None``.
    - ``wind`` and ``predictions`` are best-effort: exceptions become
      missing fields / empty forecast list.
    - ``raw_payload`` stores the raw dicts keyed by product so D-09 replay
      works (we can re-shape later without re-fetching).
    """
    wl_ok = isinstance(water_level, dict)
    wt_ok = isinstance(water_temperature, dict)
    if not (wl_ok or wt_ok):
        raise NoaaAPIError(
            f"Both water_level and water_temperature failed for {station_id}"
        )

    raw: dict[str, Any] = {}
    obs_time: datetime | None = None
    water_level_m: float | None = None
    water_temp_c: float | None = None
    wind_speed_ms: float | None = None
    wind_dir_deg: float | None = None

    if wl_ok:
        raw["water_level"] = water_level
        data_list = water_level.get("data") or []
        if data_list:
            latest = data_list[-1]
            obs_time = _parse_iso_utc(latest["t"])
            v = latest.get("v")
            water_level_m = float(v) if v not in (None, "") else None
    if wt_ok:
        raw["water_temperature"] = water_temperature
        data_list = water_temperature.get("data") or []
        if data_list:
            latest = data_list[-1]
            if obs_time is None:
                obs_time = _parse_iso_utc(latest["t"])
            v = latest.get("v")
            water_temp_c = float(v) if v not in (None, "") else None
    if isinstance(wind, dict):
        raw["wind"] = wind
        data_list = wind.get("data") or []
        if data_list:
            latest = data_list[-1]
            if obs_time is None:
                obs_time = _parse_iso_utc(latest["t"])
            s = latest.get("s")
            d = latest.get("d")
            wind_speed_ms = float(s) if s not in (None, "") else None
            wind_dir_deg = float(d) if d not in (None, "") else None

    if obs_time is None:
        raise NoaaAPIError(f"No observation timestamps found for {station_id}")

    tidal_row: TidalObservationRow = {
        "station_id": station_id,
        "time": obs_time,
        "water_level_m": water_level_m,
        "water_temp_c": water_temp_c,
        "wind_speed_ms": wind_speed_ms,
        "wind_dir_deg": wind_dir_deg,
        "current_speed_ms": None,
        "current_dir_deg": None,
        "source": "noaa_co-ops",
        "raw_payload": raw,
    }

    forecast_rows: list[HarmonicForecastRow] = []
    if isinstance(predictions, dict):
        issued_at = datetime.now(timezone.utc)
        for entry in predictions.get("predictions", []) or []:
            try:
                target = _parse_iso_utc(entry["t"])
            except (KeyError, ValueError):
                continue
            v = entry.get("v")
            try:
                predicted = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                predicted = None
            forecast_rows.append(
                {
                    "station_id": station_id,
                    "issued_at": issued_at,
                    "target_time": target,
                    "predicted_level_m": predicted,
                    "hi_lo": entry.get("type"),
                    "source": "noaa_co-ops",
                    "raw_payload": entry,
                }
            )

    return [tidal_row], forecast_rows


async def fetch_all_products_for_station(
    station: Any,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[TidalObservationRow], list[HarmonicForecastRow]]:
    """Fetch every product subscribed by ``station`` in parallel.

    ``station`` is either a ``db.models.NoaaStation`` instance or a
    duck-typed object with ``station_id`` and ``products`` attributes.
    """
    station_id: str = station.station_id
    products: list[str] = list(getattr(station, "products", []) or [])

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_NOAA_TIMEOUT)
    try:
        tasks = [
            _fetch_product(client, station_id, "water_level"),
            _fetch_product(client, station_id, "water_temperature"),
        ]
        want_wind = "wind" in products
        want_predictions = True  # every station publishes predictions
        if want_wind:
            tasks.append(_fetch_product(client, station_id, "wind"))
        if want_predictions:
            tasks.append(_fetch_product(client, station_id, "predictions"))

        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        if owns_client:
            await client.aclose()

    # Unpack in the order they were appended
    water_level = results[0]
    water_temperature = results[1]
    idx = 2
    wind: dict[str, Any] | BaseException | None = None
    predictions: dict[str, Any] | BaseException | None = None
    if want_wind:
        wind = results[idx]
        idx += 1
    if want_predictions:
        predictions = results[idx]
        idx += 1

    return _shape_rows(station_id, water_level, water_temperature, wind, predictions)


__all__ = [
    "NOAA_BASE",
    "NoaaAPIError",
    "TidalObservationRow",
    "HarmonicForecastRow",
    "fetch_all_products_for_station",
    "_shape_rows",
    "_fetch_product",
]
