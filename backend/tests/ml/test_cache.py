"""R-10 — Redis query-result cache.

Plan 07 cache contract:

- ``cache_key`` is 15-min-bucket-aligned + namespace ``cache:rag:*``.
- ``get_cached`` / ``put_cached`` round-trip arbitrary list-of-dicts via orjson.
- TTL is exactly 900s (15 min) per R-10.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration


def test_cache_key_buckets_15min_windows():
    """Same species+location+query within a 15-min wall-clock bucket → same key."""
    from cache.rag import cache_key

    base = datetime(2026, 4, 20, 12, 7, 30, tzinfo=timezone.utc)  # :07 → bucket :00
    k1 = cache_key("striper", "barnegat_bay", "inlet outgoing", now=base)
    k2 = cache_key(
        "striper",
        "barnegat_bay",
        "inlet outgoing",
        now=base + timedelta(minutes=5),  # :12 → same bucket
    )
    assert k1 == k2
    k3 = cache_key(
        "striper",
        "barnegat_bay",
        "inlet outgoing",
        now=base + timedelta(minutes=15),  # :22 → next bucket
    )
    assert k1 != k3


def test_cache_key_distinguishes_species():
    from cache.rag import cache_key

    base = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    k_striper = cache_key("striper", None, "bunker chunks", now=base)
    k_fluke = cache_key("fluke", None, "bunker chunks", now=base)
    assert k_striper != k_fluke


def test_cache_key_distinguishes_location():
    from cache.rag import cache_key

    base = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    k_bb = cache_key("striper", "barnegat_bay", "q", now=base)
    k_sh = cache_key("striper", "sandy_hook", "q", now=base)
    assert k_bb != k_sh


def test_cache_key_case_insensitive_query():
    """Casing variations shouldn't fragment the cache."""
    from cache.rag import cache_key

    base = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    k1 = cache_key("striper", None, "Bunker Chunks", now=base)
    k2 = cache_key("striper", None, "bunker chunks", now=base)
    assert k1 == k2


def test_cache_key_namespace_prefix():
    from cache.rag import cache_key

    k = cache_key("striper", None, "x")
    assert k.startswith("cache:rag:")


@pytest.mark.asyncio
async def test_put_get_roundtrip(redis_client):
    from cache.rag import cache_key, get_cached, put_cached

    key = cache_key(
        "striper", None, "test", now=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    )
    value = [
        {"id": "abc", "payload": {"source_name": "x"}},
        {"id": "def", "payload": {}},
    ]
    await put_cached(redis_client, key, value)
    loaded = await get_cached(redis_client, key)
    assert loaded == value


@pytest.mark.asyncio
async def test_get_missing_returns_none(redis_client):
    from cache.rag import get_cached

    result = await get_cached(redis_client, "cache:rag:does_not_exist")
    assert result is None


@pytest.mark.asyncio
async def test_ttl_is_15_minutes(redis_client):
    from cache.rag import TTL_SECONDS, cache_key, put_cached

    assert TTL_SECONDS == 900
    key = cache_key("striper", None, "ttl-test")
    await put_cached(redis_client, key, [{"x": 1}])
    ttl = await redis_client.ttl(key)
    # Allow a small lower bound to absorb test scheduling lag.
    assert 800 <= ttl <= 900
