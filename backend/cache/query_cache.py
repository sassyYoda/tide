"""Final-agent-result cache (CONTEXT D-02.1).

Key = sha256(normalized_query + species_canonical + spot_id_or_none + time_window_label)
TTL = 15 minutes (matches Celery scorer cadence; bounded by Phase 1 freshness gate)
Value = JSON-serialized RecommendationPayload dict

Honest annotation per CONTEXT D-02.1: this module is the WRITE path for the
result cache. The pre-graph short-circuit READ that D-02.1 ultimately calls
for is deferred to a planner-only subgraph (the canonical fields needed for
the key — species_canonical, spot_id, time_window_label — are not available
until the Planner has run). The key construction itself is fully D-02.1-
compliant: deterministic hashlib.sha256 over normalized inputs.

NEVER use Python's built-in ``hash()`` for cache keys — it is non-deterministic
across processes (PYTHONHASHSEED is randomized by default), which would
silently produce cache misses for clients hitting different gunicorn workers.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from redis.asyncio import Redis

from cache.metrics import query_cache_hits_total, query_cache_misses_total

log = logging.getLogger(__name__)

TTL_SECONDS = 15 * 60
KEY_PREFIX = "cache:query:"


def normalize_query(q: str) -> str:
    """Lowercase + collapse whitespace. Cheap, deterministic.

    Two queries that differ only in case or whitespace map to the same key:

        normalize_query("  Stripers   AT Barnegat?  ") == "stripers at barnegat?"
    """
    return " ".join((q or "").lower().split())


def query_cache_key(
    query: str,
    species: str | None,
    spot_id: int | None,
    time_window: str | None,
) -> str:
    """Stable hash of the canonical query identity (D-02.1).

    Uses ``hashlib.sha256``; the resulting hex digest is deterministic across
    processes / machines. The first 16 hex chars are sufficient for cache key
    collision avoidance at MVP scale.
    """
    blob = "|".join([
        normalize_query(query),
        species or "",
        str(spot_id) if spot_id is not None else "",
        (time_window or "").lower(),
    ])
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return KEY_PREFIX + digest


async def get_cached_query(redis: Redis, key: str) -> dict[str, Any] | None:
    """Read+decode a cached recommendation payload. Returns None on miss / error.

    P-09 instrumentation: increments ``query_cache_hits_total`` on the success
    branch and ``query_cache_misses_total`` on any of the three miss branches
    (read fail / raw absent / decode fail). Counters are un-labelled so they
    aggregate across the whole process (Pitfall P4).
    """
    try:
        raw = await redis.get(key)
    except Exception as e:  # noqa: BLE001 — best-effort, never fail the request
        log.warning("query_cache: read failed: %s", e)
        query_cache_misses_total.inc()
        return None
    if not raw:
        query_cache_misses_total.inc()
        return None
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("query_cache: cached value malformed at %s", key)
        query_cache_misses_total.inc()
        return None
    query_cache_hits_total.inc()
    return decoded


async def put_cached_query(redis: Redis, key: str, payload: dict[str, Any]) -> None:
    """Encode+store a recommendation payload with the D-02.1 TTL.

    Best-effort: a cache write failure must never fail the user's request
    (the SSE stream has already been delivered when this is called).
    """
    try:
        await redis.setex(key, TTL_SECONDS, json.dumps(payload))
    except Exception as e:  # noqa: BLE001
        log.warning("query_cache: write failed: %s", e)


__all__ = [
    "TTL_SECONDS",
    "KEY_PREFIX",
    "normalize_query",
    "query_cache_key",
    "get_cached_query",
    "put_cached_query",
]
