"""Historical environmental-data backfill for ML training.

Phase 1's ingest is real-time-only (Celery beat at 15-30 min). Phase 2's
training labels span 2014-2026, so we need to populate the time-series
hypertables (tidal_observations, weather_observations, solunar_values,
noaa_harmonic_forecasts) over an arbitrary historical window.

Sources:
  - NOAA CO-OPS                 hourly_height + water_temperature + wind
                                (datagetter, begin_date/end_date params)
  - NOAA CO-OPS predictions     interval=h  (harmonic predictions)
  - Open-Meteo Historical       https://archive-api.open-meteo.com/v1/archive
  - Solunar                     pure ephem via ingest.solunar.compute_solunar

Idempotent: every INSERT uses ON CONFLICT DO NOTHING — re-running the same
window adds zero rows.

Cadence: hourly for tide + weather + solunar to keep payload sizes manageable
across multi-month windows. Phase 1's real-time ingest still runs at 6-min
granularity for current observations; the ML feature builder reads either.

Usage:
    cd backend && uv run python -m scripts.backfill_history \\
        --start 2025-10-01 --end 2026-04-25 \\
        [--stations 8531680,8534720] [--db postgresql://tide:tide@localhost:5432/tide]

Defaults to last 180 days against postgresql://tide:tide@localhost:5432/tide.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import httpx
import psycopg2
import psycopg2.extras
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from ingest.solunar import compute_solunar  # noqa: E402

NOAA_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
OPEN_METEO_HISTORICAL = "https://archive-api.open-meteo.com/v1/archive"

# NOAA enforces ~31-day max windows for 6-min data; for hourly_height the docs
# state 1-year windows are accepted, but we chunk at 90 days to stay polite.
_NOAA_CHUNK = timedelta(days=90)

# NOAA predictions: doc cap is 30 days per request.
_NOAA_PRED_CHUNK = timedelta(days=30)

_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_INTER_REQUEST_DELAY = 0.5  # polite per-station spacing in seconds

log = logging.getLogger("backfill")


def _default_db_url() -> str:
    url = os.environ.get("DATABASE_SYNC_URL")
    if url:
        return _normalize_psycopg_url(url)
    env_path = REPO_ROOT / "backend" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("DATABASE_SYNC_URL="):
                return _normalize_psycopg_url(line.split("=", 1)[1].strip().strip('"').strip("'"))
    return "postgresql://tide:tide@localhost:5432/tide"


def _normalize_psycopg_url(url: str) -> str:
    """Strip SQLAlchemy driver suffix that psycopg2 doesn't understand."""
    return url.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )


# ---------------------------------------------------------------------------
# NOAA CO-OPS — historical observations + predictions
# ---------------------------------------------------------------------------


class NoaaNoDataError(RuntimeError):
    """Raised on permanent 'No data was found' responses — distinct from transient
    HTTP errors so the caller can fall back to a different product without burning
    tenacity retries."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def _noaa_get(client: httpx.AsyncClient, params: dict[str, str]) -> dict:
    resp = await client.get(NOAA_BASE, params=params, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    err = data.get("error") if isinstance(data, dict) else None
    if err and "no data was found" in str(err.get("message", "")).lower():
        raise NoaaNoDataError(err.get("message", "No data was found"))
    return data


def _noaa_chunks(start: date, end: date, step: timedelta) -> list[tuple[date, date]]:
    chunks = []
    cur = start
    while cur <= end:
        nxt = min(cur + step - timedelta(days=1), end)
        chunks.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return chunks


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


async def fetch_noaa_observations(
    client: httpx.AsyncClient,
    station_id: str,
    products_available: list[str],
    start: date,
    end: date,
) -> tuple[dict[datetime, dict], list[dict]]:
    """Returns (obs_by_time, prediction_rows).

    obs_by_time merges hourly_height + water_temperature + wind by their
    timestamp. Each value dict is shaped for tidal_observations.
    """
    obs: dict[datetime, dict] = {}
    pred_rows: list[dict] = []
    chunks = _noaa_chunks(start, end, _NOAA_CHUNK)
    for c_start, c_end in chunks:
        # Water level: prefer hourly_height (verified-archival, stable for data
        # >~3 weeks old). For recent windows hourly_height returns "No data";
        # fall back to water_level (6-min provisional) and sample on the hour.
        try:
            data = await _noaa_get(
                client,
                {
                    "station": station_id,
                    "product": "hourly_height",
                    "begin_date": _ymd(c_start),
                    "end_date": _ymd(c_end),
                    "datum": "MLLW",
                    "units": "metric",
                    "time_zone": "gmt",
                    "format": "json",
                    "application": "tide-mvp-backfill",
                },
            )
            entries = data.get("data", []) or []
        except NoaaNoDataError:
            entries = []
        except Exception as e:
            log.warning("hourly_height %s %s..%s failed: %s", station_id, c_start, c_end, e)
            entries = []

        if not entries:
            try:
                data = await _noaa_get(
                    client,
                    {
                        "station": station_id,
                        "product": "water_level",
                        "begin_date": _ymd(c_start),
                        "end_date": _ymd(c_end),
                        "datum": "MLLW",
                        "units": "metric",
                        "time_zone": "gmt",
                        "format": "json",
                        "application": "tide-mvp-backfill",
                    },
                )
                # Downsample 6-min observations to :00 timestamps only
                entries = [e for e in (data.get("data", []) or [])
                           if (e.get("t") or "").endswith(":00")]
            except Exception as e:
                log.warning("water_level fallback %s %s..%s failed: %s",
                            station_id, c_start, c_end, e)
                entries = []

        for entry in entries:
            t = _parse_noaa_time(entry.get("t"))
            v = _coerce_float(entry.get("v"))
            if t is None:
                continue
            obs.setdefault(t, _empty_obs_row(station_id, t))["water_level_m"] = v

        # water_temperature (hourly aggregation: NOAA returns 6-min; we sample on the hour)
        try:
            data = await _noaa_get(
                client,
                {
                    "station": station_id,
                    "product": "water_temperature",
                    "begin_date": _ymd(c_start),
                    "end_date": _ymd(c_end),
                    "interval": "h",
                    "units": "metric",
                    "time_zone": "gmt",
                    "format": "json",
                    "application": "tide-mvp-backfill",
                },
            )
            for entry in data.get("data", []) or []:
                t = _parse_noaa_time(entry.get("t"))
                v = _coerce_float(entry.get("v"))
                if t is None:
                    continue
                obs.setdefault(t, _empty_obs_row(station_id, t))["water_temp_c"] = v
        except Exception as e:
            log.warning("water_temperature %s %s..%s failed: %s", station_id, c_start, c_end, e)

        # wind (only if station publishes it)
        if "wind" in products_available:
            try:
                data = await _noaa_get(
                    client,
                    {
                        "station": station_id,
                        "product": "wind",
                        "begin_date": _ymd(c_start),
                        "end_date": _ymd(c_end),
                        "interval": "h",
                        "units": "metric",
                        "time_zone": "gmt",
                        "format": "json",
                        "application": "tide-mvp-backfill",
                    },
                )
                for entry in data.get("data", []) or []:
                    t = _parse_noaa_time(entry.get("t"))
                    if t is None:
                        continue
                    speed = _coerce_float(entry.get("s"))
                    direction = _coerce_float(entry.get("d"))
                    row = obs.setdefault(t, _empty_obs_row(station_id, t))
                    row["wind_speed_ms"] = speed
                    row["wind_dir_deg"] = direction
            except Exception as e:
                log.warning("wind %s %s..%s failed: %s", station_id, c_start, c_end, e)

        await asyncio.sleep(_INTER_REQUEST_DELAY)

    # Predictions chunked separately (NOAA caps at 30 days for predictions)
    pred_issued = datetime.now(timezone.utc)
    for c_start, c_end in _noaa_chunks(start, end, _NOAA_PRED_CHUNK):
        try:
            data = await _noaa_get(
                client,
                {
                    "station": station_id,
                    "product": "predictions",
                    "begin_date": _ymd(c_start),
                    "end_date": _ymd(c_end),
                    "interval": "h",
                    "datum": "MLLW",
                    "units": "metric",
                    "time_zone": "gmt",
                    "format": "json",
                    "application": "tide-mvp-backfill",
                },
            )
            for entry in data.get("predictions", []) or []:
                t = _parse_noaa_time(entry.get("t"))
                v = _coerce_float(entry.get("v"))
                if t is None:
                    continue
                pred_rows.append(
                    {
                        "station_id": station_id,
                        "issued_at": pred_issued,
                        "target_time": t,
                        "predicted_level_m": v,
                        "hi_lo": entry.get("type"),
                        "raw_payload": entry,
                    }
                )
        except Exception as e:
            log.warning("predictions %s %s..%s failed: %s", station_id, c_start, c_end, e)
        await asyncio.sleep(_INTER_REQUEST_DELAY)

    return obs, pred_rows


def _empty_obs_row(station_id: str, t: datetime) -> dict:
    return {
        "station_id": station_id,
        "time": t,
        "water_level_m": None,
        "water_temp_c": None,
        "wind_speed_ms": None,
        "wind_dir_deg": None,
        "current_speed_ms": None,
        "current_dir_deg": None,
        "source": "noaa_co-ops_backfill",
        "raw_payload": {},
    }


def _parse_noaa_time(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Open-Meteo Historical — full window in one call per station
# ---------------------------------------------------------------------------


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def fetch_meteo_historical(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    start: date,
    end: date,
) -> dict:
    params = {
        "latitude": str(lat),
        "longitude": str(lon),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": (
            "wind_speed_10m,wind_direction_10m,surface_pressure,"
            "temperature_2m,precipitation_probability,cloud_cover"
        ),
        "timezone": "UTC",
        "windspeed_unit": "ms",
    }
    resp = await client.get(OPEN_METEO_HISTORICAL, params=params, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def shape_meteo_rows(station_id: str, raw: dict) -> list[dict]:
    """Pivot Open-Meteo hourly arrays into per-row dicts for weather_observations."""
    hourly = raw.get("hourly") or {}
    times = hourly.get("time") or []
    rows: list[dict] = []
    for i, t_str in enumerate(times):
        t = _parse_noaa_time(t_str)
        if t is None:
            continue
        rows.append(
            {
                "station_id": station_id,
                "time": t,
                "wind_speed_ms": _coerce_float(_safe_idx(hourly.get("wind_speed_10m"), i)),
                "wind_dir_deg": _coerce_float(_safe_idx(hourly.get("wind_direction_10m"), i)),
                "surface_pressure_hpa": _coerce_float(_safe_idx(hourly.get("surface_pressure"), i)),
                "temperature_2m_c": _coerce_float(_safe_idx(hourly.get("temperature_2m"), i)),
                "precipitation_prob_pct": _coerce_float(
                    _safe_idx(hourly.get("precipitation_probability"), i)
                ),
                "cloud_cover_pct": _coerce_float(_safe_idx(hourly.get("cloud_cover"), i)),
                "source": "open_meteo_historical",
                "raw_payload": {"_idx": i, "_time": t_str},
            }
        )
    return rows


def _safe_idx(arr, i):
    if arr is None:
        return None
    try:
        return arr[i]
    except (IndexError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Solunar — pure ephem, hourly cadence
# ---------------------------------------------------------------------------


def compute_solunar_hours(station_id: str, lat: float, lon: float, start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    cur = datetime(start.year, start.month, start.day, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, 23, 0, tzinfo=timezone.utc)
    while cur <= end_dt:
        try:
            payload = compute_solunar(lat, lon, cur)
        except Exception as e:
            log.warning("compute_solunar %s @ %s failed: %s", station_id, cur, e)
            cur += timedelta(hours=1)
            continue
        rows.append({"station_id": station_id, **payload})
        cur += timedelta(hours=1)
    return rows


# ---------------------------------------------------------------------------
# DB writes — psycopg2 + UPSERT-with-DO-NOTHING
# ---------------------------------------------------------------------------


def upsert_tidal_observations(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = [
        (
            r["station_id"], r["time"], r.get("water_level_m"), r.get("water_temp_c"),
            r.get("wind_speed_ms"), r.get("wind_dir_deg"),
            r.get("current_speed_ms"), r.get("current_dir_deg"),
            r.get("source", "noaa_co-ops_backfill"),
            psycopg2.extras.Json(r.get("raw_payload") or {}),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO tidal_observations (
              station_id, time, water_level_m, water_temp_c,
              wind_speed_ms, wind_dir_deg, current_speed_ms, current_dir_deg,
              source, raw_payload
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (station_id, time) DO NOTHING
            """,
            payload,
            page_size=500,
        )
    conn.commit()
    return len(rows)


def upsert_weather_observations(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = [
        (
            r["station_id"], r["time"],
            r.get("wind_speed_ms"), r.get("wind_dir_deg"),
            r.get("surface_pressure_hpa"), r.get("temperature_2m_c"),
            r.get("precipitation_prob_pct"), r.get("cloud_cover_pct"),
            r.get("source", "open_meteo_historical"),
            psycopg2.extras.Json(r.get("raw_payload") or {}),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO weather_observations (
              station_id, time, wind_speed_ms, wind_dir_deg,
              surface_pressure_hpa, temperature_2m_c,
              precipitation_prob_pct, cloud_cover_pct,
              source, raw_payload
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (station_id, time) DO NOTHING
            """,
            payload,
            page_size=500,
        )
    conn.commit()
    return len(rows)


def upsert_solunar_values(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = [
        (
            r["station_id"], r["time"],
            r["moon_phase"], r["moon_phase_sin"], r["moon_phase_cos"],
            r["illumination"], r["lunar_day"],
            r.get("sunrise"), r.get("sunset"),
            r.get("next_major_start"), r.get("next_major_end"),
            r.get("next_minor_start"), r.get("next_minor_end"),
            r["quality_score"], "ephem_backfill",
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO solunar_values (
              station_id, time, moon_phase, moon_phase_sin, moon_phase_cos,
              illumination, lunar_day, sunrise, sunset,
              next_major_start, next_major_end, next_minor_start, next_minor_end,
              quality_score, source
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (station_id, time) DO NOTHING
            """,
            payload,
            page_size=500,
        )
    conn.commit()
    return len(rows)


def upsert_harmonic_forecasts(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    payload = [
        (
            r["station_id"], r["issued_at"], r["target_time"],
            r.get("predicted_level_m"), r.get("hi_lo"),
            "noaa-predictions-backfill",
            psycopg2.extras.Json(r.get("raw_payload") or {}),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO noaa_harmonic_forecasts (
              station_id, issued_at, target_time,
              predicted_level_m, hi_lo, source, raw_payload
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (station_id, issued_at, target_time) DO NOTHING
            """,
            payload,
            page_size=500,
        )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def backfill_station(
    client: httpx.AsyncClient,
    conn,
    station_id: str,
    name: str,
    lat: float,
    lon: float,
    products_available: list[str],
    start: date,
    end: date,
) -> dict[str, int]:
    """Fetch + write all four data sources for one station over [start, end]."""
    log.info("station=%s (%s) %s..%s — fetching", station_id, name, start, end)

    # Tide + harmonic forecasts (NOAA CO-OPS)
    obs_by_time, pred_rows = await fetch_noaa_observations(
        client, station_id, products_available, start, end
    )
    tidal_rows = list(obs_by_time.values())
    n_tide = upsert_tidal_observations(conn, tidal_rows)
    n_pred = upsert_harmonic_forecasts(conn, pred_rows)

    # Weather (Open-Meteo Historical)
    try:
        meteo_raw = await fetch_meteo_historical(client, lat, lon, start, end)
        meteo_rows = shape_meteo_rows(station_id, meteo_raw)
    except Exception as e:
        log.warning("Open-Meteo historical %s failed: %s", station_id, e)
        meteo_rows = []
    n_weather = upsert_weather_observations(conn, meteo_rows)

    # Solunar (pure compute)
    sol_rows = compute_solunar_hours(station_id, lat, lon, start, end)
    n_solunar = upsert_solunar_values(conn, sol_rows)

    counts = {"tide": n_tide, "weather": n_weather, "solunar": n_solunar, "predictions": n_pred}
    log.info("station=%s wrote %s", station_id, counts)
    return counts


async def main_async(args: argparse.Namespace) -> int:
    db_url = args.db or _default_db_url()
    log.info("connecting to %s", db_url.split("@")[-1])
    conn = psycopg2.connect(db_url)

    # Load station list
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT station_id, name, lat, lon, products FROM noaa_stations ORDER BY station_id"
        )
        stations = list(cur.fetchall())
    if args.stations:
        wanted = set(s.strip() for s in args.stations.split(","))
        stations = [s for s in stations if s["station_id"] in wanted]
    log.info("backfill window %s..%s across %d stations", args.start, args.end, len(stations))

    totals = {"tide": 0, "weather": 0, "solunar": 0, "predictions": 0}
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        headers={"User-Agent": "Tide/0.1 (research-mvp; +https://github.com/X-commando/tide)"},
    ) as client:
        for s in stations:
            counts = await backfill_station(
                client,
                conn,
                s["station_id"], s["name"], float(s["lat"]), float(s["lon"]),
                list(s["products"] or []),
                args.start, args.end,
            )
            for k, v in counts.items():
                totals[k] += v

    conn.close()
    log.info("backfill complete totals=%s", totals)
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    today = date.today()
    p.add_argument(
        "--start",
        type=lambda s: date.fromisoformat(s),
        default=today - timedelta(days=180),
        help="UTC start date (YYYY-MM-DD). Default: today - 180 days.",
    )
    p.add_argument(
        "--end",
        type=lambda s: date.fromisoformat(s),
        default=today,
        help="UTC end date (YYYY-MM-DD), inclusive. Default: today.",
    )
    p.add_argument(
        "--stations",
        type=str,
        default=None,
        help="Comma-separated station_id whitelist. Default: all in noaa_stations.",
    )
    p.add_argument(
        "--db",
        type=str,
        default=None,
        help="Postgres URL. Default: $DATABASE_SYNC_URL or backend/.env or localhost.",
    )
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Python log level. Default: INFO.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.start > args.end:
        log.error("--start (%s) is after --end (%s)", args.start, args.end)
        return 2
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
