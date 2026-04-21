"""Redis Last-Known-Good (LKG) cache + per-station circuit breaker.

LKG semantics (INFRA-06): the most recent successful ingest payload is
cached under ``lkg:<source>:<station_id>:<product>`` with an explicit TTL
(default 35 minutes — longer than the 30-min poll cadence so a single
missed poll does not invalidate the LKG). Downstream readers (the Plan 06
``/conditions`` endpoint) fall back to LKG when a DB row is stale.

Circuit breaker semantics (REL-02): after ``BREAKER_THRESHOLD`` consecutive
failures for a given ``station_id``, the breaker is considered "open" and
the Prometheus counter ``noaa_breaker_tripped_total`` is incremented
*exactly once* per open event. Counter fires on ``count == THRESHOLD`` only
— not ``>=`` — so a station that keeps failing after the trip doesn't
double-count.
"""

from __future__ import annotations

from typing import Any

import orjson
from redis.asyncio import Redis

from ingest.metrics import noaa_breaker_tripped_total


BREAKER_THRESHOLD = 3  # 3 consecutive failures = open circuit
BREAKER_TTL = 60 * 60   # breaker counter key expires after 1 hour of quiet
DEFAULT_LKG_TTL = 35 * 60  # 35 minutes


def _breaker_key(station_id: str) -> str:
    return f"breaker:noaa:{station_id}"


async def write_lkg(
    redis: Redis,
    key: str,
    payload: Any,
    ttl: int = DEFAULT_LKG_TTL,
) -> None:
    """Store ``payload`` under ``key`` with a TTL. Payload is orjson-encoded."""
    body = orjson.dumps(payload, option=orjson.OPT_NAIVE_UTC)
    await redis.set(key, body, ex=ttl)


async def read_lkg(redis: Redis, key: str) -> Any | None:
    """Return the decoded LKG payload for ``key``, or None if missing."""
    raw = await redis.get(key)
    if raw is None:
        return None
    return orjson.loads(raw)


async def increment_breaker(redis: Redis, station_id: str) -> int:
    """Increment the per-station failure counter and return the new value.

    Emits ``noaa_breaker_tripped_total`` exactly once when the counter
    equals :data:`BREAKER_THRESHOLD`. Fourth / fifth / Nth failures after
    that do NOT re-emit.
    """
    key = _breaker_key(station_id)
    count = await redis.incr(key)
    # Only set expiry on the first increment so the TTL tracks the open-event
    # window (not the most recent failure). INCR alone does not set a TTL.
    if count == 1:
        await redis.expire(key, BREAKER_TTL)
    if int(count) == BREAKER_THRESHOLD:
        noaa_breaker_tripped_total.labels(station_id=station_id).inc()
    return int(count)


async def reset_breaker(redis: Redis, station_id: str) -> None:
    """Clear the per-station failure counter (call on any successful poll)."""
    await redis.delete(_breaker_key(station_id))


__all__ = [
    "BREAKER_THRESHOLD",
    "BREAKER_TTL",
    "DEFAULT_LKG_TTL",
    "write_lkg",
    "read_lkg",
    "increment_breaker",
    "reset_breaker",
]
