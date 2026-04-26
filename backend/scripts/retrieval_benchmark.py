"""R-05 gate — Recall@5 ≥ 0.75 on 20 jargon-heavy NJ saltwater queries."""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from typing import Any

import yaml
from fastembed import SparseTextEmbedding
from openai import AsyncOpenAI
from qdrant_client.models import SparseVector

from app.config import settings
from qdrant.client import get_qdrant
from qdrant.retriever import hybrid_retrieve

log = logging.getLogger(__name__)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BENCHMARK_PATH = REPO_ROOT / "backend" / "rag" / "benchmark" / "jargon_queries.yaml"
RECALL_GATE = 0.75


async def run(assert_gate: bool = True) -> dict[str, Any]:
    if not BENCHMARK_PATH.exists():
        raise FileNotFoundError(f"Benchmark not curated: {BENCHMARK_PATH}")
    doc = yaml.safe_load(BENCHMARK_PATH.read_text())
    cases = doc.get("cases") if isinstance(doc, dict) else doc
    if not cases:
        raise ValueError(f"No cases found in {BENCHMARK_PATH}")
    client = get_qdrant()
    oa = AsyncOpenAI(api_key=settings.openai_api_key)
    sparse_embedder = SparseTextEmbedding("Qdrant/bm25")
    hits = 0
    details: list[dict] = []
    for case in cases:
        q = case["query"]
        expected = set(case["expected_report_ids"])
        species = case.get("species", "striper")
        loc = case.get("location_region")
        emb = await oa.embeddings.create(model="text-embedding-3-small", input=q)
        dense = emb.data[0].embedding
        sparse_raw = next(iter(sparse_embedder.embed([q])))
        sparse = SparseVector(
            indices=sparse_raw.indices.tolist(),
            values=sparse_raw.values.tolist(),
        )
        results = await hybrid_retrieve(
            client,
            dense,
            sparse,
            species=species,
            location_region=loc,
            top_k=5,
        )
        retrieved_ids = {r["payload"].get("report_id") for r in results}
        hit = bool(expected & retrieved_ids)
        hits += int(hit)
        details.append(
            {
                "query": q,
                "hit": hit,
                "retrieved": list(retrieved_ids)[:5],
                "expected": list(expected),
            }
        )
    recall = hits / len(cases) if cases else 0.0
    out = {"recall_at_5": recall, "hits": hits, "n": len(cases), "details": details}
    log.info("retrieval-benchmark recall@5=%.3f hits=%d/%d", recall, hits, len(cases))
    if assert_gate and recall < RECALL_GATE:
        raise AssertionError(f"Recall@5 {recall:.3f} < {RECALL_GATE} gate")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    result = asyncio.run(run(assert_gate=True))
    print(
        f"retrieval-benchmark recall@5={result['recall_at_5']:.3f} "
        f"hits={result['hits']}/{result['n']}"
    )
