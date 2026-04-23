"""Stub — M-10/M-11 scorer row shape + SHAP persistence. Implemented in Plan 07."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 07"),
    pytest.mark.integration,
]


def test_activity_scores_row_has_required_fields():
    """Plan 07: each row has score, shap_values, model_version, confidence, is_forecast, raw_payload."""
    assert False, "Not implemented"


def test_confidence_label_matches_report_density():
    """Plan 07 (M-11): confidence='high' iff ≥3 reports <72h, else 'moderate'/'low'."""
    assert False, "Not implemented"
