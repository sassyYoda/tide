"""Stub — R-05 Recall@5 ≥ 0.75 on 20-query jargon benchmark. Implemented in Plan 06."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 06"),
    pytest.mark.integration,
    pytest.mark.slow,
]


def test_collection_has_at_least_500_reports():
    """Plan 06: fishing_reports collection size ≥ 500 chunked reports (R-01)."""
    assert False, "Not implemented"


def test_recall_at_5_above_threshold():
    """Plan 06: Recall@5 ≥ 0.75 on eval/retrieval_benchmark.json queries."""
    assert False, "Not implemented"
