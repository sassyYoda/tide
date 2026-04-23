"""Stub — M-11/M-13 Celery beat scorer. Implemented in Plan 07."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 07"),
    pytest.mark.integration,
]


def test_beat_registers_15min_schedule():
    """Plan 07: celery_app beat schedule contains 'score_all_spots' @ 15min cadence."""
    assert False, "Not implemented"


def test_writes_score_per_spot_species():
    """Plan 07: one activity_scores row per (spot_id, species) after a single tick."""
    assert False, "Not implemented"


def test_shap_values_has_top_3():
    """Plan 07 (M-10): shap_values JSONB has exactly 3 (feature_name, value) entries."""
    assert False, "Not implemented"
