"""Graph topology + conditional edge tests.

Pure unit — no I/O, no LLM, no DB. Asserts the structure of the compiled
StateGraph and the singleton + Langfuse-graceful-skip contracts.
"""
from __future__ import annotations

import importlib

import pytest


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
