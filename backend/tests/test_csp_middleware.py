"""SEC-05 — CSP middleware response header tests.

RED SKELETONS. Plan 06-03 (Wave 1) wires CSPMiddleware into backend/app/main.py and
fills these test bodies. Until then they're marked skip so the quick suite stays green.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 1 — 06-03 wires CSPMiddleware into main.py")
def test_healthz_carries_csp_header():
    """GET /healthz should return a Content-Security-Policy header with default-src 'self'."""


@pytest.mark.skip(reason="Wave 1 — 06-03 wires CSPMiddleware into main.py")
def test_csp_includes_frame_ancestors_none():
    """Every response CSP must include `frame-ancestors 'none'` (clickjacking defense)."""


@pytest.mark.skip(reason="Wave 1 — 06-03 wires CSPMiddleware into main.py")
def test_csp_blocks_eval():
    """CSP policy must not include 'unsafe-eval'; script-src is `'self' 'unsafe-inline' ...` only."""
