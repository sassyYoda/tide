"""P-09 Prometheus cache-counter visibility test for ``/metrics``.

Wave 1 (plan 05-02) wires ``backend/cache/metrics.py`` (query_cache_hits_total
+ query_cache_misses_total counters) and force-imports it in
``backend/app/main.py`` so the counters land on the default REGISTRY before
the first scrape. This test verifies they're visible on ``/metrics``.

Wave 0 (this file) ships a RED SKELETON.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")
def test_cache_counter_visible_at_metrics():
    """Hit /api/v1/query once, then GET /metrics; assert counters present.

    Per OQ-2 resolution (RESEARCH §Q5): first call is always a miss until
    the read-path short-circuit lands in v1.x, so the assertion is on
    ``query_cache_misses_total`` being non-zero + ``data_age_seconds``
    being exposed.
    """
    pass
