"""SEC-05 — CSP middleware response header tests.

Plan 06-03 (Wave 1) wires CSPMiddleware into backend/app/main.py AFTER CORS
and BEFORE routers. These tests assert the locked CSP shape from
backend/app/middleware/csp.py:CSP_POLICY (L-04).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_healthz_carries_csp_header(client):
    """GET /healthz must carry a Content-Security-Policy header containing default-src 'self'."""
    r = client.get("/healthz")
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp, f"CSP missing default-src directive: {csp!r}"


def test_csp_includes_frame_ancestors_none(client):
    """Every response CSP must include frame-ancestors 'none' (clickjacking defense)."""
    r = client.get("/healthz")
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp, f"CSP missing frame-ancestors 'none': {csp!r}"


def test_csp_blocks_unsafe_eval(client):
    """CSP script-src must NOT include 'unsafe-eval'.

    'unsafe-inline' on style-src is accepted (Tailwind v4 requirement) but
    'unsafe-eval' would defeat the policy for the script directive.
    """
    r = client.get("/healthz")
    csp = r.headers.get("content-security-policy", "")
    script_src_segment = next(
        (s for s in csp.split(";") if s.strip().startswith("script-src")), ""
    )
    assert "unsafe-eval" not in script_src_segment, (
        f"unsafe-eval found in script-src: {script_src_segment!r}"
    )
