"""RAG Retriever node — cache-wrapped Qdrant hybrid search (A-04, A-08, P-05).

Pattern composition (PATTERNS.md → 03-PATTERNS.md rag_retriever):
1. Build dense embedding via OpenAI text-embedding-3-small.
2. Build sparse embedding via fastembed BM25 (matches scripts/retrieval_benchmark.py).
3. cache.rag.cache_key(species, location_region, query) → Redis lookup.
4. On miss: hybrid_retrieve(qdrant, dense, sparse, species, location_region) → top-5.
5. cache.rag.put_cached(...) on miss (TTL 1h handled inside cache.rag).
6. Map hybrid_retrieve dict result → RAGChunk TypedDict (whitelist of payload fields).

Graceful (A-08): wrap embed + retrieve in try/except for connection / API
failures → retrieval_ok=False, chunks=[], log warning. The Synthesizer reads
this flag and adjusts its prompt to "based on conditions only" caveat.

Self-contained Redis access: ``app.deps.redis.get_redis`` is a FastAPI
``Depends`` generator that cannot be invoked from a LangGraph node (no request
lifecycle), and no equivalent module-level helper exists. We open a
``redis.asyncio`` client inline from ``settings.redis_url`` and close it in a
``finally`` block — same pattern used by scripts/retrieval_benchmark.py.

W-1: ``rag_latency_ms`` is whitelisted on RecommendationPayload and asserted
by the plan 03-06 latency smoke test for the P-05 ≤800ms p95 gate.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from agent.state import RAGChunk, TideAgentState
from app.config import settings

log = logging.getLogger(__name__)

TOP_K = 5


# ─── Embedding helpers ──────────────────────────────────────────────────


async def _embed_dense(text: str) -> list[float]:
    """OpenAI text-embedding-3-small (1536 dims) — matches Phase 2 ingest path."""
    from openai import AsyncOpenAI

    oa = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await oa.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


_sparse_embedder: Any = None


def _get_sparse_embedder() -> Any:
    """Lazy fastembed BM25 singleton (model file cached on first call)."""
    global _sparse_embedder
    if _sparse_embedder is None:
        from fastembed import SparseTextEmbedding

        _sparse_embedder = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _sparse_embedder


def _embed_sparse(text: str) -> Any:
    """fastembed BM25 sparse embedding → qdrant SparseVector."""
    from qdrant_client.models import SparseVector

    embedder = _get_sparse_embedder()
    raw = next(iter(embedder.embed([text])))
    return SparseVector(indices=raw.indices.tolist(), values=raw.values.tolist())


# ─── ScoredPoint / dict → RAGChunk ──────────────────────────────────────


def _result_to_chunk(item: Any) -> RAGChunk:
    """Whitelist payload fields → RAGChunk TypedDict.

    ``hybrid_retrieve`` (Phase 2) returns ``list[dict]`` with shape
    ``{id, score_raw, score_adjusted, payload}``. We support both that dict
    shape and the raw ``ScoredPoint`` shape so the helper is robust to future
    return-type changes.
    """
    if isinstance(item, dict):
        payload = item.get("payload") or {}
        chunk_id = str(item.get("id", ""))
        score = float(item.get("score_adjusted", item.get("score_raw", 0.0)))
    else:
        payload = getattr(item, "payload", None) or {}
        chunk_id = str(getattr(item, "id", ""))
        score = float(getattr(item, "score", 0.0))

    return {
        "chunk_id": chunk_id,
        "text": payload.get("text") or payload.get("body") or "",
        "source_name": payload.get("source_name", "unknown"),
        "source_url": payload.get("source_url", ""),
        "title": payload.get("title", ""),
        "date": payload.get("date", ""),
        "author": payload.get("author", ""),
        "score": score,
    }


# ─── Node ───────────────────────────────────────────────────────────────


async def rag_retriever_node(state: TideAgentState) -> dict[str, Any]:
    """state.query + species_canonical + spot_name → top-5 chunks with provenance.

    Returns a state-update dict containing ``chunks``, ``retrieval_ok``,
    ``rag_latency_ms``. Never raises (A-08).
    """
    import redis.asyncio as redis_async

    from cache.rag import cache_key, get_cached, put_cached
    from qdrant.client import get_qdrant
    from qdrant.retriever import hybrid_retrieve

    t0 = time.perf_counter()
    query = state.get("query", "")
    species = state.get("species_canonical") or "striper"  # safe default; planner already validated
    location_region = state.get("spot_name")  # used as a coarse region filter

    if not query:
        log.warning("rag_retriever_node: empty query — skipping")
        return {"chunks": [], "retrieval_ok": True, "rag_latency_ms": 0.0}

    cache = await redis_async.from_url(settings.redis_url, decode_responses=False)
    try:
        # ─── Cache lookup ─────────────────────────────────────────────
        key = cache_key(species, location_region, query)
        try:
            cached = await get_cached(cache, key)
        except Exception as e:
            log.warning("rag_retriever_node: cache read failed: %s", e)
            cached = None

        if cached is not None:
            chunks_out: list[RAGChunk] = cached if isinstance(cached, list) else []
            return {
                "chunks": chunks_out[:TOP_K],
                "retrieval_ok": True,
                "rag_latency_ms": (time.perf_counter() - t0) * 1000.0,
            }

        # ─── Cold path — embed + retrieve ─────────────────────────────
        try:
            dense = await _embed_dense(query)
            sparse = _embed_sparse(query)
            client = get_qdrant()
            results = await hybrid_retrieve(
                client, dense, sparse, species, location_region
            )
            chunks: list[RAGChunk] = [
                _result_to_chunk(r) for r in (results or [])
            ][:TOP_K]
        except Exception as e:
            log.warning(
                "rag_retriever_node: retrieval failed → graceful (A-08): %s", e
            )
            return {
                "chunks": [],
                "retrieval_ok": False,
                "rag_latency_ms": (time.perf_counter() - t0) * 1000.0,
            }

        # ─── Best-effort cache write ──────────────────────────────────
        try:
            await put_cached(cache, key, chunks)
        except Exception as e:
            log.warning("rag_retriever_node: cache write failed (non-fatal): %s", e)

        return {
            "chunks": chunks,
            "retrieval_ok": True,
            "rag_latency_ms": (time.perf_counter() - t0) * 1000.0,
        }
    finally:
        await cache.aclose()


__all__ = ["rag_retriever_node", "TOP_K"]
