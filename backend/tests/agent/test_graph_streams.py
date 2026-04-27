"""Integration test for runtime.iter_sse_events end-to-end.

Stubs the Planner and Synthesizer LLMs (via fixtures) and the Data Fetcher /
RAG Retriever node functions (via monkeypatch on ``agent.graph.<node>``) so
the graph runs deterministically without DB / Qdrant / network.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def patched_planner_chatmodel(stub_planner_llm, monkeypatch):
    """Belt-and-braces: also rebind ``agent.nodes.planner.ChatOpenAI`` to the stub.

    ``stub_planner_llm`` patches ``langchain_openai.ChatOpenAI``, which only
    works when ``agent.nodes.planner`` has not yet been imported (so its
    ``from langchain_openai import ChatOpenAI`` then resolves to the stub).
    Other agent tests (e.g. ``test_graph_topology.py``) cause
    ``agent.nodes.planner`` to be imported BEFORE the patch is installed, so
    its local binding stays on the real class. Re-bind explicitly.
    """
    import agent.nodes.planner as _planner_mod
    monkeypatch.setattr(_planner_mod, "ChatOpenAI", stub_planner_llm)
    yield stub_planner_llm


@pytest.fixture
def patched_synth_chatmodel(stub_synth_llm, monkeypatch):
    """Same isolation guard for the Synthesizer's ``ChatAnthropic`` binding."""
    import agent.nodes.synthesizer as _synth_mod
    monkeypatch.setattr(_synth_mod, "ChatAnthropic", stub_synth_llm)
    yield stub_synth_llm


@pytest.mark.asyncio
async def test_in_scope_full_pipeline(
    patched_planner_chatmodel,
    patched_synth_chatmodel,
    monkeypatch,
    lazy_models,
    lazy_spots,
):
    stub_planner_llm = patched_planner_chatmodel
    stub_synth_llm = patched_synth_chatmodel

    from agent.nodes.planner import (
        PlannerOutput,
        _reset_planner_llm_for_tests,
    )

    _reset_planner_llm_for_tests()

    # Planner: in-scope striper at Barnegat
    stub_planner_llm.next_response = PlannerOutput(
        intent="fishing-recommendation",
        species_canonical="striper",
        location_hint_raw="Barnegat",
        time_window_label="Saturday morning",
    )

    # Synthesizer LLM response — must contain a citation marker so
    # ``_extract_confidence_label`` and citation parsing succeed.
    class _Resp:
        content = (
            "Try Barnegat Inlet on the incoming tide [Report: NJF, 2026-04-22]. "
            "Confidence: Moderate"
        )

    stub_synth_llm.next_response = _Resp()

    # Stub Data Fetcher + RAG Retriever node refs in agent.graph so we don't
    # touch DB / Qdrant. These names are bound at import in agent.graph; a
    # subsequent reset_for_test() forces build_graph() to use them.
    async def _stub_data_fetcher(state):
        return {
            "spot_id": 1,
            "spot_name": "Barnegat Inlet",
            "spot_resolution_strategy": "fuzzy_name",
            "conditions": {"tide_phase": "incoming"},
            "ml_score": 0.78,
            "shap_top3": ["tide_phase"],
            "ml_score_available": True,
            "conditions_stale": False,
            "data_age_seconds": 60.0,
            "data_fetcher_latency_ms": 5.0,
        }

    async def _stub_rag(state):
        return {
            "chunks": [
                {
                    "chunk_id": "c1",
                    "text": "stripers running",
                    "source_name": "NJF",
                    "source_url": "https://x",
                    "title": "x",
                    "date": "2026-04-22",
                    "author": "x",
                    "score": 0.9,
                }
            ],
            "retrieval_ok": True,
            "rag_latency_ms": 10.0,
        }

    monkeypatch.setattr("agent.graph.data_fetcher_node", _stub_data_fetcher)
    monkeypatch.setattr("agent.graph.rag_retriever_node", _stub_rag)

    # Force graph rebuild so the patched node refs are bound into the compiled graph.
    from agent.graph import reset_for_test

    reset_for_test()

    from agent.runtime import iter_sse_events

    events: list = []
    async for ev_type, payload in iter_sse_events(
        {"query": "stripers at Barnegat?"}
    ):
        events.append((ev_type, payload))

    types = [t for t, _ in events]

    # Locked sequence: progress(planner), progress(data_fetcher),
    # partial_conditions, progress(rag_retriever), progress(synthesizer),
    # recommendation (no error in happy path).
    assert "recommendation" in types, f"got {types}"
    assert "partial_conditions" in types, f"got {types}"
    assert "error" not in types, f"got {types}"

    # Synthesizer recommendation must come after data_fetcher's partial_conditions.
    rec_idx = types.index("recommendation")
    pc_idx = types.index("partial_conditions")
    assert pc_idx < rec_idx

    # Verify recommendation payload shape.
    rec = next(p for t, p in events if t == "recommendation")
    assert "Barnegat" in rec.recommendation_text
    assert len(rec.citations) == 1
    assert rec.confidence_label in ("High", "Moderate", "Low")
    assert rec.spot_id == 1
    assert rec.retrieval_ok is True
    # W-1: rag_latency_ms surfaced for P-05 smoke gate
    assert rec.rag_latency_ms == 10.0

    # partial_conditions payload should expose conditions, ml_score, etc.
    pc = next(p for t, p in events if t == "partial_conditions")
    assert pc.spot_id == 1
    assert pc.spot_name == "Barnegat Inlet"
    assert pc.ml_score == 0.78
    assert pc.conditions_stale is False


@pytest.mark.asyncio
async def test_out_of_scope_short_circuits_to_error(patched_planner_chatmodel):
    stub_planner_llm = patched_planner_chatmodel
    from agent.nodes.planner import (
        PlannerOutput,
        _reset_planner_llm_for_tests,
    )

    _reset_planner_llm_for_tests()

    stub_planner_llm.next_response = PlannerOutput(
        intent="out-of-scope",
        reject_reason="non_nj_geo",
    )

    from agent.graph import reset_for_test

    reset_for_test()
    from agent.runtime import iter_sse_events

    events: list = []
    async for ev_type, payload in iter_sse_events({"query": "fishing in Maine"}):
        events.append((ev_type, payload))

    types = [t for t, _ in events]
    # Out-of-scope short-circuits BEFORE any progress emission — exactly one
    # error event with code planner_out_of_scope.
    assert "error" in types, f"got {types}"
    err = next(p for t, p in events if t == "error")
    assert err.code == "planner_out_of_scope"
    assert "NJ saltwater" in err.message
    # No data_fetcher / rag_retriever / synthesizer reached — assert via
    # progress stages.
    progress_stages = [p.stage for t, p in events if t == "progress"]
    assert "synthesizer" not in progress_stages
    assert "data_fetcher" not in progress_stages


@pytest.mark.asyncio
async def test_synthesizer_failure_yields_llm_unavailable(
    patched_planner_chatmodel,
    monkeypatch,
    lazy_models,
    lazy_spots,
):
    stub_planner_llm = patched_planner_chatmodel
    import anthropic

    from agent.nodes.planner import (
        PlannerOutput,
        _reset_planner_llm_for_tests,
    )

    _reset_planner_llm_for_tests()

    stub_planner_llm.next_response = PlannerOutput(
        intent="fishing-recommendation",
        species_canonical="striper",
        location_hint_raw="Barnegat",
    )

    async def _stub_data_fetcher(state):
        return {
            "spot_id": 1,
            "spot_name": "X",
            "spot_resolution_strategy": "fuzzy_name",
            "conditions": {},
            "ml_score_available": False,
            "conditions_stale": False,
            "data_fetcher_latency_ms": 1.0,
        }

    async def _stub_rag(state):
        return {"chunks": [], "retrieval_ok": True, "rag_latency_ms": 1.0}

    async def _failing_synth(state):
        # APIStatusError needs response/body; stub a minimal httpx.Response.
        import httpx
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        resp = httpx.Response(500, request=req)
        raise anthropic.APIStatusError(
            message="boom", response=resp, body=None
        )

    monkeypatch.setattr("agent.graph.data_fetcher_node", _stub_data_fetcher)
    monkeypatch.setattr("agent.graph.rag_retriever_node", _stub_rag)
    monkeypatch.setattr("agent.graph.synthesizer_node", _failing_synth)

    from agent.graph import reset_for_test

    reset_for_test()
    from agent.runtime import iter_sse_events

    events: list = []
    async for ev_type, payload in iter_sse_events({"query": "stripers"}):
        events.append((ev_type, payload))

    types = [t for t, _ in events]
    assert "error" in types, f"got {types}"
    err = next(p for t, p in events if t == "error")
    assert err.code == "llm_unavailable"
    # State up to synthesizer must be present in partial_state.
    assert err.partial_state is not None
    assert err.partial_state.get("species_canonical") == "striper"


def test_runtime_module_exports_reject_messages():
    from agent.runtime import REJECT_MESSAGES

    assert "non_nj_geo" in REJECT_MESSAGES
    assert "NJ saltwater" in REJECT_MESSAGES["non_nj_geo"]
    assert REJECT_MESSAGES["non_mvp_species"]
    assert REJECT_MESSAGES["non_fishing"]
