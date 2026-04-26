"""Qdrant `fishing_reports` collection bootstrap (R-04, R-05).

Idempotent — uses get_collections + create_collection only when absent.
NEVER use the destructive re-create variant (Pitfall #5 — silently wipes data).
"""
from __future__ import annotations

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, Modifier, SparseVectorParams, VectorParams

log = logging.getLogger(__name__)

COLLECTION_NAME = "fishing_reports"
DENSE_DIM = 1536  # text-embedding-3-small
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "bm25"


async def ensure_collection(client: AsyncQdrantClient) -> bool:
    """Create if absent. Returns True if created, False if already existed."""
    existing = {c.name for c in (await client.get_collections()).collections}
    if COLLECTION_NAME in existing:
        log.info("qdrant collection %s already exists", COLLECTION_NAME)
        return False
    await client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            DENSE_VECTOR_NAME: VectorParams(size=DENSE_DIM, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF),
        },
    )
    log.info("qdrant collection %s created", COLLECTION_NAME)
    return True


__all__ = [
    "COLLECTION_NAME",
    "DENSE_DIM",
    "DENSE_VECTOR_NAME",
    "SPARSE_VECTOR_NAME",
    "ensure_collection",
]
