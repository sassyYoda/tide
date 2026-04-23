"""Stub — R-02 GPT-4o-mini field-extraction schema. Implemented in Plan 01."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 01")


def test_extracted_fields_conform_to_pydantic_schema():
    """Plan 01: instructor-validated output has catch_quality, species_mentioned, water_body, date, bait, location."""
    assert False, "Not implemented"


def test_catch_quality_is_enum_good_slow_no_fish():
    """Plan 01: catch_quality ∈ {good, slow, no_fish}."""
    assert False, "Not implemented"
