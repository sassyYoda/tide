"""Stub — M-14 permutation-importance leakage gate. Implemented in Plan 03."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 03")


def test_no_feature_has_zero_permutation_drop():
    """Plan 03: every feature's permutation AUC drop > 0 (else it's a leakage proxy)."""
    assert False, "Not implemented"


def test_solunar_contribution_is_nontrivial():
    """Plan 03: solunar features contribute ≥ 0.01 AUC lift or they get dropped."""
    assert False, "Not implemented"
