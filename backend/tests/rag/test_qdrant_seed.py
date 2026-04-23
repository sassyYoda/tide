"""Stub — R-01/R-04/R-05 Qdrant collection seed + payload schema. Implemented in Plan 06."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 06"),
    pytest.mark.integration,
]


def test_collection_exists_with_dense_and_sparse_vectors():
    """Plan 06: fishing_reports has text-embedding-3-small (1536d) + BM25 sparse."""
    assert False, "Not implemented"


def test_payload_has_attribution_fields():
    """Plan 06 (D-09): payload has source_name, source_url or source_description, original_author_handle, scrape_date."""
    assert False, "Not implemented"


def test_upsert_is_idempotent():
    """Plan 06: re-seeding the same chunks does not duplicate rows."""
    assert False, "Not implemented"
