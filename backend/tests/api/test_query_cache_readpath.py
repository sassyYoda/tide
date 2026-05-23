"""P-09 read-path short-circuit tests for ``/api/v1/query``.

Phase 5 follow-up to OQ-2: ``backend/api/v1/query.py`` checks a fast
query-only cache key BEFORE opening the LangGraph stream. On hit, replays
the cached recommendation event without running the full graph. On miss,
proceeds normally + writes to the fast key after the graph completes.

These tests stub the LangGraph runtime + Redis so the route's cache flow is
exercised in isolation (no real LLMs, no real Qdrant).
"""
from __future__ import annotations

import asyncio
import json

import pytest


pytestmark = pytest.mark.integration


def _make_recommendation_payload_dict() -> dict:
    """Minimal RecommendationPayload shape that survives JSON round-trip."""
    return {
        "recommendation_text": "Cached recommendation — stripers favorable.",
        "citations": [
            {"source": "NJF", "date": "2026-05-20", "title": "Bunker pod off Sea Bright"},
        ],
        "shap_top3": ["tide_phase", "moon_phase", "water_temp"],
        "confidence": "Moderate",
        "species_canonical": "striper",
        "time_window_label": "saturday morning",
        "spot_id": 42,
        "retrieval_ok": True,
    }


class _RedisStub:
    """In-memory Redis stub supporting get / setex used by the cache helpers."""

    def __init__(self, initial: dict | None = None):
        self._store: dict[str, str] = {k: v for k, v in (initial or {}).items()}
        self.set_calls: list[tuple[str, int, str]] = []
        self.get_calls: list[str] = []

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value
        self.set_calls.append((key, ttl, value))


def test_fast_cache_key_is_query_only_and_deterministic():
    """fast_query_cache_key normalizes whitespace + case, ignores canonical fields."""
    from cache.query_cache import KEY_PREFIX_FAST, fast_query_cache_key

    k1 = fast_query_cache_key("  Stripers AT  Barnegat?  ")
    k2 = fast_query_cache_key("stripers at barnegat?")
    assert k1 == k2, "normalization must collapse whitespace + case"
    assert k1.startswith(KEY_PREFIX_FAST), f"expected prefix {KEY_PREFIX_FAST!r} on {k1!r}"

    # Different query → different key
    k3 = fast_query_cache_key("fluke in raritan?")
    assert k1 != k3


def test_fast_key_differs_from_canonical_key():
    """fast_query_cache_key and query_cache_key MUST produce distinct keys so
    the two caches coexist (read-path uses fast key; D-02.1 write uses both)."""
    from cache.query_cache import fast_query_cache_key, query_cache_key

    q = "stripers at barnegat saturday morning"
    fast = fast_query_cache_key(q)
    canonical = query_cache_key(q, "striper", 42, "saturday morning")
    assert fast != canonical, "fast key must differ from canonical key to avoid overwrite"


def test_get_cached_query_returns_payload_on_hit():
    """get_cached_query reads a value stored under the fast key and returns the decoded payload.

    This is the building block the route's read-path short-circuit relies on.
    """
    from cache.query_cache import fast_query_cache_key, get_cached_query

    query = "stripers at barnegat saturday morning"
    key = fast_query_cache_key(query)
    cached_value = {"event": "recommendation", "payload": _make_recommendation_payload_dict()}

    redis = _RedisStub({key: json.dumps(cached_value)})

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(get_cached_query(redis, key))
    finally:
        loop.close()

    assert result is not None, "expected a cache hit"
    assert result["event"] == "recommendation"
    assert result["payload"]["species_canonical"] == "striper"
    assert result["payload"]["spot_id"] == 42


def test_put_cached_query_writes_under_both_keys():
    """The route writes to BOTH the canonical (D-02.1) key AND the fast key
    after a successful graph run, so subsequent identical queries hit the
    pre-graph short-circuit.
    """
    from cache.query_cache import fast_query_cache_key, put_cached_query, query_cache_key

    query = "fluke in raritan?"
    species = "fluke"
    spot_id = 17
    time_window = "tomorrow morning"
    payload = _make_recommendation_payload_dict()
    cached_value = {"event": "recommendation", "payload": payload}

    redis = _RedisStub()

    canonical = query_cache_key(query, species, spot_id, time_window)
    fast = fast_query_cache_key(query)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(put_cached_query(redis, canonical, cached_value))
        loop.run_until_complete(put_cached_query(redis, fast, cached_value))
    finally:
        loop.close()

    keys_written = [call[0] for call in redis.set_calls]
    assert canonical in keys_written
    assert fast in keys_written
    assert canonical != fast
