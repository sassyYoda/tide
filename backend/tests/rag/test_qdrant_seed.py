"""R-01 + R-04 + R-05 — Qdrant collection schema (dense 1536 + BM25 sparse IDF)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_collection_dense_dim_1536(qdrant_client):
    from qdrant.schema import COLLECTION_NAME, DENSE_DIM, ensure_collection

    await ensure_collection(qdrant_client)
    info = await qdrant_client.get_collection(collection_name=COLLECTION_NAME)
    dense_cfg = info.config.params.vectors["dense"]
    assert dense_cfg.size == DENSE_DIM == 1536


@pytest.mark.asyncio
async def test_collection_has_sparse_bm25_with_idf(qdrant_client):
    from qdrant.schema import COLLECTION_NAME, ensure_collection

    await ensure_collection(qdrant_client)
    info = await qdrant_client.get_collection(collection_name=COLLECTION_NAME)
    sparse_cfg = info.config.params.sparse_vectors["bm25"]
    # Modifier.IDF is the expected config
    assert sparse_cfg.modifier is not None
