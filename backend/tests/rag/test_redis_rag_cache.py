"""Stub — R-10 Redis query-result cache integration. Implemented in Plan 07."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 07"),
    pytest.mark.integration,
]


def test_identical_query_served_from_cache():
    """Plan 07: second identical retrieve() returns cached result without Qdrant call."""
    assert False, "Not implemented"


def test_cache_key_includes_species_and_time_bucket():
    """Plan 07: cache key = hash(query + species + time_bucket + location_filter)."""
    assert False, "Not implemented"
