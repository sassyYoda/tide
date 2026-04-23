"""Stub — M-01 feature-engineering pipeline shape. Implemented in Plan 02."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Wave 0 stub — implemented in Plan 02")


def test_feature_vector_has_all_required_groups():
    """Plan 02: tidal + atmospheric + solunar + temporal + water + species-match + lag present."""
    assert False, "Not implemented"


def test_feature_vector_has_spot_type_one_hot():
    """Plan 02 (D-13): spot_type one-hot encoded (is_jetty, is_inlet, is_flat, ...)."""
    assert False, "Not implemented"
