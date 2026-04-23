"""Stub — R-03 report body chunking (512/64 RecursiveCharacterTextSplitter). Implemented in Plan 06."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 06")


def test_chunk_size_512_tokens_with_64_overlap():
    """Plan 06: LangChain RecursiveCharacterTextSplitter chunk_size=512, overlap=64."""
    assert False, "Not implemented"


def test_chunker_preserves_report_metadata():
    """Plan 06: each chunk inherits source_name, date, author from parent report."""
    assert False, "Not implemented"
