"""Graph topology + conditional edge tests.

Pure unit — no I/O, no LLM, no DB. Asserts the structure of the compiled
StateGraph and the singleton + Langfuse-graceful-skip contracts.
"""
from __future__ import annotations

import importlib



def test_node_names_exact():
    from agent.graph import NODE_NAMES
    assert NODE_NAMES == ("planner", "data_fetcher", "rag_retriever", "synthesizer")


def test_route_after_planner_out_of_scope():
    from agent.graph import _route_after_planner
    assert _route_after_planner({"intent": "out-of-scope"}) == "END"
    assert _route_after_planner(
        {"intent": "out-of-scope", "reject_reason": "non_nj_geo"}
    ) == "END"


def test_route_after_planner_in_scope():
    from agent.graph import _route_after_planner
    assert _route_after_planner({"intent": "fishing-recommendation"}) == "continue"


def test_route_after_planner_missing_intent_continues():
    """Defensive default — if intent missing, continue (downstream nodes handle gracefully)."""
    from agent.graph import _route_after_planner
    assert _route_after_planner({}) == "continue"


def test_build_graph_has_all_nodes():
    from agent.graph import NODE_NAMES, build_graph, reset_for_test

    reset_for_test()
    g = build_graph()
    nodes = g.get_graph().nodes
    for name in NODE_NAMES:
        assert name in nodes, f"node {name!r} missing from compiled graph"


def test_get_compiled_graph_is_singleton():
    from agent.graph import get_compiled_graph, reset_for_test

    reset_for_test()
    g1 = get_compiled_graph()
    g2 = get_compiled_graph()
    assert g1 is g2


def test_no_langfuse_handler_when_keys_empty(monkeypatch):
    """L-06: graceful skip when keys are not provided."""
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    # Re-read settings + graph module so the env-changes apply.
    import app.config as cfg
    importlib.reload(cfg)
    import agent.graph as gmod
    importlib.reload(gmod)
    assert gmod._maybe_get_langfuse_handler() is None


# ─── OPS-01 unit-test extension (Phase 5, plan 05-01) ────────────────────
#
# Verifies that ``_maybe_get_langfuse_handler`` returns the Langfuse
# CallbackHandler when both env keys are configured, and ``None`` when they
# are unset. Replaces what would otherwise be an end-to-end OPS-01 check
# against the live Langfuse SaaS — the integration shape is exercised
# separately in ``tests/agent/test_langfuse_trace_shape.py`` (Wave 3).


def test_langfuse_callback_attached_when_keys_set(monkeypatch, caplog):
    """OPS-01: handler returned when LANGFUSE_*_KEY env keys are set."""
    import langfuse.langchain as lf_mod

    from agent.graph import _maybe_get_langfuse_handler, reset_for_test
    from app.config import settings

    reset_for_test()
    monkeypatch.setattr(settings, "langfuse_secret_key", "test-secret")
    monkeypatch.setattr(settings, "langfuse_public_key", "test-public")

    sentinel = object()
    monkeypatch.setattr(lf_mod, "CallbackHandler", lambda: sentinel)

    with caplog.at_level("INFO"):
        handler = _maybe_get_langfuse_handler()
    assert handler is sentinel
    reset_for_test()


def test_langfuse_callback_skipped_when_keys_unset(monkeypatch, caplog):
    """OPS-01: handler is None + skip log emitted when keys are empty."""
    from agent.graph import _maybe_get_langfuse_handler, reset_for_test
    from app.config import settings

    reset_for_test()
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    monkeypatch.setattr(settings, "langfuse_public_key", "")

    with caplog.at_level("INFO"):
        handler = _maybe_get_langfuse_handler()
    assert handler is None
    assert "skipping CallbackHandler" in caplog.text
    reset_for_test()
