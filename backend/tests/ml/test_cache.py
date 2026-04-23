"""Stub — R-10 Redis RAG query-result cache. Implemented in Plan 07."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 07"),
    pytest.mark.integration,
]


def test_query_cache_hit_on_repeat():
    """Plan 07: identical RAG query served from Redis on second call."""
    assert False, "Not implemented"


def test_cache_ttl_is_15_minutes():
    """Plan 07: Redis EXPIRE set to 900s per R-10."""
    assert False, "Not implemented"
