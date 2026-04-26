"""R-03 — 512/64 chunking + metadata summary prepend (Pitfall #11)."""
from __future__ import annotations

from datetime import date, datetime, timezone


def _make_record():
    from ingest.reports.schema import RawReport, ReportFields, StructuredReport

    raw = RawReport(
        source_name="reddit:r/striperfishing",
        source_url="https://reddit.com/r/striperfishing/comments/abc",
        original_author_handle="angler1",
        scrape_date=datetime.now(timezone.utc),
        post_date=date(2024, 10, 15),
        body=(
            "Caught a nice keeper at Barnegat last night. Bunker chunks on outgoing tide. "
            * 30
        ),  # ~1500 chars → should produce multiple chunks
    )
    fields = ReportFields(
        catch_quality="good_catch",
        species_mentioned=["striper"],
        water_body="Barnegat Bay",
        location_region="barnegat_bay",
        date=date(2024, 10, 15),
        bait_mentioned=["bunker chunks"],
        tide_phase="outgoing",
        confidence=0.9,
    )
    return StructuredReport(raw=raw, fields=fields)


def test_chunk_with_metadata_prepends_summary_to_first_chunk():
    from scripts.seed_reports import build_metadata_summary, chunk_with_metadata

    rec = _make_record()
    chunks = chunk_with_metadata(rec, report_id=0)
    assert len(chunks) >= 1
    summary = build_metadata_summary(rec)
    # The first chunk should contain the summary prefix (Pitfall #11)
    assert chunks[0][0].startswith(summary.split()[0])


def test_chunk_payload_has_all_d09_attribution_fields():
    from scripts.seed_reports import chunk_with_metadata

    rec = _make_record()
    chunks = chunk_with_metadata(rec, report_id=42)
    payload = chunks[0][1]
    for key in (
        "source_name",
        "source_url",
        "original_author_handle",
        "scrape_date",
        "species_mentioned",
        "location_region",
        "date",
        "metadata_summary",
        "bait_mentioned",
        "tide_phase_mentioned",
        "catch_quality",
        "report_id",
        "chunk_index",
    ):
        assert key in payload, f"missing payload key: {key}"
    assert payload["report_id"] == 42


def test_build_metadata_summary_includes_all_key_fields():
    from scripts.seed_reports import build_metadata_summary

    rec = _make_record()
    summary = build_metadata_summary(rec)
    assert "barnegat_bay" in summary.lower()
    assert "striper" in summary
    assert "outgoing" in summary
    assert "2024-10-15" in summary


def test_point_id_is_deterministic():
    from scripts.seed_reports import _point_id_for_chunk

    id1 = _point_id_for_chunk("same text", 1, 0)
    id2 = _point_id_for_chunk("same text", 1, 0)
    id3 = _point_id_for_chunk("different text", 1, 0)
    assert id1 == id2
    assert id1 != id3
    assert len(id1) == 32


def test_chunks_honor_512_token_bound_approximately():
    """RecursiveCharacterTextSplitter with tiktoken encoder respects token limits."""
    from scripts.seed_reports import chunk_with_metadata

    rec = _make_record()
    chunks = chunk_with_metadata(rec, report_id=0)
    # Sanity: no chunk is dramatically over 512 chars × ~4 chars/token headroom
    for chunk_text, _ in chunks:
        assert len(chunk_text) <= 4000  # generous upper bound
