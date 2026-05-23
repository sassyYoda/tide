"""LangGraph stream → typed SSE event translator.

This is the only place LangGraph's ``astream(version='v2')`` event shape is
mapped to the locked SSE protocol (CONTEXT D-03). All raw-state filtering
goes through ``agent.sse_protocol``'s whitelist builders (Pitfall 7).

ASTREAM CHUNK SHAPE (LangGraph 1.1.8, ``version='v2'``, ``stream_mode=[...]``):

    {'type': 'updates' | 'custom', 'ns': (...), 'data': <payload>}

For ``updates``: ``data`` is ``{<node_name>: <state_update_dict>}``.
For ``custom``: ``data`` is whatever ``get_stream_writer()(...)`` was called with.

(For robustness this module also accepts the older 2-tuple form
``(stream_mode_label, payload)`` returned when ``version='v1'`` is used with a
list of stream modes — both forms are unified into a normalized
``(chunk_type, data)`` pair before mapping.)

Event mapping (locked sequence per plan 03-04 success criteria):

    Planner update with intent='out-of-scope' → error(planner_out_of_scope)
                                                 + return (no further nodes)
    Planner update otherwise                  → progress(planner)
    Data Fetcher update                       → progress(data_fetcher)
                                                 + partial_conditions
    RAG Retriever update                      → progress(rag_retriever)
    Synthesizer update                        → progress(synthesizer)
                                                 + recommendation

The runtime accumulates ``state_so_far`` so payload builders see the FULL
state — not just the per-node delta. This matters for
``make_recommendation_payload`` which needs ``conditions``,
``ml_score_available``, ``rag_latency_ms``, etc. which were written by
upstream nodes.

Error code mapping (plan 03-04 success criteria):

    anthropic.APIError / APIStatusError / APIConnectionError → llm_unavailable
    httpx.HTTPError                                          → llm_unavailable
    asyncio.TimeoutError                                     → planner_timeout
                                                                (if intent unset)
                                                                else internal
    everything else                                          → internal

Never raises — always emits a terminal ``error`` event.

Pitfall 7: every emission MUST go through one of the ``make_*_payload``
builders. Never echo raw ``state`` or raw ``data`` to the wire.

Note on the route layer (plan 03-05): ``progress(planner)`` is also emitted by
the route at stream open BEFORE the graph runs (so the client sees activity in
≤2s — A-07). This module STILL emits its own ``progress(planner)`` after the
planner-update arrives so unit tests of ``iter_sse_events`` in isolation are
deterministic; the route layer is responsible for de-duplicating the sequence
for clients (W-4 in 03-PATTERNS.md).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, TYPE_CHECKING
from uuid import uuid4

import anthropic
import httpx

from agent.graph import get_compiled_graph
from agent.sse_protocol import (
    SSEEventType,
    make_error_payload,
    make_partial_conditions_payload,
    make_progress_payload,
    make_recommendation_payload,
)
from agent.state import TideAgentState

if TYPE_CHECKING:
    from pydantic import BaseModel

log = logging.getLogger(__name__)


REJECT_MESSAGES: dict[str, str] = {
    "non_mvp_species": (
        "I only cover striper, fluke, bluefish, weakfish, and tautog right now. "
        "Try one of those at a NJ saltwater spot."
    ),
    "non_nj_geo": (
        "I only cover NJ saltwater right now. "
        "Try Sandy Hook, Manasquan, or Barnegat Inlet."
    ),
    "non_fishing": (
        "I'm a fishing recommender. "
        "Try asking about fishing for a specific species at a specific spot."
    ),
    "none": "Out of scope.",
}


def _normalize_chunk(chunk: Any) -> tuple[str | None, Any]:
    """Coerce the LangGraph astream chunk into a ``(chunk_type, data)`` pair.

    Handles both the v2 dict form ``{'type', 'ns', 'data'}`` and the legacy
    2-tuple form ``(stream_mode_label, payload)``. Returns ``(None, None)``
    for any chunk we can't recognise (defensively logged + skipped).
    """
    if isinstance(chunk, dict) and "type" in chunk and "data" in chunk:
        return chunk.get("type"), chunk.get("data")
    if isinstance(chunk, tuple) and len(chunk) == 2:
        return chunk[0], chunk[1]
    log.debug("runtime: unrecognized astream chunk shape: %r", chunk)
    return (None, None)


async def iter_sse_events(
    query_body: dict[str, Any],
    *,
    request_id: str | None = None,
    session_id: str | None = None,
) -> AsyncIterator[tuple[SSEEventType, "BaseModel"]]:
    """Async-generate ``(event_type, payload)`` tuples for one query.

    Caller (FastAPI route in plan 03-05) wraps this in
    ``sse_starlette.EventSourceResponse``. Never raises — exceptions inside
    the graph are caught and converted to a terminal ``error`` event.

    OPS-02 (plan 05-04): ``session_id`` is propagated into the LangGraph
    invocation as ``config.metadata.langfuse_session_id``. The Langfuse
    v4 LangChain ``CallbackHandler`` recognises this metadata key and
    sets ``sessionId`` on the resulting trace, enabling cross-trace
    correlation in the Langfuse Sessions UI and per-session integration
    tests.
    """
    rid = request_id or str(uuid4())
    initial_state: TideAgentState = {
        "query": query_body.get("query", ""),
        "location_hint": query_body.get("location_hint"),
        "request_id": rid,
    }
    state_so_far: dict[str, Any] = dict(initial_state)

    compiled = get_compiled_graph()

    # OPS-02: propagate langfuse_session_id (when provided) via the LangGraph
    # invocation config. The Langfuse v4 LangChain CallbackHandler reads
    # config.metadata.langfuse_session_id and attaches it as the trace's
    # sessionId. This is the canonical wiring per Langfuse docs (see
    # langfuse.com/docs/integrations/langchain/get-started).
    astream_kwargs: dict[str, Any] = {
        "stream_mode": ["updates", "custom"],
        "version": "v2",
    }
    if session_id:
        astream_kwargs["config"] = {
            "metadata": {"langfuse_session_id": session_id}
        }

    try:
        async for chunk in compiled.astream(
            initial_state,
            **astream_kwargs,
        ):
            chunk_type, data = _normalize_chunk(chunk)

            if chunk_type == "updates":
                if not isinstance(data, dict):
                    continue
                for node_name, update in data.items():
                    if not isinstance(update, dict):
                        continue
                    state_so_far.update(update)

                    if node_name == "planner":
                        # D-04.3: out-of-scope short-circuit — emit error + stop.
                        if state_so_far.get("intent") == "out-of-scope":
                            reason = state_so_far.get("reject_reason", "none")
                            yield (
                                "error",
                                make_error_payload(
                                    "planner_out_of_scope",
                                    REJECT_MESSAGES.get(
                                        reason, REJECT_MESSAGES["none"]
                                    ),
                                    state_so_far,
                                ),
                            )
                            return
                        yield ("progress", make_progress_payload("planner"))
                    elif node_name == "data_fetcher":
                        yield ("progress", make_progress_payload("data_fetcher"))
                        yield (
                            "partial_conditions",
                            make_partial_conditions_payload(state_so_far),
                        )
                    elif node_name == "rag_retriever":
                        yield ("progress", make_progress_payload("rag_retriever"))
                    elif node_name == "synthesizer":
                        yield ("progress", make_progress_payload("synthesizer"))
                        yield (
                            "recommendation",
                            make_recommendation_payload(state_so_far),
                        )
                    else:
                        log.warning(
                            "runtime: unknown node update: %s (skipped)", node_name
                        )
            elif chunk_type == "custom":
                # Reserved for future per-node custom progress emissions via
                # ``langgraph.config.get_stream_writer()``. Currently unused —
                # all progress events are emitted by this translator above.
                log.debug("runtime: custom event: %r", data)
            # Other chunk types (None, unknown) are dropped — already logged in
            # _normalize_chunk for the unknown case.

    except (
        anthropic.APIError,
        anthropic.APIStatusError,
        anthropic.APIConnectionError,
    ) as e:
        log.warning("runtime: synthesizer LLM unavailable: %s", e)
        yield (
            "error",
            make_error_payload(
                "llm_unavailable",
                "The recommendation engine is temporarily unavailable. "
                "Please try again.",
                state_so_far,
            ),
        )
    except httpx.HTTPError as e:
        log.warning("runtime: HTTP error during graph run: %s", e)
        yield (
            "error",
            make_error_payload(
                "llm_unavailable",
                "Network error reaching the recommendation engine. "
                "Please try again.",
                state_so_far,
            ),
        )
    except (asyncio.TimeoutError, TimeoutError) as e:
        log.warning("runtime: timeout: %s", e)
        # Best-effort attribution: if planner hadn't completed (no intent),
        # label as planner_timeout per the SSEErrorCode enum.
        if state_so_far.get("intent") is None:
            yield (
                "error",
                make_error_payload(
                    "planner_timeout",
                    "Planner timed out. Please try again.",
                    state_so_far,
                ),
            )
        else:
            yield (
                "error",
                make_error_payload(
                    "internal",
                    "An internal timeout occurred. Please try again.",
                    state_so_far,
                ),
            )
    except Exception as e:  # noqa: BLE001
        log.exception("runtime: internal error during graph run: %s", e)
        yield (
            "error",
            make_error_payload(
                "internal",
                "An internal error occurred. Please try again.",
                state_so_far,
            ),
        )


__all__ = ["iter_sse_events", "REJECT_MESSAGES"]
