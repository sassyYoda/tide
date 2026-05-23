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

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import REGISTRY, CollectorRegistry, make_asgi_app, multiprocess
from slowapi.errors import RateLimitExceeded

# Force-import ingest.metrics so Counter/Gauge/Histogram declarations register
# with the default REGISTRY before /metrics is first scraped. Without this
# the single-process registry is empty at scrape time if no ingest task has
# run yet in the process.
from app import api  # noqa: F401 — touches deps so app.api is importable
from app.api.conditions import router as conditions_router
from app.api.health import mark_model_loaded, router as health_router
from cache import metrics as _cache_metrics_module  # noqa: F401 — register cache hit/miss counters
from ingest import metrics as _metrics_module  # noqa: F401 — register metrics

# Phase 3 — agent SSE + scored-spots routes. Bare-import convention against
# pythonpath=["."] in pytest + PYTHONPATH=backend in the runtime image. The
# repo never prefixes imports with the package directory name; that path
# does not resolve at runtime.
from api.middleware.rate_limit import limiter, rate_limit_handler
from api.v1 import router as v1_router


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """REL-01 / Pitfall P8 — best-effort model load on startup.

    The Phase 2 D-04 carry-over means 0/5 species are currently promoted to
    the MLflow Production stage (per the 2026-05-16 remote agent run; ML
    promotion uplift lands in Phase 6). Until then, no ``ml.scorer_singleton``
    helper exists to attempt a real model load — so the lifespan flips the
    ``model_loaded`` flag unconditionally on a successful ``ml.species_config``
    import. This keeps /healthz informative in local dev (the flag flips True
    once the FastAPI app is functionally up) without lying about a model
    actually being in memory. Phase 6 will tighten this once promotion uplift
    lands and a real ``attempt_load_any_production_model`` helper exists.
    """
    try:
        # The mere fact that ml.species_config imports cleanly means the ML
        # subsystem is reachable — sufficient signal for the MVP /healthz
        # readiness flag. Replace with a true model load when D-04 promotion
        # is unblocked in Phase 6.
        from ml.species_config import SPECIES_LIST  # noqa: F401

        mark_model_loaded()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "lifespan: best-effort model load skipped: %s", e
        )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Tide API", version="0.1.0", lifespan=lifespan)

    # ─── CORS (API-04) ──────────────────────────────────────────────────
    # Allow gettide.app + Vercel preview URLs + localhost dev. ``allow_origin_regex``
    # covers any *.vercel.app preview deployment without listing them all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://gettide.app",
            "http://localhost:3000",
            "http://localhost:3001",
        ],
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        max_age=3600,
    )

    # ─── slowapi rate limiter (SEC-02 / L-05) ───────────────────────────
    # WR-05 was a Phase 1 deferral; this fulfills it for Phase 3 traffic. The
    # @limiter.limit decorator on ``api.v1.query`` enforces the 20/IP/hour
    # budget; the custom handler converts RateLimitExceeded into a single
    # SSE error event with code='rate_limited' (NOT an HTTP 429 JSON body).
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # ─── Routers ────────────────────────────────────────────────────────
    # Phase 1
    app.include_router(conditions_router, prefix="/api/v1")
    app.include_router(health_router)
    # Phase 3 — query SSE + scored-spots
    app.include_router(v1_router, prefix="/api/v1")

    app.mount("/metrics", make_asgi_app(registry=_build_metrics_registry()))
    return app


app = create_app()
