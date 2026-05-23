"""Phase 6 smoke tests against the deployed Cloud Run backend.

Skipped by default. To run:
  export TIDE_DEPLOYED_URL=https://tide-backend-XXX.run.app
  pytest tests/smoke/
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TIDE_DEPLOYED_URL"),
    reason="set TIDE_DEPLOYED_URL to run smoke tests against deployed backend",
)

BASE = os.environ.get("TIDE_DEPLOYED_URL", "")


def test_healthz_returns_200():
    r = httpx.get(f"{BASE}/healthz", timeout=15.0)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_csp_header_present():
    r = httpx.get(f"{BASE}/healthz", timeout=15.0)
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp, f"CSP missing or wrong: {csp!r}"


def test_https_only():
    # HTTP should redirect to HTTPS.
    http_url = BASE.replace("https://", "http://")
    r = httpx.get(f"{http_url}/healthz", timeout=15.0, follow_redirects=False)
    assert r.status_code in (301, 308), f"expected redirect, got {r.status_code}"
