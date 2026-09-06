"""Redis query-result cache for RAG retrieval (R-10).

Shares the Phase 1 Memorystore instance. Key namespace ``cache:rag:*`` is
distinct from ``lkg:*`` (Phase 1 LKG), ``cache:conditions:*`` (Phase 1),
``breaker:*`` (Phase 1 circuit breaker), and future ``cache:query:*`` (Phase 3).

Pattern shape mirrors ``backend/ingest/lkg.py`` deliberately — both layers are
"orjson-encoded payload + TTL" stores over the same Redis instance, but the
LKG semantics (most-recent-good fallback) differ from the RAG cache semantics
(15-min bucketed dedupe of identical queries). Keeping the surface symmetric
keeps the operator mental model simple.

R-10 contract:

- TTL = 15 minutes (matches the scorer beat cadence — repeat queries within a
  single scorer tick share a cache entry, never longer).
- Key is bucket-aligned to 15-min windows so any two queries arriving in the
  same wall-clock bucket map to the same key (deterministic dedupe — not
  time-dependent rolling cache).
- ``cache_key`` lower-cases the query text before hashing so case variations
  ("Bunker chunks" vs "bunker chunks") collapse to one key.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import orjson
from redis.asyncio import Redis

TTL_SECONDS = 15 * 60  # R-10 — 15 minutes


def cache_key(
    species: str,
    location_region: str | None,
    query_text: str,
    now: datetime | None = None,
) -> str:
    """Deterministic 15-min-bucketed SHA256 cache key.

    Two queries land on the same key iff:
      - same species, same location_region (None counts as its own bucket),
      - same lower-cased+stripped query_text,
      - their ``now`` timestamps fall in the same 15-minute UTC bucket.

    Returns ``cache:rag:<16-char-hex>`` so Redis SCAN by namespace works.
    """
    now = now or datetime.now(timezone.utc)
    bucket = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    raw = f"{species}|{location_region or ''}|{bucket.isoformat()}|{query_text.strip().lower()}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"cache:rag:{h}"


async def get_cached(redis: Redis, key: str) -> list[dict] | None:
    """Read+decode a cached retrieval result. Returns None on cache miss."""
    raw = await redis.get(key)
    return None if raw is None else orjson.loads(raw)


async def put_cached(redis: Redis, key: str, value: list[dict]) -> None:
    """Encode+store a retrieval result with the R-10 TTL.

    ``value`` is whatever ``hybrid_retrieve`` returns — a list of dicts with
    id / score_adjusted / score_raw / payload keys. orjson handles datetimes
    via ``OPT_NAIVE_UTC`` (any datetime fields are coerced to UTC ISO strings).
    """
    body = orjson.dumps(value, option=orjson.OPT_NAIVE_UTC)
    await redis.set(key, body, ex=TTL_SECONDS)


__all__ = ["TTL_SECONDS", "cache_key", "get_cached", "put_cached"]
