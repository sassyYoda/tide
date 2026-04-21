"""Shared Prometheus metrics for the ingest + conditions layers.

Module import is side-effect-safe under ``PROMETHEUS_MULTIPROC_DIR`` — the
``prometheus_client`` library picks up the env var lazily when the registry
is built by the FastAPI /metrics endpoint (Plan 06). This module only
declares the metric objects on the default (global) registry.

Metric inventory (keep in sync with RESEARCH.md §11):

- ``data_age_seconds`` (Gauge, multiprocess_mode="livesum"): freshest row age
  per ``{station_id, source}``. Feeds the Plan 06 freshness gate that returns
  503 when the newest row is older than 30 min.
- ``ingest_success_total`` / ``ingest_failure_total`` (Counter): per-poll
  outcome counters labelled by ``source`` and (for failures) ``reason``.
- ``ingest_duration_seconds`` (Histogram): wall-clock per poll; labelled by
  ``source``. Default buckets are fine — ingests complete in <5s normally.
- ``noaa_breaker_tripped_total`` (Counter): increments exactly once the moment
  the per-station breaker flips open at ``BREAKER_THRESHOLD`` consecutive
  failures (REL-02).
- ``freshness_gate_503_total`` (Counter): incremented by the /conditions
  endpoint when the gate returns 503 (wired in Plan 06; declared here so the
  module owns all metric names in one place).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


# Freshness gauge — multiprocess_mode="livesum" so each worker's set() is summed
# in the parent (matches the Prometheus multiproc model for per-child gauges).
data_age_seconds = Gauge(
    "data_age_seconds",
    "Age in seconds of the freshest observation row for a given station/source.",
    labelnames=("station_id", "source"),
    multiprocess_mode="livesum",
)

ingest_success_total = Counter(
    "ingest_success_total",
    "Count of successful ingest polls, labelled by source and station.",
    labelnames=("source", "station_id"),
)

ingest_failure_total = Counter(
    "ingest_failure_total",
    "Count of failed ingest polls, labelled by source, station, and exception type.",
    labelnames=("source", "station_id", "reason"),
)

ingest_duration_seconds = Histogram(
    "ingest_duration_seconds",
    "Wall-clock duration of one ingest poll.",
    labelnames=("source",),
)

noaa_breaker_tripped_total = Counter(
    "noaa_breaker_tripped_total",
    "Count of per-station NOAA circuit-breaker trips (fires exactly once per open event).",
    labelnames=("station_id",),
)

freshness_gate_503_total = Counter(
    "freshness_gate_503_total",
    "Count of /conditions responses where the freshness gate returned 503.",
    labelnames=("station_id", "reason"),
)


__all__ = [
    "data_age_seconds",
    "ingest_success_total",
    "ingest_failure_total",
    "ingest_duration_seconds",
    "noaa_breaker_tripped_total",
    "freshness_gate_503_total",
]
