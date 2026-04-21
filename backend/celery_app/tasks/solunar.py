"""Hourly solunar computation task — pure ephem, writes to ``solunar_values``.

The Celery task is named ``compute_solunar_task`` to disambiguate it from the
pure-function helper :func:`ingest.solunar.compute_solunar` (same name collision
caused a minor beat-schedule rename; see ``celery_app/__init__.py``).
"""

from __future__ import annotations

import asyncio
import time as _time
from datetime import datetime, timezone

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


async def _run_one(
    station: NoaaStation, when: datetime, results: dict[str, int]
) -> None:
    start = _time.perf_counter()
    try:
        row = compute_solunar(station.lat, station.lon, when)
        row["station_id"] = station.station_id
        async with async_session_factory() as session:
            await session.merge(SolunarValue(**row))
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
