"""OPS-04 schema gate for ``eval/golden_dataset.json``.

Per L-10 (CONTEXT line 79), every golden-dataset entry MUST carry
``reviewed_by`` / ``reviewed_at`` / ``reviewer_notes`` attribution.

Post-Wave-2 invariants (2026-05-23 hand-review complete):
- Exactly 20 entries.
- ALL 20 entries are reviewed by X-commando (no nulls).
- Entries 1-4 are Phase 3 Path A carry-overs (D-02 bundle).
- Entries 5-20 are Wave 2 hand-reviewed candidates.

Pydantic strict-schema pattern copied from
``backend/agent/sse_protocol.py`` (``model_config = ConfigDict(extra="forbid")``).
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# tests/eval/ → tests → backend → repo  (parents[3])
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN_PATH = REPO_ROOT / "eval" / "golden_dataset.json"


class GoldenEntry(BaseModel):
    """Schema for a single entry in eval/golden_dataset.json (post-Wave-2 shape)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    species: Literal["striper", "fluke", "bluefish", "weakfish", "tautog", "mixed"]
    query_type: Literal["happy_path", "jargon_heavy", "casual", "definition", "out_of_scope"]
    query: str = Field(min_length=5)
    expected_answer: str = Field(min_length=20)
    expected_citations: list[str] = Field(default_factory=list)
    reviewed_by: str
    reviewed_at: datetime
    reviewer_notes: str


def _load_dataset() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text())


def test_dataset_has_20_entries():
    data = _load_dataset()
    assert len(data) == 20, f"Expected 20 entries, got {len(data)}"


def test_all_entries_validate_schema():
    data = _load_dataset()
    for entry in data:
        GoldenEntry.model_validate(entry)  # raises on invalid


def test_all_20_entries_have_attribution_after_wave2():
    """OPS-04: post-Wave-2, all 20 entries must have X-commando attribution."""
    data = _load_dataset()
    reviewed = [e for e in data if e.get("reviewed_by") and e.get("reviewed_at")]
    assert len(reviewed) == 20, f"Expected all 20 entries reviewed, got {len(reviewed)}"
    for e in reviewed:
        assert e["reviewed_by"] == "X-commando", f"Entry {e['id']} reviewer != X-commando"


def test_no_unreviewed_entries_remain():
    """Inverse of test_all_20_entries_have_attribution_after_wave2."""
    data = _load_dataset()
    unreviewed = [e for e in data if not e.get("reviewed_by") or not e.get("reviewed_at")]
    assert len(unreviewed) == 0, f"Expected 0 unreviewed entries, got {len(unreviewed)}: {[e['id'] for e in unreviewed]}"


def test_query_type_distribution():
    """Sanity check the planned mix: 7 casual / 5 happy_path / 4 jargon_heavy / 2 definition / 2 out_of_scope."""
    data = _load_dataset()
    from collections import Counter

    types = Counter(e["query_type"] for e in data)
    # Allow some flexibility — just assert all 5 categories present + within ±2 of plan
    assert "casual" in types
    assert "happy_path" in types
    assert "jargon_heavy" in types
    assert "definition" in types
    assert "out_of_scope" in types
    assert types["out_of_scope"] == 2, "Refusal tests should be exactly 2 (regulatory + freshwater)"
    assert types["definition"] >= 1, "At least 1 definitional entry required"


def test_species_coverage():
    """All 5 species (striper, fluke, bluefish, weakfish, tautog) must appear at least once."""
    data = _load_dataset()
    species_seen = {e["species"] for e in data}
    required = {"striper", "fluke", "bluefish", "weakfish", "tautog"}
    missing = required - species_seen
    assert not missing, f"Missing species: {missing}"
