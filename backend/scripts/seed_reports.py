"""Chunk + embed (dense + sparse) + upsert corpus.jsonl → Qdrant (R-03, R-04, R-05).

Idempotent per Pitfall #8: point IDs are sha256(report_id|chunk_index|chunk_text)
truncated — re-running overwrites rather than duplicating.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import pathlib
from typing import Iterable

from fastembed import SparseTextEmbedding
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import AsyncOpenAI
from qdrant_client.models import PointStruct, SparseVector

from app.config import settings
from ingest.reports.schema import StructuredReport
from qdrant.client import get_qdrant
from qdrant.schema import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    ensure_collection,
)

log = logging.getLogger(__name__)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / "data" / "structured_reports" / "corpus.jsonl"

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 96  # OpenAI batch limit-friendly


def build_metadata_summary(rec: StructuredReport) -> str:
    """Pitfall #11 — 2-3 sentence summary prepended to every chunk before embedding."""
    f = rec.fields
    r = rec.raw
    parts = [
        f"Date: {f.date.isoformat() if f.date else 'unknown'}.",
        f"Location: {f.location_region} ({f.water_body or 'water body unspecified'}).",
        f"Species: {', '.join(f.species_mentioned) or 'unspecified'}.",
        f"Tide phase: {f.tide_phase}.",
        f"Source: {r.source_name}.",
    ]
    return " ".join(parts)


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        model_name=EMBED_MODEL,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )


def chunk_with_metadata(rec: StructuredReport, report_id: int) -> list[tuple[str, dict]]:
    """Returns list of (chunk_text, payload) for every chunk of one report."""
    summary = build_metadata_summary(rec)
    full_text = summary + "\n\n" + rec.raw.body
    chunks = _splitter().split_text(full_text)
    r, f = rec.raw, rec.fields
    out: list[tuple[str, dict]] = []
    for i, chunk_text in enumerate(chunks):
        payload = {
            "report_id": report_id,
            "chunk_index": i,
            "date": f.date.isoformat() if f.date else None,
            "location_region": f.location_region,
            "water_body": f.water_body,
            "species_mentioned": list(f.species_mentioned),
            "source_name": r.source_name,
            "source_url": r.source_url,
            "source_description": r.source_description,
            "original_author_handle": r.original_author_handle,
            "scrape_date": r.scrape_date.isoformat(),
            "bait_mentioned": list(f.bait_mentioned),
            "tide_phase_mentioned": f.tide_phase,
            "catch_quality": f.catch_quality,
            "metadata_summary": summary,
            "text": chunk_text[:2000],
        }
        out.append((chunk_text, payload))
    return out


def _point_id_for_chunk(chunk_text: str, report_id: int, chunk_index: int) -> str:
    """Pitfall #8 — stable content-hash ID so re-runs overwrite."""
    h = hashlib.sha256(f"{report_id}|{chunk_index}|{chunk_text}".encode()).hexdigest()
    return h[:32]


def _batched(it: Iterable, n: int):
    batch: list = []
    for item in it:
        batch.append(item)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


async def seed() -> dict:
    if not CORPUS_PATH.exists():
        raise FileNotFoundError(f"{CORPUS_PATH} missing — run finalize_corpus first")
    client = get_qdrant()
    await ensure_collection(client)

    oa = AsyncOpenAI(api_key=settings.openai_api_key)
    sparse_embedder = SparseTextEmbedding("Qdrant/bm25")

    # Load all records (split('\n') for U+2028/2029 safety per 02-04 SUMMARY)
    records = [
        StructuredReport.model_validate_json(line)
        for line in CORPUS_PATH.read_text().split("\n")
        if line.strip()
    ]
    log.info("Loaded %d records from %s", len(records), CORPUS_PATH)

    # Flatten to (chunk_text, payload, point_id) triples
    triples: list[tuple[str, dict, str]] = []
    for i, rec in enumerate(records):
        for chunk_text, payload in chunk_with_metadata(rec, report_id=i):
            pid = _point_id_for_chunk(chunk_text, i, payload["chunk_index"])
            triples.append((chunk_text, payload, pid))
    log.info("Prepared %d chunks", len(triples))

    upserted = 0
    for batch in _batched(triples, EMBED_BATCH):
        texts = [t[0] for t in batch]
        # Dense embeddings
        dense_resp = await oa.embeddings.create(model=EMBED_MODEL, input=texts)
        dense_vecs = [d.embedding for d in dense_resp.data]
        # Sparse embeddings
        sparse_vecs = list(sparse_embedder.embed(texts))
        points = []
        for (chunk_text, payload, pid), dense, sparse in zip(batch, dense_vecs, sparse_vecs):
            points.append(
                PointStruct(
                    id=pid,
                    vector={
                        DENSE_VECTOR_NAME: dense,
                        SPARSE_VECTOR_NAME: SparseVector(
                            indices=sparse.indices.tolist(),
                            values=sparse.values.tolist(),
                        ),
                    },
                    payload=payload,
                )
            )
        await client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
        upserted += len(points)
        log.info("upserted %d / %d", upserted, len(triples))
    return {"reports": len(records), "chunks": len(triples), "upserted": upserted}


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    result = asyncio.run(seed())
    print(f"seed: reports={result['reports']}, chunks={result['chunks']}, upserted={result['upserted']}")
