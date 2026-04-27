"""SEC-02 rate limit: slowapi (Redis-backed) + custom SSE error handler.

L-05: 20/IP/hour via Redis INCR+EXPIRE-equivalent (slowapi handles internally).
RESEARCH Pitfall 2: limiter must fire BEFORE EventSourceResponse headers
flush — apply at route decorator, not as middleware.
RESEARCH Q4: emit a single SSE error event on 429, not an HTTP 429 JSON body.

The frontend EventSource consumer treats HTTP 429 as a connection error
(no event delivered). Surfacing the rate-limit decision as a stream-level
SSE ``error`` event with ``code='rate_limited'`` keeps the frontend's error
rendering path uniform across all rate-limit / synthesis / network failures.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

from agent.sse_protocol import make_error_payload
from app.config import settings

log = logging.getLogger(__name__)

# Module-level singleton — referenced by route decorators (e.g. api.v1.query).
# storage_uri shares the Phase 1 Redis instance; slowapi auto-namespaces its
# keys under ``LIMITER/<key_func>:<route>:<window>``.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=[],  # no global default; per-route only
)


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> EventSourceResponse:
    """Convert slowapi 429 into a stream-level SSE error event.

    Returning EventSourceResponse here means the EventSource client on the
    frontend sees ONE 'error' event, then EOS — exactly the same shape as
    other agent failures (D-03.1 closed-enum error code ``rate_limited``).
    """
    log.info(
        "rate_limit: 429 from %s (limit=%s)",
        get_remote_address(request),
        getattr(exc, "detail", "?"),
    )

    async def _gen() -> AsyncIterator[dict]:
        payload = make_error_payload(
            "rate_limited",
            "Too many queries. Please try again in a minute.",
            None,
        )
        yield {"event": "error", "data": payload.model_dump_json()}

    return EventSourceResponse(_gen(), status_code=200)


__all__ = ["limiter", "rate_limit_handler"]
