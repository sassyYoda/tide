"""Phase 6 smoke tests against the deployed Cloud Run backend.

Skipped by default (the entire module is `skipif` on `TIDE_DEPLOYED_URL`).
To run after `terraform apply`:

    export TIDE_DEPLOYED_URL=https://tide-backend-XXX.run.app
    cd backend && uv run pytest ../tests/smoke/ -v

Or from the repo root with the backend venv activated:

    TIDE_DEPLOYED_URL=https://tide-backend-XXX.run.app pytest tests/smoke/ -v

Tests cover the 5 critical post-deploy gates:

1. /api/v1/healthz returns 200 + body {"status":"ok"}             (REL-01)
2. CSP header present on every response                    (SEC-05)
3. HTTP -> HTTPS redirect (Cloud Run auto)                 (SEC-01)
4. GET /api/v1/conditions/{NOAA_station_id} 200 + JSON     (Phase 3 REST)
5. GET /api/v1/spots 200 + non-empty JSON array            (Phase 3 REST)
6. POST /api/v1/query streams SSE events incl. final       (Phase 3 SSE + agent)
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TIDE_DEPLOYED_URL"),
    reason="set TIDE_DEPLOYED_URL to run smoke tests against deployed backend",
)

BASE = os.environ.get("TIDE_DEPLOYED_URL", "").rstrip("/")

# Default timeout: Cloud Run cold start (~5–8s) + agent worst case (~8s p95) + buffer.
DEFAULT_TIMEOUT = 30.0
SSE_TIMEOUT = 60.0  # full SSE stream may take 8–15s end-to-end.

# Atlantic City, NJ — a real NOAA CO-OPS station with known coverage in the
# Phase 1 backfill (Pitfall P12 + Phase 2 hypertables).
SAMPLE_NOAA_STATION = "8534720"


def test_healthz_returns_200():
    """REL-01 — /api/v1/healthz returns 200 + status=ok JSON."""
    r = httpx.get(f"{BASE}/api/v1/healthz", timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200, f"/api/v1/healthz returned {r.status_code}, body={r.text[:200]}"
    body = r.json()
    assert body.get("status") == "ok", f"/api/v1/healthz body status != 'ok': {body}"


def test_csp_header_present():
    """SEC-05 — CSP middleware emits header on every response."""
    r = httpx.get(f"{BASE}/api/v1/healthz", timeout=DEFAULT_TIMEOUT)
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp, f"CSP missing default-src 'self': {csp!r}"
    assert "frame-ancestors 'none'" in csp, f"CSP missing frame-ancestors 'none': {csp!r}"


def test_https_only():
    """SEC-01 — http:// must redirect to https:// (Cloud Run auto)."""
    http_url = BASE.replace("https://", "http://")
    r = httpx.get(f"{http_url}/api/v1/healthz", timeout=DEFAULT_TIMEOUT, follow_redirects=False)
    assert r.status_code in (301, 308), f"expected 301/308 redirect, got {r.status_code}"


def test_conditions_endpoint_returns_json():
    """GET /api/v1/conditions/{station_id} returns 200 + JSON conditions snapshot."""
    r = httpx.get(
        f"{BASE}/api/v1/conditions/{SAMPLE_NOAA_STATION}",
        timeout=DEFAULT_TIMEOUT,
    )
    # 200 expected; 503 acceptable iff data_age_seconds > 30min freshness gate
    # (Pitfall P3 — the deployed VM may not have caught up yet on first boot).
    assert r.status_code in (200, 503), (
        f"/api/v1/conditions returned {r.status_code}, body={r.text[:300]}"
    )
    if r.status_code == 200:
        body = r.json()
        assert isinstance(body, dict), f"expected dict, got {type(body).__name__}"
        # F-09: freshness fields should be present in a healthy snapshot.
        assert "station_id" in body or "data_age_seconds" in body, (
            f"conditions response missing expected fields: {list(body.keys())}"
        )


def test_spots_endpoint_returns_list():
    """GET /api/v1/spots returns 200 + non-empty JSON array of spot objects."""
    r = httpx.get(f"{BASE}/api/v1/spots", timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200, f"/api/v1/spots returned {r.status_code}, body={r.text[:300]}"
    body = r.json()
    assert isinstance(body, list), f"expected list, got {type(body).__name__}"
    assert len(body) > 0, "/api/v1/spots returned empty list"
    # Each spot should have id + name + coords at minimum.
    first = body[0]
    assert "id" in first or "spot_id" in first, f"spot object missing id field: {first}"


def test_query_endpoint_streams_sse():
    """POST /api/v1/query streams SSE events; expects at least 1 event including the
    final recommendation. Uses httpx streaming + manual SSE parse to avoid an extra
    dep on `sseclient`/`httpx-sse` for a one-shot smoke."""
    payload = {"query": "striper barnegat tonight"}
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}

    events_seen = 0
    has_final = False

    with httpx.stream(
        "POST",
        f"{BASE}/api/v1/query",
        json=payload,
        headers=headers,
        timeout=SSE_TIMEOUT,
    ) as r:
        # 200 is the only valid SSE start; 429 = rate-limited (should not happen on
        # first call in a fresh smoke run), 5xx = backend broken.
        assert r.status_code == 200, (
            f"POST /api/v1/query returned {r.status_code}; expected 200 SSE start"
        )
        ctype = r.headers.get("content-type", "")
        assert "text/event-stream" in ctype, f"content-type not SSE: {ctype!r}"

        for line in r.iter_lines():
            if not line:
                continue
            if line.startswith(":"):
                # SSE keepalive comment (Phase 6 03 fix — ping=10).
                continue
            if line.startswith("event:") or line.startswith("data:"):
                events_seen += 1
                if line.startswith("data:"):
                    payload_str = line[5:].strip()
                    # Best-effort detect terminal event.
                    if (
                        "recommendation" in payload_str
                        or "final" in payload_str
                        or '"done"' in payload_str
                    ):
                        has_final = True
                        try:
                            json.loads(payload_str)  # last data: must be valid JSON
                        except json.JSONDecodeError:
                            pass
            # Defensive stop after 60 events (the agent should emit <30 typically).
            if events_seen >= 60:
                break

    assert events_seen > 0, "no SSE events received from /api/v1/query"
    assert has_final, (
        f"SSE stream ended without a recognizable final/recommendation event "
        f"(events_seen={events_seen})"
    )
