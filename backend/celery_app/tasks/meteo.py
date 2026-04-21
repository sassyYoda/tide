"""Open-Meteo poll task — fetches current + hourly + computes pressure trend."""

from __future__ import annotations

import asyncio
import time as _time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from celery_app import celery_app
from db.models import NoaaStation, WeatherObservation
from db.session import async_session_factory
from ingest.meteo_client import fetch_open_meteo, shape_meteo_row
from ingest.metrics import (
    data_age_seconds,
    ingest_duration_seconds,
    ingest_failure_total,
    ingest_success_total,
)
from ingest.pressure import compute_pressure_trend


@celery_app.task(name="celery_app.tasks.meteo.poll_open_meteo", bind=True)
def poll_open_meteo(self) -> dict:
    """Beat-scheduled Open-Meteo poll (30-min cadence)."""
    return asyncio.run(_poll_all())


async def _poll_all() -> dict:
    results: dict[str, int] = {"success": 0, "failure": 0}
    async with async_session_factory() as session:
        stations = (await session.execute(select(NoaaStation))).scalars().all()
    await asyncio.gather(*[_poll_one(s, results) for s in stations])
    return results


async def _poll_one(station: NoaaStation, results: dict[str, int]) -> None:
    start = _time.perf_counter()
    try:
        raw = await fetch_open_meteo(station.lat, station.lon)
        row = shape_meteo_row(station.station_id, raw)

        # Pressure trend: last 7 hourly rows to compute 1h/3h/6h deltas.
        async with async_session_factory() as session:
            since = row["time"] - timedelta(hours=7)
            q = (
                select(WeatherObservation.time, WeatherObservation.surface_pressure_hpa)
                .where(WeatherObservation.station_id == station.station_id)
                .where(WeatherObservation.time >= since)
                .order_by(WeatherObservation.time.desc())
            )
            rows = (await session.execute(q)).all()
            history = [
                (t, float(p))
                for t, p in rows
                if p is not None
            ]
            # Include the incoming observation so trend reflects "now".
            if row.get("surface_pressure_hpa") is not None:
                history.insert(0, (row["time"], float(row["surface_pressure_hpa"])))
            trend = compute_pressure_trend(history)
            # Attach trend fields (they are extras on the model — ignored by
            # server default INSERT but may be wired into the row in Plan 06
            # if schema gains these columns). For now store in raw_payload.
            payload = dict(row["raw_payload"])
            payload["_pressure_trend"] = trend
            row["raw_payload"] = payload

            await session.merge(WeatherObservation(**row))
            await session.commit()

        results["success"] += 1
        ingest_success_total.labels(source="meteo", station_id=station.station_id).inc()
        age = (datetime.now(timezone.utc) - row["time"]).total_seconds()
        data_age_seconds.labels(
            station_id=station.station_id, source="meteo"
        ).set(age)
    except Exception as exc:  # noqa: BLE001
        results["failure"] += 1
        ingest_failure_total.labels(
            source="meteo",
            station_id=station.station_id,
            reason=type(exc).__name__,
        ).inc()
    finally:
        ingest_duration_seconds.labels(source="meteo").observe(
            _time.perf_counter() - start
        )


__all__ = ["poll_open_meteo"]
