"""Hourly solunar computation task — pure ephem, writes to ``solunar_values``.

The Celery task is named ``compute_solunar_task`` to disambiguate it from the
pure-function helper :func:`ingest.solunar.compute_solunar` (same name collision
caused a minor beat-schedule rename; see ``celery_app/__init__.py``).
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from celery_app import celery_app
from db.models import NoaaStation, SolunarValue
from db.session import async_session_factory
from ingest.metrics import (
    ingest_duration_seconds,
    ingest_failure_total,
    ingest_success_total,
)
from ingest.solunar import compute_solunar

logger = logging.getLogger(__name__)

# Number of future hourly rows to seed per station per run (7 days).
SOLUNAR_FORECAST_HOURS = 168


@celery_app.task(name="celery_app.tasks.solunar.compute_solunar_task", bind=True)
def compute_solunar_task(self) -> dict:
    """Beat-scheduled solunar compute (hourly top-of-hour)."""
    return asyncio.run(_run_all())


async def _run_all() -> dict:
    results: dict[str, int] = {"success": 0, "failure": 0}
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        stations = (await session.execute(select(NoaaStation))).scalars().all()
    for station in stations:
        await _run_one(station, now, results)
    return results


def _next_top_of_hour(when: datetime) -> datetime:
    """Round ``when`` UP to the next top-of-hour boundary (UTC-aware)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    floor = when.replace(minute=0, second=0, microsecond=0)
    if when == floor:
        return floor
    return floor + timedelta(hours=1)


async def _run_one(
    station: NoaaStation, when: datetime, results: dict[str, int]
) -> None:
    """Seed 168 future hourly solunar rows for a single station.

    One session is opened per station and committed once at the end so we
    don't thrash connections. Per-row failures are logged + skipped so a
    single bad hour can't abort the rest of the station's horizon.
    """
    start = _time.perf_counter()
    try:
        base = _next_top_of_hour(when)
        async with async_session_factory() as session:
            for hour_offset in range(SOLUNAR_FORECAST_HOURS):
                target_time = base + timedelta(hours=hour_offset)
                try:
                    row = compute_solunar(station.lat, station.lon, target_time)
                    row["station_id"] = station.station_id
                    # compute_solunar returns its own "time" key, but force it
                    # to the requested target_time so the PK lands on the
                    # exact hour boundary we asked for.
                    row["time"] = target_time
                    await session.merge(SolunarValue(**row))
                except Exception as row_exc:  # noqa: BLE001
                    logger.warning(
                        "solunar row failed station=%s target=%s err=%s",
                        station.station_id,
                        target_time.isoformat(),
                        row_exc,
                    )
                    continue
            await session.commit()
        results["success"] += 1
        ingest_success_total.labels(
            source="solunar", station_id=station.station_id
        ).inc()
    except Exception as exc:  # noqa: BLE001
        results["failure"] += 1
        ingest_failure_total.labels(
            source="solunar",
            station_id=station.station_id,
            reason=type(exc).__name__,
        ).inc()
    finally:
        ingest_duration_seconds.labels(source="solunar").observe(
            _time.perf_counter() - start
        )


__all__ = ["compute_solunar_task"]
