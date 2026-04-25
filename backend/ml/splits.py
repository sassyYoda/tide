"""Temporal train/val/test split (M-04) — strict chronological ordering.

Per PITFALLS.md §1, random shuffling is banned for this problem class.
The test fold must be strictly chronologically after the val fold, which
must be strictly after the train fold. No overlap ever.
"""
from __future__ import annotations

import pandas as pd


def temporal_split(
    df: pd.DataFrame,
    time_col: str = "label_time",
    train_frac: float = 0.70,
    val_frac: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological 70/15/15 split.

    Raises AssertionError if the strict boundary invariant is violated
    (e.g., duplicate timestamps straddling the boundary).
    """
    if not 0 < train_frac < 1 or not 0 < val_frac < 1 or train_frac + val_frac >= 1:
        raise ValueError(f"Bad fractions: train={train_frac} val={val_frac}")
    df_sorted = df.sort_values(time_col).reset_index(drop=True)
    n = len(df_sorted)
    if n < 10:
        raise ValueError(f"Cannot split {n} rows — need >= 10")
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)
    train = df_sorted.iloc[:train_end].copy()
    val = df_sorted.iloc[train_end:val_end].copy()
    test = df_sorted.iloc[val_end:].copy()

    # Hard boundary invariant per PITFALLS.md §1
    assert train[time_col].max() < val[time_col].min(), (
        f"Split leak: max(train)={train[time_col].max()} >= min(val)={val[time_col].min()}"
    )
    assert val[time_col].max() < test[time_col].min(), (
        f"Split leak: max(val)={val[time_col].max()} >= min(test)={test[time_col].min()}"
    )
    return train, val, test


def assert_no_leakage(
    train_df: pd.DataFrame, test_df: pd.DataFrame, time_col: str = "label_time"
) -> None:
    """Post-split guard. Called by the leakage integration test AND at the top of
    train.py before any feature computation.
    """
    if train_df.empty or test_df.empty:
        return
    train_max = train_df[time_col].max()
    test_min = test_df[time_col].min()
    assert train_max < test_min, (
        f"LEAKAGE: max(train[{time_col}])={train_max} >= min(test[{time_col}])={test_min}"
    )


__all__ = ["temporal_split", "assert_no_leakage"]
