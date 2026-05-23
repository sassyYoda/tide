"""Phase 5 Wave 2 — Ragas runner fixtures.

These fixtures expect ``docker compose up -d`` to have brought up Postgres +
Redis + Qdrant + the FastAPI app. The Ragas CI workflow
(``.github/workflows/ragas.yml``) spins compose first; locally, run
``docker compose up -d`` from the repo root before invoking these tests.

The ``live_endpoint_ready`` fixture polls ``/healthz`` for up to 60s
(Assumption A7 from RESEARCH §Q1 line 630). If the backend is not ready,
the dependent test is skipped — not failed — so unit-only suites stay
green without docker.
"""
from __future__ import annotations

import os
import time

import httpx
import pytest


@pytest.fixture(scope="session")
def live_endpoint_ready() -> str:
    """Poll /healthz until 200 with a 60s budget; skip if not ready."""
    base = os.environ.get("RAGAS_ENDPOINT_BASE", "http://localhost:8000")
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base}/healthz", timeout=2.0)
            if r.status_code in (200, 503):
                # 503 is acceptable here — the endpoint exists; the body's
                # status field reports degraded but the route is reachable.
                return base
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    pytest.skip(f"backend at {base}/healthz not ready within 60s")
