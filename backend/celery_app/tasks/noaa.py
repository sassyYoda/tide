"""NOAA poll task — per-station jitter + tenacity retry + LKG breaker wiring."""

from __future__ import annotations

import asyncio
import random
import time as _time
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select

from app.config import settings
from celery_app import celery_app
from db.models import NoaaHarmonicForecast, NoaaStation, TidalObservation
from db.session import async_session_factory
from ingest.lkg import increment_breaker, reset_breaker, write_lkg
from ingest.metrics import (
    data_age_seconds,
    ingest_duration_seconds,
    ingest_failure_total,
    ingest_success_total,
)
from ingest.noaa_client import NoaaAPIError, fetch_all_products_for_station  # noqa: F401


@celery_app.task(name="celery_app.tasks.noaa.poll_noaa_stations", bind=True)
def poll_noaa_stations(self) -> dict:
    """Beat-scheduled NOAA poll. Delegates to :func:`_poll_all` under asyncio."""
    return asyncio.run(_poll_all())


async def _poll_all() -> dict:
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    results: dict[str, int] = {"success": 0, "failure": 0}
    async with async_session_factory() as session:
        stations = (await session.execute(select(NoaaStation))).scalars().all()
    try:
        await asyncio.gather(*[_poll_one(s, redis, results) for s in stations])
    finally:
        await redis.aclose()
    return results


async def _poll_one(station: NoaaStation, redis: Redis, results: dict[str, int]) -> None:
    """Poll one station; spread load with per-station jitter (pitfall #6)."""
    await asyncio.sleep(random.uniform(0, 60))  # per-station jitter
    start = _time.perf_counter()
    try:
        tidal_rows, forecast_rows = await fetch_all_products_for_station(station)
        async with async_session_factory() as session:
            for row in tidal_rows:
                await session.merge(TidalObservation(**row))
            for row in forecast_rows:
                await session.merge(NoaaHarmonicForecast(**row))
            await session.commit()
        # LKG on success — per-product key with 35-min TTL.
        for row in tidal_rows:
            await write_lkg(
                redis,
                f"lkg:noaa:{station.station_id}:water_level",
                {
                    "time": row["time"].isoformat(),
                    "value": row.get("water_level_m"),
                    "raw": row["raw_payload"],
                },
                ttl=35 * 60,
            )
        await reset_breaker(redis, station.station_id)
        results["success"] += 1
        ingest_success_total.labels(source="noaa", station_id=station.station_id).inc()
        if tidal_rows:
            age = (datetime.now(timezone.utc) - tidal_rows[0]["time"]).total_seconds()
            data_age_seconds.labels(
                station_id=station.station_id, source="noaa"
            ).set(age)
    except Exception as exc:  # noqa: BLE001 — metric-labelling branch
        results["failure"] += 1
        ingest_failure_total.labels(
            source="noaa",
            station_id=station.station_id,
            reason=type(exc).__name__,
        ).inc()
        await increment_breaker(redis, station.station_id)
    finally:
        ingest_duration_seconds.labels(source="noaa").observe(
            _time.perf_counter() - start
        )


__all__ = ["poll_noaa_stations"]
