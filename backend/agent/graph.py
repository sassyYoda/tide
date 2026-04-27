"""LangGraph 4-node StateGraph: Planner → Data Fetcher → RAG → Synthesizer.

CONTEXT L-01: 4 nodes; Critic deferred.
CONTEXT D-04.3: out-of-scope intent routes to END (no Synthesizer call).
CONTEXT L-02: stream_mode=["updates","custom"], version="v2" — set by caller.
CONTEXT L-03 / OPS-01: Langfuse v4.3.1 CallbackHandler attached at compile time
  IF LANGFUSE_SECRET_KEY is set; otherwise skip (development mode).

Edges:
    START → planner
    planner → END                    (when intent == 'out-of-scope')
    planner → data_fetcher           (otherwise)
    data_fetcher → rag_retriever
    rag_retriever → synthesizer
    synthesizer → END
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from agent.nodes.data_fetcher import data_fetcher_node
from agent.nodes.planner import planner_node
from agent.nodes.rag_retriever import rag_retriever_node
from agent.nodes.synthesizer import synthesizer_node
from agent.state import TideAgentState
from app.config import settings

log = logging.getLogger(__name__)

NODE_NAMES: tuple[str, ...] = (
    "planner", "data_fetcher", "rag_retriever", "synthesizer",
)


def _route_after_planner(state: TideAgentState) -> Literal["END", "continue"]:
    """Conditional edge: out-of-scope intent → END (no Synthesizer call)."""
    if state.get("intent") == "out-of-scope":
        return "END"
    return "continue"


def _maybe_get_langfuse_handler() -> Any | None:
    """Attach Langfuse only when keys are configured. L-03 + L-06.

    Langfuse v4.3.1's CallbackHandler reads LANGFUSE_HOST / LANGFUSE_SECRET_KEY /
    LANGFUSE_PUBLIC_KEY from env. We pre-check ``settings`` so we can log a
    clear "skipped" message in dev (where keys are intentionally unset until
    plan 03-06).
    """
    if not settings.langfuse_secret_key or not settings.langfuse_public_key:
        log.info("graph: LANGFUSE_*_KEY not set — skipping CallbackHandler")
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as e:  # noqa: BLE001
        log.warning("graph: failed to construct Langfuse CallbackHandler: %s", e)
        return None


def build_graph() -> Any:
    """Construct + compile the LangGraph; attach Langfuse callback if available."""
    builder: StateGraph = StateGraph(TideAgentState)
    # Indirection through this module's namespace so test monkeypatches on
    # ``agent.graph.<node>_node`` (rather than the source module) take effect
    # when ``build_graph`` is called after ``reset_for_test``.
    builder.add_node("planner", planner_node)
    builder.add_node("data_fetcher", data_fetcher_node)
    builder.add_node("rag_retriever", rag_retriever_node)
    builder.add_node("synthesizer", synthesizer_node)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges(
        "planner",
        _route_after_planner,
        {"END": END, "continue": "data_fetcher"},
    )
    builder.add_edge("data_fetcher", "rag_retriever")
    builder.add_edge("rag_retriever", "synthesizer")
    builder.add_edge("synthesizer", END)

    compiled = builder.compile()

    handler = _maybe_get_langfuse_handler()
    if handler is not None:
        compiled = compiled.with_config({"callbacks": [handler]})
        log.info("graph: Langfuse CallbackHandler attached")

    log.info("graph: compiled with %d nodes", len(NODE_NAMES))
    return compiled


# ─── Module-level singleton (mirrors qdrant.client.get_qdrant pattern) ──

_compiled: Any = None


def get_compiled_graph() -> Any:
    """Return the lazily-built compiled graph singleton."""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def reset_for_test() -> None:
    """Test hook — drop the compiled singleton so the next ``get_compiled_graph`` rebuilds.

    Required when tests monkeypatch ``agent.graph.<node>_node`` references; the
    pre-existing ``_compiled`` was bound to the original node callables and
    will not see the patched ones.
    """
    global _compiled
    _compiled = None


__all__ = [
    "NODE_NAMES",
    "build_graph",
    "get_compiled_graph",
    "reset_for_test",
    "_route_after_planner",
    "_maybe_get_langfuse_handler",
]
