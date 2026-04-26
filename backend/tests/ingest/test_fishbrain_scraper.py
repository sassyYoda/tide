"""FishBrain scraper — HTML parsing + DoS guard + A8 graceful fallback + dedupe."""
from __future__ import annotations

import json

import httpx
import pytest
import respx
from httpx import Response


SAMPLE_CATCH_HTML = """
<html><body>
  <div class="catch-body">Caught a 4lb tog on green crab at a jetty off IBSP.</div>
  <time datetime="2024-10-20T14:00:00">Oct 20</time>
  <span class="user-name">tog_master</span>
  <span class="species-name">tautog</span>
  <span class="lure-name">green crab</span>
</body></html>
"""

SAMPLE_INDEX_HTML = """
<html><body>
  <a href="/catches/12345">Catch 1</a>
  <a href="/catches/12346">Catch 2</a>
</body></html>
"""


def test_parse_catch_page_extracts_body_author_hints():
    from scripts.scrape_fishbrain import _parse_catch_page

    rec = _parse_catch_page(
        SAMPLE_CATCH_HTML, "https://fishbrain.com/catches/12345"
    )
    assert rec is not None
    assert "tog on green crab" in rec.body
    assert rec.original_author_handle == "tog_master"
    assert rec.post_date is not None
    assert rec.post_date.isoformat() == "2024-10-20"
    assert rec.ingest_notes["species_hint"] == "tautog"
    assert rec.ingest_notes["bait_hint"] == "green crab"
    assert rec.source_name == "fishbrain"
    assert rec.source_url == "https://fishbrain.com/catches/12345"


@pytest.mark.asyncio
@respx.mock
async def test_scrape_species_indexes_and_fetches_catches(monkeypatch):
    """Index page yields 2 catch links → both catch pages fetched and parsed."""
    from scripts import scrape_fishbrain

    # Bypass robots.txt + the 2.0s polite sleep to keep test fast
    monkeypatch.setattr(scrape_fishbrain, "_check_robots", lambda *_: True)
    monkeypatch.setattr(scrape_fishbrain, "_PER_DOMAIN_DELAY", 0.0)

    respx.get(
        "https://fishbrain.com/catches?species=tautog&location=new-jersey"
    ).mock(return_value=Response(200, text=SAMPLE_INDEX_HTML))
    respx.get(
        "https://fishbrain.com/catches?species=blackfish&location=new-jersey"
    ).mock(return_value=Response(200, text="<html><body></body></html>"))
    respx.get("https://fishbrain.com/catches/12345").mock(
        return_value=Response(200, text=SAMPLE_CATCH_HTML)
    )
    respx.get("https://fishbrain.com/catches/12346").mock(
        return_value=Response(200, text=SAMPLE_CATCH_HTML)
    )

    async with httpx.AsyncClient() as client:
        reports = await scrape_fishbrain.scrape_species(
            "tautog", client=client, max_per_species=3
        )

    assert len(reports) >= 2
    assert all(r.source_name == "fishbrain" for r in reports)
    assert all(r.source_url and r.source_url.startswith("https://fishbrain.com/") for r in reports)


@pytest.mark.asyncio
@respx.mock
async def test_scrape_species_returns_empty_when_selectors_miss(monkeypatch):
    """A8 fallback — if HTML structure changes and all selectors miss, return []."""
    from scripts import scrape_fishbrain

    monkeypatch.setattr(scrape_fishbrain, "_check_robots", lambda *_: True)
    monkeypatch.setattr(scrape_fishbrain, "_PER_DOMAIN_DELAY", 0.0)

    # Index page has no catch links at all → no catch pages fetched, no reports
    respx.get(
        "https://fishbrain.com/catches?species=tautog&location=new-jersey"
    ).mock(
        return_value=Response(
            200, text="<html><body><div>unrelated markup</div></body></html>"
        )
    )
    respx.get(
        "https://fishbrain.com/catches?species=blackfish&location=new-jersey"
    ).mock(return_value=Response(200, text="<html></html>"))

    async with httpx.AsyncClient() as client:
        reports = await scrape_fishbrain.scrape_species("tautog", client=client)

    assert reports == []


def test_finalize_corpus_dedupes_by_content_hash(tmp_path, monkeypatch):
    """Running finalize_corpus twice must not double-count subset records."""
    from scripts import finalize_corpus as fc

    monkeypatch.setattr(fc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fc, "RAW_DIR", tmp_path / "data" / "raw_reports")
    monkeypatch.setattr(fc, "STRUCT_DIR", tmp_path / "data" / "structured_reports")
    monkeypatch.setattr(
        fc, "SUBSET_PATH", tmp_path / "data" / "structured_reports" / "subset.jsonl"
    )
    monkeypatch.setattr(
        fc, "CORPUS_PATH", tmp_path / "data" / "structured_reports" / "corpus.jsonl"
    )
    fc.STRUCT_DIR.mkdir(parents=True)
    fc.RAW_DIR.mkdir(parents=True)

    subset_rec = {
        "raw": {
            "source_name": "njfishing.com",
            "source_url": "https://x/1",
            "scrape_date": "2024-10-20T00:00:00+00:00",
            "body": "hello",
        },
        "fields": {
            "catch_quality": "good_catch",
            "species_mentioned": ["striper"],
            "water_body": "Barnegat",
            "location_region": "barnegat_bay",
            "date": "2024-10-15",
            "bait_mentioned": [],
            "tide_phase": "outgoing",
            "confidence": 0.9,
        },
    }
    fc.SUBSET_PATH.write_text(json.dumps(subset_rec) + "\n")

    n1 = fc.main()
    n2 = fc.main()
    assert n1 == n2 == 1  # no duplication on second run
    # Corpus file matches subset content (no new raw → no extraction calls)
    assert fc.CORPUS_PATH.exists()
    lines = [line for line in fc.CORPUS_PATH.read_text().splitlines() if line.strip()]
    assert len(lines) == 1


def test_finalize_corpus_skips_raw_already_in_subset(tmp_path, monkeypatch):
    """Raw record matching a subset hash should not be re-extracted."""
    from scripts import finalize_corpus as fc

    monkeypatch.setattr(fc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fc, "RAW_DIR", tmp_path / "data" / "raw_reports")
    monkeypatch.setattr(fc, "STRUCT_DIR", tmp_path / "data" / "structured_reports")
    monkeypatch.setattr(
        fc, "SUBSET_PATH", tmp_path / "data" / "structured_reports" / "subset.jsonl"
    )
    monkeypatch.setattr(
        fc, "CORPUS_PATH", tmp_path / "data" / "structured_reports" / "corpus.jsonl"
    )
    fc.STRUCT_DIR.mkdir(parents=True)
    fc.RAW_DIR.mkdir(parents=True)

    # Subset record with known body+url+source_name
    body = "hello world striper bite"
    subset_rec = {
        "raw": {
            "source_name": "njfishing",
            "source_url": "https://x/1",
            "scrape_date": "2024-10-20T00:00:00+00:00",
            "body": body,
        },
        "fields": {
            "catch_quality": "good_catch",
            "species_mentioned": ["striper"],
            "water_body": "Barnegat",
            "location_region": "barnegat_bay",
            "date": "2024-10-15",
            "bait_mentioned": [],
            "tide_phase": "outgoing",
            "confidence": 0.9,
        },
    }
    fc.SUBSET_PATH.write_text(json.dumps(subset_rec) + "\n")

    # Raw file containing the SAME content → must be skipped before extract
    raw_rec = {
        "source_name": "njfishing",
        "source_url": "https://x/1",
        "scrape_date": "2024-10-20T00:00:00+00:00",
        "body": body,
        "ingest_notes": {},
    }
    (fc.RAW_DIR / "njfishing_dup.jsonl").write_text(json.dumps(raw_rec) + "\n")

    # Sentinel: if extract_fields.run is called, the test fails — dedupe should
    # prevent any new raw from reaching extraction.
    from scripts import extract_fields

    def _should_not_be_called(*_args, **_kwargs):
        raise AssertionError("extract_fields.run should not be called for duplicate raw")

    monkeypatch.setattr(extract_fields, "run", _should_not_be_called)

    n = fc.main()
    assert n == 1


def test_user_agent_default_does_not_require_app_config(monkeypatch):
    """Importing scrape_fishbrain must not require DATABASE_URL / OPENAI_API_KEY.

    Regression guard for the deviation that switched away from
    `from app.config import settings` (which fails at import time without
    a fully-populated env).
    """
    from scripts import scrape_fishbrain

    # Default UA falls through to the hardcoded literal when env unset
    monkeypatch.delenv("FISHBRAIN_USER_AGENT", raising=False)
    ua = scrape_fishbrain._user_agent()
    assert "Tide" in ua


def test_max_bytes_dos_guard_constants():
    """Threat T-02-04-04: DoS guard + per-domain delay must match plan spec."""
    from scripts import scrape_fishbrain

    assert scrape_fishbrain._MAX_BYTES == 2_000_000
    assert scrape_fishbrain._PER_DOMAIN_DELAY == 2.0
    assert set(scrape_fishbrain.TARGET_SPECIES.keys()) == {
        "tautog",
        "weakfish",
        "striper",
        "fluke",
        "bluefish",
    }
