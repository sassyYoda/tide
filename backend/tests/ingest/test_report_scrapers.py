"""Report-scraper unit tests (respx-mocked HTTP, no real network)."""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from ingest.reports.schema import RawReport


SAMPLE_FORUM_HTML = """
<html><body>
  <div class="post-body">Good striper bite at Barnegat last night on bunker chunks.</div>
  <time datetime="2024-10-15T18:00:00"></time>
  <span class="username">joe_angler</span>
</body></html>
"""


@pytest.mark.asyncio
@respx.mock
async def test_forum_scraper_parses_body_date_author():
    from scripts.scrape_forum import scrape_source
    import httpx

    respx.get("https://njfishing.com/robots.txt").mock(return_value=Response(200, text="User-agent: *\nAllow: /"))
    respx.get("https://njfishing.com/thread/1").mock(return_value=Response(200, text=SAMPLE_FORUM_HTML))

    async with httpx.AsyncClient() as client:
        reports = await scrape_source("njfishing", ["/thread/1"], client=client)

    assert len(reports) == 1
    r = reports[0]
    assert "Barnegat" in r.body
    assert r.original_author_handle == "joe_angler"
    assert r.post_date is not None
    assert r.source_url == "https://njfishing.com/thread/1"


@pytest.mark.asyncio
@respx.mock
async def test_forum_scraper_honors_robots_disallow():
    from scripts.scrape_forum import scrape_source
    import httpx

    respx.get("https://njfishing.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: Tide/0.1\nDisallow: /thread/")
    )
    async with httpx.AsyncClient() as client:
        reports = await scrape_source("njfishing", ["/thread/1"], client=client)

    assert reports == []


@pytest.mark.asyncio
@respx.mock
async def test_forum_scraper_rejects_oversized_body():
    from scripts.scrape_forum import _fetch, _MAX_BYTES
    import httpx

    big = "x" * (_MAX_BYTES + 1)
    respx.get("https://njfishing.com/huge").mock(
        return_value=Response(200, text=big, headers={"content-length": str(len(big))})
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="> 2000000 bytes"):
            await _fetch(client, "https://njfishing.com/huge")


def test_raw_report_schema_roundtrip():
    from datetime import datetime, timezone, date
    r = RawReport(
        source_name="njfishing.com",
        source_url="https://njfishing.com/threads/great-night-at-barnegat.12345/",
        original_author_handle="bassman01",
        scrape_date=datetime.now(timezone.utc),
        post_date=date(2024, 10, 15),
        title="Great night at Barnegat",
        body="Landed 3 keepers on bunker chunks, outgoing tide.",
    )
    blob = r.model_dump_json()
    loaded = RawReport.model_validate_json(blob)
    assert loaded.source_name == r.source_name
    assert loaded.body == r.body
