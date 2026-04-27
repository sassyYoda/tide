"""A-08: Qdrant unreachable → retrieval_ok=False, chunks=[], no raise.

Wave 2 / plan 03-03 / Rule 1 - Bug guarded.

The node must NOT raise when Qdrant is unreachable. Instead it logs a
warning and emits a graceful state update (retrieval_ok=False, chunks=[])
so the Synthesizer can produce a "based on conditions only" response.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_qdrant_unreachable_returns_graceful(
    monkeypatch, redis_container, lazy_models, lazy_spots
):
    """Point QDRANT_URL at a closed port; node MUST NOT raise."""
    rhost = redis_container.get_container_host_ip()
    rport = int(redis_container.get_exposed_port(6379))
    # 127.0.0.1:1 is the canonical "definitely closed" port; fast TCP refusal
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("REDIS_URL", f"redis://{rhost}:{rport}/0")

    # Force a fresh qdrant client + settings so the closed-port URL is used.
    import importlib
    import app.config as cfg
    importlib.reload(cfg)
    import qdrant.client as qc
    qc._client = None  # type: ignore[attr-defined]
    importlib.reload(qc)
    import agent.nodes.rag_retriever as mod
    importlib.reload(mod)

    from agent.nodes.rag_retriever import rag_retriever_node
    out = await rag_retriever_node({"query": "stripers", "species_canonical": "striper"})

    assert out["retrieval_ok"] is False
    assert out["chunks"] == []
    assert out["rag_latency_ms"] >= 0
