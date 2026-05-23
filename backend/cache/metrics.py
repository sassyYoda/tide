"""P-09 Prometheus metrics for the query-result cache (CONTEXT D-02.1).

This module mirrors ``backend/ingest/metrics.py``: bare ``prometheus_client``
Counter declarations on the default REGISTRY. Per RESEARCH §Q5 (L-06 lock)
the project explicitly does NOT use ``prometheus-fastapi-instrumentator`` —
the instrumentator adds per-route labels by default which would blow
cardinality (Pitfall P4: NEVER label metrics with user-supplied path or query
fragments). Direct Counter declarations keep the metric shape under our
control.

The two counters here are intentionally UN-labelled. Aggregate hit-rate is
computed via PromQL ``rate(query_cache_hits_total[5m]) /
(rate(query_cache_hits_total[5m]) + rate(query_cache_misses_total[5m]))`` —
NOT precomputed and exposed as a Gauge. Precomputed ratios silently lie when
one of the rates is zero; the PromQL ``rate()`` form handles the
zero-divisor case at scrape time.

OQ-2 resolution (RESEARCH §Q5 lines 451-453): the read-path short-circuit
into ``api/v1/query.py`` is deferred to v1.x — the canonical cache-key
inputs (species_canonical, spot_id, time_window_label) are not available
until after the Planner runs. Phase 5 still instruments
``cache.query_cache.get_cached_query`` so when any upstream caller does
invoke it (RAG cache, conditions cache, future planner-only subgraph) the
hit/miss signal lands on /metrics. In normal Phase 5 traffic the counters
may stay at 0.0; that's the documented MVP state, not a bug.
"""

from __future__ import annotations

from prometheus_client import Counter


# No labelnames. Pitfall P4 — labels on these counters would invite
# query_text / user_id / IP-tagged variants that explode cardinality.
query_cache_hits_total = Counter(
    "query_cache_hits_total",
    "Count of /api/v1/query result-cache hits (post-graph read path).",
)

query_cache_misses_total = Counter(
    "query_cache_misses_total",
    "Count of /api/v1/query result-cache misses.",
)


__all__ = [
    "query_cache_hits_total",
    "query_cache_misses_total",
]
