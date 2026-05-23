"""SSE keepalive — EventSourceResponse(ping=10) defends against Cloud Run idle timeout.

Plan 06-03 (Wave 1) adds `ping=10` + `ping_message_factory=lambda: ServerSentEvent(comment="keepalive")`
to backend/api/v1/query.py's EventSourceResponse construction (Pitfall P3).

Cloud Run drops idle HTTPS connections after ~15min (and the load balancer
after ~5min). A 10-second ping keeps the stream alive through long
Synthesizer LLM round-trips that may exceed both thresholds.

This is a static-source contract test rather than a runtime monkeypatch:
the SSE response is constructed lazily under TestClient and the ASGI plumbing
adds more risk of false positives than the grep-style check buys us. The
literal kwargs are simple to inspect and grep-checkable.
"""

from __future__ import annotations

import inspect


def test_query_route_constructs_eventsource_response_with_ping_10():
    """The query route MUST construct EventSourceResponse with ping=10 (Pitfall P3)."""
    from api.v1 import query as query_module

    src = inspect.getsource(query_module)
    assert "EventSourceResponse(" in src, "query.py must use EventSourceResponse"
    assert "ping=10" in src, (
        "query.py must construct EventSourceResponse(ping=10, ...) per Pitfall P3"
    )
    assert "ping_message_factory" in src, (
        "query.py must pass ping_message_factory= so the keepalive uses an SSE comment"
    )
    assert (
        'comment="keepalive"' in src or "comment='keepalive'" in src
    ), "ping_message_factory must emit ServerSentEvent(comment='keepalive')"
