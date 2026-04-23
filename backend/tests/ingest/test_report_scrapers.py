"""Stub — R-01/R-02/R-11 report scrapers (NJFishing, SurfTalk, FishBrain, manual-FB). Implemented in Plan 01."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 01")


def test_njfishing_scraper_respects_robots_txt():
    """Plan 01 (R-11): scraper checks robots.txt and backs off on Disallow."""
    assert False, "Not implemented"


def test_fishbrain_scraper_preserves_attribution():
    """Plan 01 (D-09): payload retains source_url, original_author_handle, scrape_date."""
    assert False, "Not implemented"


def test_manual_fb_transcription_loader():
    """Plan 01 (R-11 amended): manual-FB YAML loader preserves source_description + attribution."""
    assert False, "Not implemented"


def test_extract_fields_via_instructor_gpt4o_mini():
    """Plan 01 (R-02): instructor-validated GPT-4o-mini extraction returns structured output."""
    assert False, "Not implemented"
