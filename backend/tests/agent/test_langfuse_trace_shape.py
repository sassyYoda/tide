"""OPS-02 integration test — Langfuse trace shape verification.

Wave 3 (plan 05-04) implementation: with real Langfuse credentials in env +
docker-compose backend live at $BACKEND_URL, runs one query through
``POST /api/v1/query`` with a unique ``session_id`` in the request body,
then polls the Langfuse Public API for the matching trace and asserts the
4 LangGraph node spans + session_id propagation + token / cost aggregates.

Skipped gracefully when ``LANGFUSE_PUBLIC_KEY`` or ``LANGFUSE_SECRET_KEY``
env are missing (so the default ``uv run pytest`` pass that excludes the
``integration`` marker — or any pass without keys — won't fail). Run via:

    cd backend
    LANGFUSE_PUBLIC_KEY=pk-... LANGFUSE_SECRET_KEY=sk-... \\
      BACKEND_URL=http://localhost:8000 \\
      uv run pytest tests/agent/test_langfuse_trace_shape.py -v

Per CONTEXT L-05 the OPS-02 trace MUST capture:
  - 4 per-node spans named planner / data_fetcher / rag_retriever / synthesizer
  - per-node input + output
  - sessionId propagation from the route
  - totalTokens > 0 (aggregate across LLM observations)
  - totalCost present (may be 0 if pricing not configured, but field exists)
"""
from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration


LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")


def _langfuse_auth() -> tuple[str, str]:
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        pytest.skip("LANGFUSE_*_KEY not set — skipping OPS-02 integration trace shape test")
    return (pk, sk)


def _fetch_trace_by_session(session_id: str, auth: tuple[str, str]) -> dict | None:
    """Poll Langfuse for up to ~120 s for a trace with matching sessionId.

    Langfuse ingestion is eventually consistent; the LangChain CallbackHandler
    flushes asynchronously, so the trace may not be queryable for ~5-90 s
    after the SSE stream closes (measured: ~30-60 s typical on Langfuse Cloud).
    """
    for _ in range(40):
        try:
            r = httpx.get(
                f"{LANGFUSE_HOST}/api/public/traces",
                params={"sessionId": session_id},
                auth=auth,
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    trace_id = data[0]["id"]
                    full = httpx.get(
                        f"{LANGFUSE_HOST}/api/public/traces/{trace_id}",
                        auth=auth,
                        timeout=10.0,
                    )
                    if full.status_code == 200:
                        return full.json()
        except Exception:  # noqa: BLE001 — best-effort polling
            pass
        time.sleep(3)
    return None


def test_trace_captures_4_node_spans_and_session_id():
    """OPS-02: one /api/v1/query call produces a Langfuse trace with the
    expected sessionId, 4 node spans, and aggregate token/cost fields.
    """
    auth = _langfuse_auth()
    session_id = f"ops02-test-{uuid.uuid4()}"
    query = (
        "Where should I throw bunker chunks for stripers on the outgoing tide "
        "at Barnegat Inlet?"
    )

    # Drive the live SSE stream end-to-end so the LangGraph runtime completes
    # and the Langfuse CallbackHandler flushes its trace.
    with httpx.stream(
        "POST",
        f"{BACKEND_URL}/api/v1/query",
        json={"query": query, "session_id": session_id},
        headers={"Accept": "text/event-stream"},
        timeout=60.0,
    ) as resp:
        assert resp.status_code == 200, f"backend returned {resp.status_code}"
        # Drain the stream so the agent run completes server-side.
        for _ in resp.iter_lines():
            pass

    trace = _fetch_trace_by_session(session_id, auth)
    assert trace is not None, (
        f"No Langfuse trace found for session_id={session_id} within 120s — "
        "either ingestion is slow, LANGFUSE_*_KEY do not match the project, "
        "or session_id propagation is not wired in iter_sse_events"
    )

    # session_id propagation — Langfuse stores it as sessionId on the trace.
    assert trace.get("sessionId") == session_id, (
        f"sessionId mismatch on trace {trace.get('id')}: got {trace.get('sessionId')!r}, "
        f"expected {session_id!r}"
    )

    # 4 node spans must be present. The Langfuse Public API returns full
    # observations[] on GET /api/public/traces/{id}.
    observations = trace.get("observations", []) or []
    span_names = {o.get("name") for o in observations}
    expected_nodes = {"planner", "data_fetcher", "rag_retriever", "synthesizer"}
    missing = expected_nodes - span_names
    assert not missing, (
        f"Missing node spans in trace {trace.get('id')}: {missing}; "
        f"got span names {span_names}"
    )

    # Per-node input/output non-empty
    for o in observations:
        name = o.get("name")
        if name in expected_nodes:
            assert o.get("input") is not None, f"Node {name!r} has no input on trace {trace.get('id')}"
            assert o.get("output") is not None, f"Node {name!r} has no output on trace {trace.get('id')}"

    # Aggregate OPS-02 fields.
    #
    # Note (deviation from plan recipe): Langfuse v4 does NOT expose a top-level
    # ``totalTokens`` field on the GET /api/public/traces/{id} response — only
    # ``totalCost``. Per-observation token counts live under
    # ``usageDetails.total`` (or ``usage.totalTokens``). We sum across all LLM
    # observations to derive the aggregate, which is the OPS-02 contract per
    # CONTEXT L-05 (the trace MUST capture total tokens — whether as a
    # precomputed field or derivable from observations).
    total_cost = trace.get("totalCost")
    assert total_cost is not None, f"totalCost missing on trace {trace.get('id')}"

    derived_total_tokens = 0
    for o in observations:
        usage_details = o.get("usageDetails") or {}
        if isinstance(usage_details, dict):
            t = usage_details.get("total")
            if isinstance(t, (int, float)):
                derived_total_tokens += int(t)
        # Fallback: some observations use the legacy ``usage.totalTokens`` shape.
        usage = o.get("usage") or {}
        if isinstance(usage, dict):
            t = usage.get("totalTokens")
            if isinstance(t, (int, float)) and derived_total_tokens == 0:
                derived_total_tokens += int(t)
    assert derived_total_tokens > 0, (
        f"No LLM observation reported token usage on trace {trace.get('id')} — "
        f"observations sampled: {[(o.get('name'), o.get('usageDetails')) for o in observations[:3]]}"
    )
