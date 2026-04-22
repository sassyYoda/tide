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
from prometheus_client import CollectorRegistry, make_asgi_app, multiprocess

from app.api.conditions import router as conditions_router
from app.api.health import router as health_router


def _build_metrics_registry() -> CollectorRegistry:
    """Return a CollectorRegistry; wire MultiProcessCollector if env is set."""
    registry = CollectorRegistry()
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.MultiProcessCollector(registry)
    return registry


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
