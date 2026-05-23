"""OPS-02 integration test — Langfuse trace captures all 4 LangGraph node spans.

Wave 3 (plan 05-04) implements the end-to-end check: with real Langfuse
credentials in env, run one query through ``POST /api/v1/query``, fetch the
resulting trace via the Langfuse public API, and assert it has 4 spans
(planner, data_fetcher, rag_retriever, synthesizer) plus per-node prompt /
output captures.

Wave 0 (this file) ships a RED SKELETON so plan 05-04 can fill it without
inventing the file.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Wave 3 — landed via 05-04-PLAN")
def test_trace_captures_4_node_spans():
    """OPS-02: one /api/v1/query call produces 4 per-node spans in Langfuse.

    Wave 3: ensure LANGFUSE_*_KEY env present, drive one query, poll the
    Langfuse public API for the trace, assert spans for planner +
    data_fetcher + rag_retriever + synthesizer all present.
    """
    pass
