"""SSE keepalive — EventSourceResponse(ping=10) defends against Cloud Run idle timeout.

RED SKELETON. Plan 06-03 (Wave 1) adds `ping=10` to backend/api/v1/query.py
EventSourceResponse construction and fills this test.

The kwarg `ping=10` instructs sse-starlette to emit a `: ping` comment line every 10s
on idle SSE streams. Cloud Run drops the connection after ~15min of total silence (and
~5min on the load balancer); a 10s ping keeps the stream alive through long Synthesizer
LLM round-trips.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 1 — 06-03 adds ping=10 to backend/api/v1/query.py")
def test_event_source_response_constructed_with_ping_10():
    """Once filled, monkeypatch EventSourceResponse and assert it was called with ping=10."""
