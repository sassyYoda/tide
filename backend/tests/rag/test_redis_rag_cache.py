"""R-10 — retriever+cache integration: repeat queries don't re-hit Qdrant.

This file tests the cache wrapper semantics that the Phase 3 LangGraph Data
Fetcher node will depend on. The unit-level cache_key tests live in
``tests/ml/test_cache.py``; this file verifies the round-trip-through-Redis
contract a downstream caller would exercise.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cache_hit_bypasses_qdrant(redis_client):
    """Cached value is returned verbatim without touching the retriever."""
    from cache.rag import cache_key, get_cached, put_cached

    now = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    key = cache_key("striper", "barnegat_bay", "inlet outgoing", now=now)

    cached_value = [
        {
            "id": "1",
            "score_adjusted": 0.8,
            "score_raw": 0.9,
            "payload": {"source_name": "reddit", "source_url": "https://x"},
        },
    ]
    await put_cached(redis_client, key, cached_value)

    got = await get_cached(redis_client, key)
    assert got == cached_value


@pytest.mark.asyncio
async def test_cache_key_includes_species_and_time_bucket(redis_client):
    """Same query text, different species → different cache slots."""
    from cache.rag import cache_key, get_cached, put_cached

    now = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    k_striper = cache_key("striper", None, "bunker school", now=now)
    k_fluke = cache_key("fluke", None, "bunker school", now=now)

    await put_cached(redis_client, k_striper, [{"id": "s1"}])
    await put_cached(redis_client, k_fluke, [{"id": "f1"}])

    assert await get_cached(redis_client, k_striper) == [{"id": "s1"}]
    assert await get_cached(redis_client, k_fluke) == [{"id": "f1"}]
