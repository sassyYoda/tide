"""Freshness gate — FastAPI dependency that hard-refuses stale conditions.

Protocol (RESEARCH.md §5):

1. Look up ``cache:freshness:{station_id}`` in Redis. On hit, parse the ISO
   timestamp and skip the DB query (micro-cache, ``MICRO_CACHE_TTL_SECONDS``).
2. On miss, run ``SELECT MAX(bucket) FROM conditions_15min WHERE station_id
   = :station_id``, cache the result, and evaluate.
3. If no bucket exists → HTTP 503 ``conditions_unavailable``; increment
   ``freshness_gate_503_total{reason="no_data"}``.
4. If ``now - latest_bucket > FRESHNESS_THRESHOLD`` → HTTP 503
   ``conditions_stale``; include ``latest_bucket`` in the error detail;
   increment ``freshness_gate_503_total{reason="stale"}``.
5. On pass → set ``data_age_seconds{station_id, source="cagg"}.set(age)`` and
   return the tz-aware UTC ``latest_bucket``.

Mitigates Pitfall #5 (silent CAGG staleness) by gating every protected route
on a materialized freshness check instead of trusting the CAGG's presence.

Mitigates API-05 DoS-against-DB by micro-caching the freshness read; under
load the hot path resolves entirely in Redis.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.db import get_session
from app.deps.redis import get_redis
from ingest.metrics import data_age_seconds, freshness_gate_503_total


FRESHNESS_THRESHOLD = timedelta(minutes=35)
MICRO_CACHE_TTL_SECONDS = 10


def _cache_key(station_id: str) -> str:
    return f"cache:freshness:{station_id}"


def _ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as tz-aware UTC (treating naive as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def require_fresh_conditions(
    station_id: str,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> datetime:
    """FastAPI dependency — returns the latest CAGG bucket for ``station_id``.

    Raises :class:`HTTPException` 503 when the data is stale or missing.
    """
    key = _cache_key(station_id)
    cached = await redis.get(key)
    latest_bucket: datetime | None = None

    if cached is not None:
        try:
            raw = cached.decode() if isinstance(cached, (bytes, bytearray)) else cached
            latest_bucket = _ensure_utc(datetime.fromisoformat(raw))
        except (ValueError, AttributeError):
            # Corrupt cache entry — fall through to DB read.
            latest_bucket = None

    if latest_bucket is None:
        result = await session.execute(
            text(
                "SELECT MAX(bucket) AS latest_bucket FROM conditions_15min "
                "WHERE station_id = :station_id"
            ),
            {"station_id": station_id},
        )
        row = result.first()
        db_bucket = row.latest_bucket if row is not None else None
        if db_bucket is not None:
            latest_bucket = _ensure_utc(db_bucket)
            await redis.setex(
                key,
                MICRO_CACHE_TTL_SECONDS,
                latest_bucket.isoformat(),
            )

    now = datetime.now(timezone.utc)

    if latest_bucket is None:
        freshness_gate_503_total.labels(
            station_id=station_id, reason="no_data"
        ).inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "conditions_unavailable",
                "message": (
                    f"No conditions data available for station {station_id}."
                ),
            },
        )

    age = now - latest_bucket
    data_age_seconds.labels(station_id=station_id, source="cagg").set(
        age.total_seconds()
    )

    if age > FRESHNESS_THRESHOLD:
        freshness_gate_503_total.labels(
            station_id=station_id, reason="stale"
        ).inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "conditions_stale",
                "message": (
                    f"Conditions data is {int(age.total_seconds() / 60)} "
                    "minutes old. Try again shortly."
                ),
                "latest_bucket": latest_bucket.isoformat(),
            },
        )

    return latest_bucket


__all__ = [
    "FRESHNESS_THRESHOLD",
    "MICRO_CACHE_TTL_SECONDS",
    "require_fresh_conditions",
]
