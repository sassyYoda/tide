"""OPS-04 schema gate for ``eval/golden_dataset.json``.

Per L-10 (CONTEXT line 79), every golden-dataset entry MUST carry
``reviewed_by`` / ``reviewed_at`` / ``reviewer_notes`` attribution. This
schema test catches any future regression that drops the 20-entry invariant
or removes attribution fields.

Wave 0 invariants:
- Exactly 20 entries.
- Entries 1-4 reviewed by X-commando on 2026-05-23T00:00:00Z (Phase 3 Path A
  hand-grades bundled per D-02).
- Entries 5-20 are placeholders with ``reviewed_by=null``. Wave 2 fills these.

Pydantic strict-schema pattern copied from
``backend/agent/sse_protocol.py:36-88`` (``model_config = ConfigDict(extra="forbid")``).
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
    """Schema for a single entry in eval/golden_dataset.json.

    ``reviewed_by`` and ``reviewed_at`` are nullable in Wave 0 (placeholder
    entries 5-20). Wave 2 hand-review will replace nulls with attribution.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    species: Literal["striper", "fluke", "bluefish", "weakfish", "tautog", "mixed"]
    query: str = Field(min_length=5)
    expected_answer: str = Field(min_length=20)
    reviewed_by: str | None
    reviewed_at: datetime | None
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


def test_phase3_seed_entries_are_reviewed():
    data = _load_dataset()
    reviewed = [e for e in data if e["reviewed_by"] is not None]
    assert len(reviewed) == 4, f"Expected 4 reviewed entries, got {len(reviewed)}"
    for e in reviewed:
        assert e["reviewed_by"] == "X-commando", e
        assert e["reviewed_at"] == "2026-05-23T00:00:00Z", e
    reviewed_ids = sorted(e["id"] for e in reviewed)
    assert reviewed_ids == [1, 2, 3, 4], f"Expected ids 1-4 reviewed, got {reviewed_ids}"


def test_placeholder_entries_have_null_attribution():
    data = _load_dataset()
    placeholders = [e for e in data if e["reviewed_by"] is None]
    assert len(placeholders) == 16, f"Expected 16 placeholders, got {len(placeholders)}"
    for e in placeholders:
        assert e["reviewed_at"] is None, e
