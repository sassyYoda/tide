"""FastAPI application factory.

Exposes three routes + one mount:

- ``GET /api/v1/conditions/{station_id}`` — public, freshness-gated.
- ``GET /healthz`` — liveness probe, NEVER gated (threat T-01-06-04).
- ``GET /metrics`` — Prometheus scrape target, mounted as an ASGI sub-app.

``/metrics`` uses a multiprocess ``CollectorRegistry`` so Celery workers
and FastAPI processes both write into the same ``PROMETHEUS_MULTIPROC_DIR``
(set in the Dockerfiles). Under bare-metal test runs the env var is
usually unset — in that case we still construct the registry with no
multiprocess collector, so unit/integration tests don't explode on the
``multiprocess.MultiProcessCollector`` call.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from prometheus_client import REGISTRY, CollectorRegistry, make_asgi_app, multiprocess

# Force-import ingest.metrics so Counter/Gauge/Histogram declarations register
# with the default REGISTRY before /metrics is first scraped. Without this
# the single-process registry is empty at scrape time if no ingest task has
# run yet in the process.
from app import api  # noqa: F401 — touches deps so app.api is importable
from app.api.conditions import router as conditions_router
from app.api.health import router as health_router
from ingest import metrics as _metrics_module  # noqa: F401 — register metrics


def _build_metrics_registry() -> CollectorRegistry:
    """Return a CollectorRegistry for /metrics.

    - Under ``PROMETHEUS_MULTIPROC_DIR`` (production workers): build a fresh
      registry and attach ``MultiProcessCollector`` so the scrape reads
      per-process *.db files instead of the default in-process registry.
    - Otherwise (single-process tests / local dev): return the default
      ``REGISTRY`` singleton so Counter/Gauge declarations in ``ingest.metrics``
      are visible at scrape time even with no samples recorded.
    """
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return registry
    return REGISTRY


def create_app() -> FastAPI:
    app = FastAPI(title="Tide API", version="0.1.0")
    # SKIP (WR-05): Per-IP rate limit (20/IP/hour — PROJECT.md quality bar)
    # is intentionally DEFERRED out of Phase 1 (Data Foundation). The Redis
    # infra needed as a slowapi storage backend is stood up here, but the
    # middleware + 429 ErrorEnvelope contract is scoped to a later REL/SEC
    # phase so Phase 1 stays focused on ingest correctness. Track as a
    # Phase N follow-up; see REVIEW-FIX WR-05 for context.
    app.include_router(conditions_router, prefix="/api/v1")
    app.include_router(health_router)
    app.mount("/metrics", make_asgi_app(registry=_build_metrics_registry()))
    return app


app = create_app()
