"""P-09 Prometheus cache-counter visibility tests for ``/metrics``.

Wave 1 (plan 05-02) wires ``backend/cache/metrics.py`` (query_cache_hits_total
+ query_cache_misses_total counters) and force-imports it in
``backend/app/main.py`` so the counters land on the default REGISTRY before
the first scrape.

Two checks:

1. ``test_cache_counter_visible_at_metrics`` — scrape /metrics, assert both
   counter NAMES appear in the exposition body (even at zero — prometheus_client
   emits a HELP/TYPE/zero-sample triplet on first scrape for declared counters).
2. ``test_cache_miss_counter_increments`` — call ``get_cached_query`` against
   a Redis returning None, assert the miss counter advances by ≥1.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_cache_counter_visible_at_metrics(test_client):
    """GET /metrics body contains both cache counter names + their HELP lines.

    OQ-2 was resolved in-Phase-5 by ``backend/api/v1/query.py`` wiring the
    pre-graph read-path short-circuit (calls ``get_cached_query`` against a
    fast query-only cache key). The counters now move under real traffic;
    this test only asserts registration so it stays green even on a cold
    Redis.
    """
    resp = test_client["client"].get("/metrics")
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert "query_cache_hits_total" in body, (
        "expected query_cache_hits_total in /metrics scrape"
    )
    assert "query_cache_misses_total" in body, (
        "expected query_cache_misses_total in /metrics scrape"
    )


def test_cache_miss_counter_increments(test_client):
    """Call get_cached_query against a Redis returning None → miss counter +=1."""
    import asyncio

    from cache.metrics import query_cache_misses_total
    from cache.query_cache import get_cached_query

    before = query_cache_misses_total._value.get()

    class _RedisNone:
        async def get(self, _key):
            return None

    async def _run():
        return await get_cached_query(_RedisNone(), "cache:query:does-not-exist")

    result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_run())
    assert result is None

    after = query_cache_misses_total._value.get()
    assert after == before + 1, (
        f"miss counter did not advance: before={before} after={after}"
    )
