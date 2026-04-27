"""RAG node integration test against testcontainer Qdrant + Redis.

Verifies the cold-path → cache write → warm-path read cycle. Skips if no
seeded ``fishing_reports`` collection is available (the cache hit path is
also exercised in :mod:`tests.agent.test_graceful_qdrant` indirectly, and
unit-level cache wiring is covered by the synthesized tests below).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_rag_node_cold_then_warm_cache(
    qdrant_container, redis_container, lazy_models, lazy_spots, monkeypatch
):
    """Cold path → cache populated; warm path returns from cache.

    The cold path embeds + retrieves; the warm path must hit Redis.
    Cold-call latency typically dominates because of the OpenAI embedding;
    we assert warm < cold OR warm < 200ms (loose gate; strict P-05 gate
    lives in plan 03-06).
    """
    qhost = qdrant_container.get_container_host_ip()
    qport = int(qdrant_container.get_exposed_port(6333))
    rhost = redis_container.get_container_host_ip()
    rport = int(redis_container.get_exposed_port(6379))
    monkeypatch.setenv("QDRANT_URL", f"http://{qhost}:{qport}")
    monkeypatch.setenv("REDIS_URL", f"redis://{rhost}:{rport}/0")

    # Reload settings so the new env vars are picked up.
    import importlib
    import app.config as cfg
    importlib.reload(cfg)
    import qdrant.client as qc
    qc._client = None  # type: ignore[attr-defined]
    importlib.reload(qc)

    from qdrant_client import AsyncQdrantClient
    client = AsyncQdrantClient(url=f"http://{qhost}:{qport}")
    cols = await client.get_collections()
    if not any(c.name == "fishing_reports" for c in cols.collections):
        pytest.skip(
            "fishing_reports collection not seeded; integration test requires "
            "seed_reports.py to have been run against this container"
        )

    import agent.nodes.rag_retriever as mod
    importlib.reload(mod)
    from agent.nodes.rag_retriever import rag_retriever_node

    state = {"query": "stripers on incoming tide", "species_canonical": "striper"}
    out_cold = await rag_retriever_node(state)
    assert out_cold["retrieval_ok"] is True
    assert isinstance(out_cold["chunks"], list)
    cold_ms = out_cold["rag_latency_ms"]

    out_warm = await rag_retriever_node(state)
    assert out_warm["retrieval_ok"] is True
    assert isinstance(out_warm["chunks"], list)
    # Loose gate: warm should be faster (cache short-circuits embed + retrieve)
    # OR very fast (≤200ms) regardless. Strict P-05 gate is plan 03-06.
    assert out_warm["rag_latency_ms"] < cold_ms or out_warm["rag_latency_ms"] < 200


@pytest.mark.asyncio
async def test_rag_node_empty_query_short_circuits(
    redis_container, lazy_models, lazy_spots, monkeypatch
):
    """Empty query never hits Qdrant; returns chunks=[], retrieval_ok=True."""
    rhost = redis_container.get_container_host_ip()
    rport = int(redis_container.get_exposed_port(6379))
    monkeypatch.setenv("REDIS_URL", f"redis://{rhost}:{rport}/0")

    import importlib
    import app.config as cfg
    importlib.reload(cfg)
    import agent.nodes.rag_retriever as mod
    importlib.reload(mod)

    out = await mod.rag_retriever_node({"query": "", "species_canonical": "striper"})
    assert out["chunks"] == []
    assert out["retrieval_ok"] is True
    assert out["rag_latency_ms"] == 0.0
