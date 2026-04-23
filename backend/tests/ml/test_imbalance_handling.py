"""Stub — M-05 scale_pos_weight (not SMOTE). Implemented in Plan 03."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 03")


def test_scale_pos_weight_computed_per_species():
    """Plan 03: scale_pos_weight = n_neg/n_pos, computed from train fold only."""
    assert False, "Not implemented"


def test_no_smote_in_pipeline():
    """Plan 03: import assert — imblearn.SMOTE not referenced in training code."""
    assert False, "Not implemented"


def test_calibrated_classifier_cv_applied():
    """Plan 03: CalibratedClassifierCV(cv='prefit') fit on validation fold."""
    assert False, "Not implemented"
