"""Stub — R-04/R-07/R-09 hybrid RRF + species/recency filter + BM25. Implemented in Plan 06."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 06"),
    pytest.mark.integration,
]


def test_rrf_fusion_combines_dense_and_sparse():
    """Plan 06: Qdrant prefetch + FusionQuery(Fusion.RRF) returns fused rank."""
    assert False, "Not implemented"


def test_species_filter_rejects_non_matching_chunks():
    """Plan 06 (R-07): species-match filter prunes cross-species chunks pre-fusion."""
    assert False, "Not implemented"


def test_bm25_sparse_vector_scores_jargon_queries():
    """Plan 06 (R-09): sparse BM25 vector recovers bait/lure keyword matches."""
    assert False, "Not implemented"
