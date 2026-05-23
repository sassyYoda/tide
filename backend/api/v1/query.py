"""POST /api/v1/query — SSE endpoint wiring iter_sse_events.

Wave 4 layout (W-4 in 03-PATTERNS.md): the route emits an initial
``progress(planner)`` event the moment the stream opens — BEFORE invoking
the LangGraph runtime — so the client receives its first byte well within
the A-07 / P-03 2 s budget. The runtime (agent.runtime.iter_sse_events)
ALSO emits its own ``progress(planner)`` after the planner-update arrives
to keep its unit tests deterministic. The route layer does NOT de-duplicate
on the wire; the frontend treats consecutive ``progress`` events with the
same stage idempotently. (See the runtime module docstring for the
rationale.)

Cache (D-02.1 + Phase 5 P-09 fix):

- POST-graph WRITE keys on the canonical D-02.1 shape: sha256(normalized_query
  + canonical_species + spot_id + time_window_label) via ``query_cache_key``.
- PRE-graph READ short-circuit uses a fast query-only key
  (``fast_query_cache_key``) since canonical fields aren't available before
  the Planner runs. Trade-off: cross-species collisions are possible but rare
  in practice — repeat queries within 15min are typically the same person
  rephrasing the same intent. v1.x can tighten to a planner-only subgraph
  for full canonical-field precision if cross-species false hits surface.
- On cache hit: emit ``progress(planner)`` + ``progress(synthesizer)`` + the
  cached ``recommendation`` event. partial_conditions is NOT replayed (live
  conditions data; staler than 15min would be misleading). The frontend
  reducer handles the abbreviated event sequence transparently.
- POST-graph also writes to the fast key (in addition to the canonical key)
  so the read-path short-circuit fires on subsequent identical queries.

The cache key uses hashlib.sha256 (deterministic across processes); see
backend/cache/query_cache.py for the rationale on never using the
built-in non-deterministic hashing primitive.

Rate limit (SEC-02 / L-05): @limiter.limit("20/hour"); the custom
``RateLimitExceeded`` handler (api.middleware.rate_limit.rate_limit_handler)
converts slowapi's 429 into a single SSE ``error`` event with
``code='rate_limited'`` (not an HTTP 429 JSON body). The decorator runs
BEFORE the response stream begins (slowapi's standard pattern; Pitfall 2).

Pydantic (SEC-06): query is bounded to 500 chars at the validation layer.
Body validation failures return HTTP 422 — the frontend treats those as
client-side errors; not stream-level errors.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from agent.runtime import iter_sse_events
from agent.sse_protocol import (
    RecommendationPayload,
    make_error_payload,
    make_progress_payload,
)
from api.middleware.rate_limit import limiter
from app.deps.redis import get_redis
from cache.query_cache import (
    fast_query_cache_key,
    get_cached_query,
    put_cached_query,
    query_cache_key,
)

log = logging.getLogger(__name__)

router = APIRouter()


class LocationHint(BaseModel):
    """Optional spatial context for spot resolution (D-05)."""

    lat: float | None = None
    lon: float | None = None
    spot_name: str | None = Field(default=None, max_length=200)


class QueryBody(BaseModel):
    """User query body. SEC-06 bound: max_length=500 on the natural-language query.

    OPS-02 (plan 05-04): ``session_id`` is optional, server-internal metadata
    used to correlate multiple traces under one Langfuse session (the trace's
    ``sessionId`` field). It is NOT echoed back on the SSE wire — only
    propagated into the LangGraph callback metadata so the resulting Langfuse
    trace can be looked up by session in integration tests.
    """

    query: str = Field(..., min_length=1, max_length=500)
    location_hint: LocationHint | None = None
    session_id: str | None = Field(default=None, max_length=200)


@router.post("/query")
@limiter.limit("20/hour")
async def query(
    request: Request,  # required positional for slowapi key_func
    body: QueryBody,
    redis: Redis = Depends(get_redis),
) -> EventSourceResponse:
    """Stream a recommendation for one natural-language fishing query.

    Returns ``EventSourceResponse`` whose generator yields events in the
    locked sequence (in-scope happy path):

        progress(planner)  ← emitted by the ROUTE at stream open (W-4)
        progress(planner)  ← emitted by the runtime after planner update
        progress(data_fetcher)
        partial_conditions
        progress(rag_retriever)
        progress(synthesizer)
        recommendation
    """
    body_dict = body.model_dump()
    # Pitfall P3 — Cloud Run drops idle connections at ~5min (LB) / ~15min
    # (service). A 10-second ping (rendered as ``: keepalive\n\n`` SSE
    # comment by the ServerSentEvent(comment=...) factory) keeps the stream
    # alive through long Synthesizer LLM round-trips. The comment is
    # silently discarded by eventsource-parser v3.0.8 on the frontend
    # (RESEARCH A7).
    return EventSourceResponse(
        _event_generator(request, body_dict, redis),
        ping=10,
        ping_message_factory=lambda: ServerSentEvent(comment="keepalive"),
    )


async def _event_generator(
    request: Request,
    body: dict[str, Any],
    redis: Redis,
) -> AsyncIterator[dict]:
    """Translate iter_sse_events tuples into sse-starlette dict events.

    W-4 first-byte guarantee: yields ``progress(planner)`` IMMEDIATELY (before
    the LangGraph stream is opened) so the client sees activity within the
    A-07 / P-03 2 s budget.

    Captures spot_id from the streamed ``partial_conditions`` event so the
    post-graph result cache key reflects the canonical spot identity. Other
    canonical fields (species_canonical, time_window_label) are not on the
    SSE wire (the runtime payload whitelist excludes them — Pitfall 7) so
    the cache key uses None for those slots — still deterministic, lower
    hit rate. Uplift to a planner-only subgraph in a follow-up if measured
    cache hit rate justifies it.
    """
    # W-4: first byte before the graph runs.
    yield {
        "event": "progress",
        "data": make_progress_payload("planner").model_dump_json(),
    }

    # Phase 5 P-09 fix: pre-graph cache check (read-path short-circuit).
    # If a recent identical query is cached, replay the recommendation event
    # and skip the full LangGraph run entirely. Cross-species collisions
    # documented in module docstring; v1.x can tighten via planner-only
    # subgraph. partial_conditions intentionally NOT replayed — those carry
    # live conditions data that shouldn't be served staler than freshly fetched.
    fast_key = fast_query_cache_key(body.get("query", ""))
    cached = await get_cached_query(redis, fast_key)
    if cached is not None and cached.get("event") == "recommendation":
        # Emit a tight progress(synthesizer) so the frontend reducer transitions
        # through streaming(synthesizer) before the final recommendation arrives.
        yield {
            "event": "progress",
            "data": make_progress_payload("synthesizer").model_dump_json(),
        }
        # Replay the cached recommendation payload verbatim.
        import json as _json
        yield {
            "event": "recommendation",
            "data": _json.dumps(cached["payload"]),
        }
        return

    final_payload: RecommendationPayload | None = None
    final_spot_id: int | None = None
    final_species: str | None = None
    final_time_window: str | None = None

    try:
        async for ev_type, payload in iter_sse_events(
            body, session_id=body.get("session_id")
        ):
            if await request.is_disconnected():
                log.info("query: client disconnected mid-stream")
                break

            yield {"event": ev_type, "data": payload.model_dump_json()}

            if ev_type == "partial_conditions":
                # Capture spot identity for the post-graph cache key (D-02.1).
                final_spot_id = getattr(payload, "spot_id", None)
            elif ev_type == "recommendation":
                final_payload = payload  # type: ignore[assignment]
                # HR-01 (Phase 3 code-review): RecommendationPayload now widens
                # to carry species_canonical + time_window_label so the cache
                # key is complete. Without these, Phase 4's read-path wiring
                # would silently return cross-species false hits.
                p_spot = getattr(payload, "spot_id", None)
                if p_spot is not None:
                    final_spot_id = p_spot
                final_species = getattr(payload, "species_canonical", None)
                final_time_window = getattr(payload, "time_window_label", None)
    except Exception as e:  # noqa: BLE001 — last-resort safety net
        # iter_sse_events is documented as never-raising (it converts
        # exceptions to a terminal error event). This catch exists for
        # belt-and-braces protection against future runtime changes.
        log.exception("query: unexpected error in event_generator: %s", e)
        err = make_error_payload("internal", "Unexpected error.", None)
        yield {"event": "error", "data": err.model_dump_json()}
        return

    # Post-graph cache write — best-effort, no impact on the delivered stream.
    # Key construction per D-02.1: sha256(normalized_query + canonical_species
    # + spot_id + time_window_label). All four inputs are deterministic;
    # ``query_cache_key`` is implemented with hashlib.sha256 (see
    # backend/cache/query_cache.py for why the non-deterministic Python
    # primitive is unsafe here — PYTHONHASHSEED is randomized across processes).
    if final_payload is not None:
        try:
            cached_value = {
                "event": "recommendation",
                "payload": final_payload.model_dump(mode="json"),
            }
            refined_key = query_cache_key(
                body.get("query", ""),
                final_species,
                final_spot_id,
                final_time_window,
            )
            await put_cached_query(redis, refined_key, cached_value)
            # Phase 5 P-09 fix: also write to the fast (query-only) key so
            # subsequent identical queries hit the pre-graph short-circuit
            # above. Same TTL (15min) and same payload.
            await put_cached_query(redis, fast_key, cached_value)
        except Exception as e:  # noqa: BLE001
            log.warning("query: cache write failed (non-fatal): %s", e)


__all__ = ["router", "QueryBody", "LocationHint"]
