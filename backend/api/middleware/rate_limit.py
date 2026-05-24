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

# Operator bypass (defense-in-depth): when a request carries header
# ``X-Tide-Test-Token`` matching ``settings.rate_limit_bypass_token``, the
# limiter aggregates that traffic into a single high-ceiling bucket
# (``bypass:tide-test``) so the operator can exercise prod end-to-end without
# burning the public per-IP ceiling. When the env var is unset (dev/local),
# the bypass is disabled entirely — callers always hit the 20/hour limit.
_BYPASS_HEADER = "X-Tide-Test-Token"
_BYPASS_KEY = "bypass:tide-test"
_BYPASS_LIMIT = "10000/minute"  # effectively unlimited for operator probes
_PUBLIC_LIMIT = "20/hour"


def _is_bypass(request: Request) -> bool:
    """Return True iff request carries a valid operator bypass header.

    Returns False when the token is unset (None) — dev/local stays subject to
    the standard 20/hour limit, matching the public behavior.
    """
    token = settings.rate_limit_bypass_token
    if not token:
        return False
    return request.headers.get(_BYPASS_HEADER) == token


def _bypass_aware_key(request: Request) -> str:
    """Custom slowapi ``key_func``: returns the bypass bucket key for valid
    operator probes, otherwise falls back to the remote-address default.

    slowapi pairs this with ``_limit_for_request`` below: when ``key`` starts
    with ``bypass:`` the limit string switches to a high ceiling, so all
    bypass traffic shares one near-unlimited bucket and public traffic stays
    on the per-IP 20/hour bucket.
    """
    if _is_bypass(request):
        return _BYPASS_KEY
    return get_remote_address(request)


def _limit_for_request(key: str) -> str:
    """Dynamic limit string. slowapi invokes this with the result of the
    ``key_func`` (verified against slowapi 0.1.x: wrappers.py LimitGroup
    ``__iter__`` calls ``limit_provider(key_function(request))`` when the
    provider accepts a ``key`` parameter).
    """
    if key.startswith("bypass:"):
        return _BYPASS_LIMIT
    return _PUBLIC_LIMIT


# Module-level singleton — referenced by route decorators (e.g. api.v1.query).
# storage_uri shares the Phase 1 Redis instance; slowapi auto-namespaces its
# keys under ``LIMITER/<key_func>:<route>:<window>``.
limiter = Limiter(
    key_func=_bypass_aware_key,
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


__all__ = [
    "limiter",
    "rate_limit_handler",
    "_is_bypass",
    "_limit_for_request",
    "_bypass_aware_key",
]
