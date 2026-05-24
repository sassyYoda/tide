"""R-06 / R-07 / R-09 — RRF fusion + filters + provenance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from qdrant_client.models import PointStruct, SparseVector

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_filter_builder_pre_filters_on_species_and_date_only():
    """The Qdrant pre-filter applies species + date hard cuts but NOT location.

    Historical contract included a strict location_region MatchValue, but in
    production it never matched (data_fetcher passes spot_name like
    "Manasquan Inlet — North Jetty" while seeded chunks tag location_region
    with a slug like "manasquan"). Vectors handle location semantics — the
    filter only enforces species + recency.
    """
    from qdrant.retriever import _build_filter

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    f = _build_filter("striper", "barnegat_bay", cutoff)
    keys = {cond.key for cond in f.must}
    assert keys == {"species_mentioned", "date"}


@pytest.mark.asyncio
async def test_filter_builder_ignores_location_when_none():
    from qdrant.retriever import _build_filter

    now = datetime.now(timezone.utc)
    f = _build_filter("striper", None, now - timedelta(days=30))
    keys = {cond.key for cond in f.must}
    assert "location_region" not in keys


@pytest.mark.asyncio
async def test_hybrid_retrieve_applies_species_filter(qdrant_client):
    """Seed 2 docs (one striper, one bluefish); query with species=striper; expect only 1 hit."""
    from qdrant.retriever import hybrid_retrieve
    from qdrant.schema import (
        COLLECTION_NAME,
        DENSE_DIM,
        DENSE_VECTOR_NAME,
        SPARSE_VECTOR_NAME,
        ensure_collection,
    )

    await ensure_collection(qdrant_client)
    now = datetime.now(timezone.utc)
    recent_iso = (now - timedelta(hours=5)).isoformat()

    # Construct deterministic dense vectors + sparse vectors
    dense_a = [0.1] * DENSE_DIM
    dense_b = [0.2] * DENSE_DIM
    sparse = SparseVector(indices=[1, 2, 3], values=[1.0, 0.5, 0.25])

    await qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=1,
                vector={DENSE_VECTOR_NAME: dense_a, SPARSE_VECTOR_NAME: sparse},
                payload={
                    "species_mentioned": ["striper"],
                    "location_region": "barnegat_bay",
                    "date": recent_iso,
                    "source_name": "reddit:r/striperfishing",
                    "source_url": "https://x/1",
                    "metadata_summary": "striper at Barnegat",
                },
            ),
            PointStruct(
                id=2,
                vector={DENSE_VECTOR_NAME: dense_b, SPARSE_VECTOR_NAME: sparse},
                payload={
                    "species_mentioned": ["bluefish"],
                    "location_region": "barnegat_bay",
                    "date": recent_iso,
                    "source_name": "reddit:r/SurfFishing",
                    "source_url": "https://x/2",
                    "metadata_summary": "blues at Barnegat",
                },
            ),
        ],
        wait=True,
    )
    results = await hybrid_retrieve(
        qdrant_client,
        dense_a,
        sparse,
        species="striper",
        location_region="barnegat_bay",
        top_k=5,
        now=now,
    )
    assert len(results) == 1
    assert results[0]["payload"]["species_mentioned"] == ["striper"]


@pytest.mark.asyncio
async def test_hybrid_retrieve_top_k_returns_provenance_fields(qdrant_client):
    """R-09 — every result must have source_name, source_url, date, species_mentioned."""
    from qdrant.retriever import hybrid_retrieve
    from qdrant.schema import (
        COLLECTION_NAME,
        DENSE_DIM,
        DENSE_VECTOR_NAME,
        SPARSE_VECTOR_NAME,
        ensure_collection,
    )

    await ensure_collection(qdrant_client)

    now = datetime.now(timezone.utc)
    recent_iso = (now - timedelta(hours=12)).isoformat()
    dense = [0.1] * DENSE_DIM
    sparse = SparseVector(indices=[1], values=[1.0])

    await qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=i,
                vector={DENSE_VECTOR_NAME: dense, SPARSE_VECTOR_NAME: sparse},
                payload={
                    "species_mentioned": ["striper"],
                    "location_region": "barnegat_bay",
                    "date": recent_iso,
                    "source_name": "reddit:r/striperfishing",
                    "source_url": f"https://x/{i}",
                    "original_author_handle": f"user{i}",
                    "scrape_date": now.isoformat(),
                    "metadata_summary": "summary",
                },
            )
            for i in range(1, 8)
        ],
        wait=True,
    )
    results = await hybrid_retrieve(
        qdrant_client, dense, sparse, species="striper", top_k=5, now=now
    )
    assert len(results) == 5
    for r in results:
        p = r["payload"]
        assert "source_name" in p
        assert "source_url" in p
        assert "date" in p
        assert "species_mentioned" in p


@pytest.mark.asyncio
async def test_hybrid_retrieve_excludes_older_than_30d(qdrant_client):
    """R-07 — date > now - 30 days filter."""
    from qdrant.retriever import hybrid_retrieve
    from qdrant.schema import (
        COLLECTION_NAME,
        DENSE_DIM,
        DENSE_VECTOR_NAME,
        SPARSE_VECTOR_NAME,
        ensure_collection,
    )

    await ensure_collection(qdrant_client)

    now = datetime.now(timezone.utc)
    old_iso = (now - timedelta(days=60)).isoformat()
    dense = [0.1] * DENSE_DIM
    sparse = SparseVector(indices=[1], values=[1.0])
    await qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=1,
                vector={DENSE_VECTOR_NAME: dense, SPARSE_VECTOR_NAME: sparse},
                payload={
                    "species_mentioned": ["striper"],
                    "location_region": "barnegat_bay",
                    "date": old_iso,
                    "source_name": "old",
                    "source_url": "https://old/1",
                },
            ),
        ],
        wait=True,
    )
    results = await hybrid_retrieve(
        qdrant_client, dense, sparse, species="striper", top_k=5, now=now
    )
    assert results == []
