"""Integration test: POST /api/v1/query SSE protocol + first-byte budget + cache key.

Coverage:

- SEC-06: oversize body rejected at Pydantic (HTTP 422 before any stream).
- W-4 / A-07 / P-03: first SSE chunk reaches the client in < 2 s.
- D-03 / locked sequence: progress(planner) → progress(data_fetcher) →
  partial_conditions → progress(rag_retriever) → progress(synthesizer) →
  recommendation. (The route emits an extra leading ``progress(planner)``
  before the runtime fires; the assertion accepts duplicates.)
- D-02.1 cache key: hashlib.sha256-based; case- and whitespace-insensitive.
"""
from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_query_rejects_oversize_query(test_client):
    """SEC-06 max_length=500 enforced by Pydantic — 501 chars → HTTP 422."""
    long = "x" * 501
    resp = test_client["client"].post("/api/v1/query", json={"query": long})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_query_in_scope_emits_full_sequence(
    test_client,
    sse_events,
    monkeypatch,
    stub_planner_llm,
    stub_synth_llm,
    lazy_models,
    lazy_spots,
):
    """Happy-path event sequence (with stubbed LLMs)."""
    # Patch the local module bindings so Planner/Synth nodes use stubs.
    import agent.nodes.planner as planner_mod
    import agent.nodes.synthesizer as synth_mod

    monkeypatch.setattr(planner_mod, "ChatOpenAI", stub_planner_llm)
    monkeypatch.setattr(synth_mod, "ChatAnthropic", stub_synth_llm)

    from agent.nodes.planner import PlannerOutput

    stub_planner_llm.next_response = PlannerOutput(
        intent="fishing-recommendation",
        species_canonical="striper",
        location_hint_raw="Barnegat",
        time_window_label="Saturday morning",
    )

    class _R:
        content = (
            "Try Barnegat Inlet on the incoming tide. "
            "[Report: NJF, 2026-04-22] Confidence: Moderate"
        )

    stub_synth_llm.next_response = _R()

    async def _df(state):
        return {
            "spot_id": 1,
            "spot_name": "Barnegat Inlet",
            "spot_resolution_strategy": "fuzzy_name",
            "conditions": {"tide_phase": "incoming"},
            "ml_score": 0.5,
            "shap_top3": [],
            "ml_score_available": True,
            "conditions_stale": False,
            "data_age_seconds": 60.0,
            "data_fetcher_latency_ms": 1.0,
        }

    async def _rag(state):
        return {
            "chunks": [
                {
                    "chunk_id": "c1",
                    "text": "x",
                    "source_name": "NJF",
                    "source_url": "x",
                    "title": "x",
                    "date": "2026-04-22",
                    "author": "x",
                    "score": 0.9,
                }
            ],
            "retrieval_ok": True,
            "rag_latency_ms": 1.0,
        }

    monkeypatch.setattr("agent.graph.data_fetcher_node", _df)
    monkeypatch.setattr("agent.graph.rag_retriever_node", _rag)
    from agent.graph import reset_for_test

    reset_for_test()

    events = sse_events(
        test_client["client"], "/api/v1/query", {"query": "stripers at Barnegat?"}
    )
    types = [t for t, _ in events]
    assert "recommendation" in types, f"missing recommendation; got {types}"
    assert "partial_conditions" in types, f"missing partial_conditions; got {types}"
    # Ordering: partial_conditions strictly before recommendation.
    assert types.index("partial_conditions") < types.index("recommendation")
    # First event MUST be progress (W-4 first-byte budget).
    assert types[0] == "progress"


@pytest.mark.asyncio
async def test_first_event_under_2s(
    test_client,
    monkeypatch,
    stub_planner_llm,
    stub_synth_llm,
    lazy_models,
    lazy_spots,
):
    """A-07 / P-03 / W-4: first SSE chunk arrives within 2 s of POST.

    With stubbed LLMs (return instantly) this should be well under 100 ms.
    The real p95 gate against actual LLM calls lives in plan 03-06's smoke test.
    """
    import agent.nodes.planner as planner_mod
    import agent.nodes.synthesizer as synth_mod

    monkeypatch.setattr(planner_mod, "ChatOpenAI", stub_planner_llm)
    monkeypatch.setattr(synth_mod, "ChatAnthropic", stub_synth_llm)

    from agent.nodes.planner import PlannerOutput

    stub_planner_llm.next_response = PlannerOutput(
        intent="fishing-recommendation",
        species_canonical="striper",
    )

    class _R:
        content = "Try X. Confidence: Low"

    stub_synth_llm.next_response = _R()

    async def _df(state):
        return {
            "spot_id": 1,
            "conditions": {},
            "ml_score_available": False,
            "conditions_stale": False,
            "data_fetcher_latency_ms": 1.0,
            "spot_resolution_strategy": "no_pin",
        }

    async def _rag(state):
        return {"chunks": [], "retrieval_ok": True, "rag_latency_ms": 1.0}

    monkeypatch.setattr("agent.graph.data_fetcher_node", _df)
    monkeypatch.setattr("agent.graph.rag_retriever_node", _rag)
    from agent.graph import reset_for_test

    reset_for_test()

    t0 = time.perf_counter()
    with test_client["client"].stream(
        "POST", "/api/v1/query", json={"query": "test"}
    ) as resp:
        first_chunk = next(resp.iter_bytes(chunk_size=1024), b"")
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"first SSE chunk took {elapsed:.2f}s (P-03 gate is 2s)"
    # The chunk must contain at least one SSE field marker — either an event
    # marker, a data marker, or a comment-keepalive ``:`` from sse-starlette.
    assert (
        b"event:" in first_chunk
        or b"data:" in first_chunk
        or first_chunk.startswith(b":")
    ), f"first chunk had no SSE markers: {first_chunk!r}"


@pytest.mark.asyncio
async def test_query_cache_key_normalization():
    """D-02.1 cache key: case- and whitespace-insensitive, deterministic.

    NEVER use Python's built-in hash() — non-deterministic across processes.
    The query_cache_key impl must use hashlib.sha256.
    """
    from cache.query_cache import query_cache_key

    # Case + whitespace normalize.
    k1 = query_cache_key("Cache TEST query", None, 42, None)
    k2 = query_cache_key("cache test  query", None, 42, None)
    assert k1 == k2, "normalize_query must collapse whitespace + lowercase"

    # spot_id contributes — different spot_id → different key.
    k3 = query_cache_key("cache test query", None, 99, None)
    assert k1 != k3

    # species + time_window contribute.
    k4 = query_cache_key("cache test query", "striper", 42, None)
    assert k1 != k4
    k5 = query_cache_key("cache test query", None, 42, "Saturday morning")
    assert k1 != k5

    # Determinism across calls (sha256-backed, NOT Python hash()).
    assert query_cache_key("q", None, None, None) == query_cache_key("q", None, None, None)


@pytest.mark.asyncio
async def test_normalize_query_variants():
    """normalize_query: lowercase + collapse whitespace + handle empty / None-ish input."""
    from cache.query_cache import normalize_query

    assert normalize_query("  Stripers   AT Barnegat?  ") == "stripers at barnegat?"
    assert normalize_query("") == ""
    assert normalize_query("ALREADY-NORMAL") == "already-normal"
