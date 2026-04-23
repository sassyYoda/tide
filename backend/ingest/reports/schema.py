"""Report scraping + extraction schemas.

RawReport = what the scrapers emit (pre-extraction).
ReportFields = what GPT-4o-mini extracts (structured).
StructuredReport = RawReport + ReportFields joined, ready for labels + Qdrant.
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


CANONICAL_SPECIES = Literal["striper", "fluke", "bluefish", "weakfish", "tautog", "other"]
LOCATION_REGION = Literal[
    "barnegat_bay", "manasquan", "sandy_hook", "ibsp", "other_nj", "unknown"
]
TIDE_PHASE = Literal["incoming", "outgoing", "slack_high", "slack_low", "unknown"]
CATCH_QUALITY = Literal["good_catch", "slow", "no_fish", "unclear"]


class RawReport(BaseModel):
    """Emitted by each scraper. All attribution fields per D-09."""

    source_name: str  # e.g. "njfishing.com", "surftalk", "fb_manual"
    source_url: str | None = None  # None for FB manual
    source_description: str | None = None  # FB manual variant per D-09
    original_author_handle: str | None = None  # raw handle (redacted for FB per user policy)
    scrape_date: datetime
    post_date: _date | None = None  # best-guess from source metadata
    title: str | None = None
    body: str
    ingest_notes: dict = Field(default_factory=dict)  # scraper-specific diagnostics


class ReportFields(BaseModel):
    """GPT-4o-mini extraction output. Schema is the Instructor contract."""

    catch_quality: CATCH_QUALITY = Field(
        description="Overall outcome reported by the angler."
    )
    species_mentioned: list[CANONICAL_SPECIES] = Field(
        description=(
            "Species explicitly named or clearly implied via NJ nicknames: "
            "'blackfish'=tautog, 'linesider'/'rockfish'=striper, 'hardhead'=weakfish."
        )
    )
    water_body: str | None = Field(
        description='Best-guess, e.g. "Barnegat Bay", "Manasquan Inlet". None if unstated.'
    )
    location_region: LOCATION_REGION = Field(
        description="Canonical NJ region tag for Qdrant payload filtering."
    )
    date: _date | None = Field(
        description="Date of the reported trip; None if unresolvable."
    )
    bait_mentioned: list[str] = Field(
        default_factory=list, description="Lures, baits, techniques named."
    )
    tide_phase: TIDE_PHASE = Field(
        description="Tide phase at time of reported catch."
    )
    confidence: float = Field(
        ge=0, le=1, description="Self-reported extraction confidence; <0.5 flags for human review."
    )


class StructuredReport(BaseModel):
    raw: RawReport
    fields: ReportFields
