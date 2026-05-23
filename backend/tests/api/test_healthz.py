"""REL-01 / Pitfall P3 readiness-probe tests for ``/healthz``.

Wave 1 (plan 05-02) replaces the existing ``/healthz`` stub with the L-05
shape (``{ts_lag_seconds, qdrant_ok, model_loaded, status}``) and adds the
required ``Cache-Control: no-store`` header (Pitfall P3). Wave 0 (this file)
ships RED SKELETONS so plan 05-02 can fill them without inventing files.

All tests are integration-marked (require ``test_client`` + Redis/Qdrant
testcontainers) and skipped at Wave 0.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")
def test_healthz_returns_200_when_healthy():
    """Seed fresh ``conditions_15min`` row, set model_loaded=True; assert 200 + shape."""
    pass


@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")
def test_healthz_returns_503_when_qdrant_down():
    """Monkeypatch ``get_qdrant()`` to raise → response is 503 with status='degraded'."""
    pass


@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")
def test_healthz_has_no_store_cache_header():
    """Pitfall P3: response carries ``Cache-Control: no-store`` (load-balancer caches lie)."""
    pass


@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")
def test_healthz_returns_503_when_ts_lag_above_threshold():
    """Seed stale CAGG bucket → 503 with ts_lag_seconds above the freshness threshold."""
    pass
