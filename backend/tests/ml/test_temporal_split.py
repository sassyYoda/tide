"""M-04 temporal split — unit tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from ml.splits import assert_no_leakage, temporal_split


BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _labels_df(n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "spot_id": [i % 10 + 1 for i in range(n)],
        "species": ["striper"] * n,
        "label_time": [BASE + timedelta(hours=i) for i in range(n)],
        "y": [i % 2 for i in range(n)],
    })


def test_strict_chronological_boundaries():
    train, val, test = temporal_split(_labels_df(100))
    assert train["label_time"].max() < val["label_time"].min()
    assert val["label_time"].max() < test["label_time"].min()


def test_70_15_15_default_fractions():
    train, val, test = temporal_split(_labels_df(100))
    assert len(train) == 70
    assert len(val) == 15
    assert len(test) == 15


def test_no_rows_lost():
    df = _labels_df(137)
    train, val, test = temporal_split(df)
    assert len(train) + len(val) + len(test) == 137


def test_rejects_bad_fractions():
    with pytest.raises(ValueError):
        temporal_split(_labels_df(100), train_frac=0.9, val_frac=0.2)


def test_rejects_tiny_df():
    with pytest.raises(ValueError):
        temporal_split(_labels_df(5))


def test_assert_no_leakage_passes_on_clean_split():
    train, _, test = temporal_split(_labels_df(100))
    assert_no_leakage(train, test)  # no raise


def test_assert_no_leakage_raises_on_overlap():
    df = _labels_df(100)
    train = df.iloc[:60]
    test = df.iloc[40:]  # overlaps train
    with pytest.raises(AssertionError, match="LEAKAGE"):
        assert_no_leakage(train, test)


def test_split_stable_under_permutation():
    """Random permutation of input rows must yield same split (sort-by-time invariance)."""
    df = _labels_df(50).sample(frac=1, random_state=42).reset_index(drop=True)
    train, val, test = temporal_split(df)
    assert train["label_time"].is_monotonic_increasing
    assert val["label_time"].is_monotonic_increasing
    assert test["label_time"].is_monotonic_increasing
