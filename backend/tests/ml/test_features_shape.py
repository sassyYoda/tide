"""M-01 features — shape, species flags, spot one-hot."""
from __future__ import annotations

from datetime import datetime, timezone

from ml.features import (
    FEATURE_NAMES,
    SPOT_TYPES,
    _species_match_flags,
    _spot_onehot,
    _temporal_block,
)


def test_feature_names_covers_m01_categories():
    cats = {
        "tidal": ["water_level_m", "water_temp_c"],
        "pressure": ["pressure_delta_1h", "pressure_delta_3h", "pressure_delta_6h"],
        "wind": ["wind_sin", "wind_cos", "wind_speed_mps"],
        "solunar": [
            "moon_phase_sin",
            "illumination",
            "lunar_day",
            "is_major_period",
            "hours_to_next_major",
        ],
        "temporal": ["hour_sin", "month_cos", "dow_sin"],
        "lag": ["water_temp_lag_3h", "water_level_lag_6h"],
        "species_match": ["match_temp_range", "match_tide_phase", "match_pressure"],
        "spot_onehot": ["spot_is_jetty", "spot_is_inlet"],
    }
    for cat, cols in cats.items():
        for c in cols:
            assert c in FEATURE_NAMES, f"{cat}: {c} missing"


def test_feature_names_unique():
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))


def test_spot_onehot_exactly_one_hot():
    oh = _spot_onehot("jetty")
    assert oh["spot_is_jetty"] == 1
    assert sum(oh.values()) == 1
    assert set(oh.keys()) == {f"spot_is_{t}" for t in SPOT_TYPES}


def test_spot_onehot_unknown_returns_all_zeros():
    oh = _spot_onehot(None)
    assert sum(oh.values()) == 0


def test_species_match_temp_range_tautog():
    """D-14: tautog temp range 13-18C, dropping pressure."""
    tidal = {"water_temp_c": 15.0, "tidal_rising": 0}
    flags = _species_match_flags("tautog", tidal, {}, {"pressure_delta_3h": -2.0})
    assert flags["match_temp_range"] == 1
    assert flags["match_pressure"] == 1


def test_species_match_temp_range_out_of_range():
    tidal = {"water_temp_c": 25.0, "tidal_rising": 1}
    flags = _species_match_flags("tautog", tidal, {}, {"pressure_delta_3h": 0})
    assert flags["match_temp_range"] == 0


def test_species_match_unknown_species_all_zero():
    flags = _species_match_flags("dolphin", {"water_temp_c": 18, "tidal_rising": 1}, {}, {})
    assert flags == {"match_temp_range": 0, "match_tide_phase": 0, "match_pressure": 0}


def test_temporal_block_cyclic_encoding():
    t = datetime(2024, 6, 21, 12, 0, tzinfo=timezone.utc)  # noon, June, Friday
    block = _temporal_block(t)
    for col in ("hour_sin", "hour_cos", "month_sin", "month_cos", "dow_sin", "dow_cos"):
        assert col in block
        assert -1.0001 <= block[col] <= 1.0001
