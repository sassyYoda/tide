"""Label extraction + pseudo-absence sampling (D-03, Pitfall #4)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


BASE = datetime(2024, 10, 1, 12, 0, tzinfo=timezone.utc)


def _pos_df():
    return pd.DataFrame([
        # (spot 1, striper positive at T)
        {"spot_id": 1, "label_time": BASE, "species": "striper", "y": 1, "source_report_id": 0},
        # (spot 1, fluke positive at T + 1h — same spot/time bucket as striper pos
        #  → universe member, but excluded from striper negatives because striper
        #  has a positive at spot 1 within 72h)
        {"spot_id": 1, "label_time": BASE + timedelta(hours=1), "species": "fluke", "y": 1, "source_report_id": 1},
        # (spot 2, bluefish positive far in time — eligible universe for striper negatives at spot 2)
        {"spot_id": 2, "label_time": BASE + timedelta(days=10), "species": "bluefish", "y": 1, "source_report_id": 2},
    ])


def test_pseudo_absence_respects_cap():
    from ml.labels import sample_pseudo_absences

    positives = _pos_df()
    negs = sample_pseudo_absences(positives, rng_seed=1, ratio_cap=2.0)
    # n_neg per species must be ≤ 2 × n_pos for that species
    for sp in negs["species"].unique():
        n_pos = int(((positives["species"] == sp) & (positives["y"] == 1)).sum())
        n_neg = int((negs["species"] == sp).sum())
        assert n_neg <= 2 * n_pos, f"{sp}: {n_neg} negatives > 2 × {n_pos} positives"


def test_pseudo_absence_excludes_same_species_within_window():
    from ml.labels import sample_pseudo_absences

    positives = _pos_df()
    negs = sample_pseudo_absences(positives, rng_seed=1, ratio_cap=10.0)
    # No striper-negative may appear at spot=1 within 72h of striper positive at BASE
    striper_negs = negs[negs["species"] == "striper"]
    for _, row in striper_negs.iterrows():
        if row["spot_id"] == 1:
            assert abs(row["label_time"] - BASE) > timedelta(hours=72)


def test_pseudo_absence_returns_only_y_zero():
    from ml.labels import sample_pseudo_absences

    negs = sample_pseudo_absences(_pos_df())
    if not negs.empty:
        assert (negs["y"] == 0).all()


def test_pseudo_absence_deterministic_with_seed():
    from ml.labels import sample_pseudo_absences

    neg1 = (
        sample_pseudo_absences(_pos_df(), rng_seed=42)
        .sort_values(["spot_id", "label_time", "species"])
        .reset_index(drop=True)
    )
    neg2 = (
        sample_pseudo_absences(_pos_df(), rng_seed=42)
        .sort_values(["spot_id", "label_time", "species"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(neg1, neg2)


def test_extract_labels_drops_unresolved_region(tmp_path):
    from ml.labels import extract_labels_from_subset

    struct_path = tmp_path / "subset.jsonl"
    rec = {
        "raw": {
            "source_name": "test",
            "scrape_date": datetime.now(timezone.utc).isoformat(),
            "body": "x",
        },
        "fields": {
            "catch_quality": "good_catch",
            "species_mentioned": ["striper"],
            "water_body": None,
            "location_region": "other_nj",  # not in region map
            "date": "2024-10-15",
            "bait_mentioned": [],
            "tide_phase": "unknown",
            "confidence": 0.9,
        },
    }
    struct_path.write_text(json.dumps(rec) + "\n")
    df = extract_labels_from_subset(struct_path, region_to_spot={"barnegat_bay": 1})
    assert len(df) == 0  # dropped due to unresolved region


def test_extract_labels_fans_out_species(tmp_path):
    from ml.labels import extract_labels_from_subset

    struct_path = tmp_path / "subset.jsonl"
    rec = {
        "raw": {
            "source_name": "test",
            "scrape_date": datetime.now(timezone.utc).isoformat(),
            "body": "x",
        },
        "fields": {
            "catch_quality": "good_catch",
            "species_mentioned": ["striper", "bluefish"],
            "water_body": "Barnegat",
            "location_region": "barnegat_bay",
            "date": "2024-10-15",
            "bait_mentioned": [],
            "tide_phase": "outgoing",
            "confidence": 0.9,
        },
    }
    struct_path.write_text(json.dumps(rec) + "\n")
    df = extract_labels_from_subset(struct_path, region_to_spot={"barnegat_bay": 1})
    assert len(df) == 2  # fanned out
    assert set(df["species"]) == {"striper", "bluefish"}
    assert (df["y"] == 1).all()


def test_extract_labels_drops_unclear_and_no_date(tmp_path):
    from ml.labels import extract_labels_from_subset

    struct_path = tmp_path / "subset.jsonl"
    lines = []
    # unclear → dropped
    lines.append(json.dumps({
        "raw": {"source_name": "t", "scrape_date": datetime.now(timezone.utc).isoformat(), "body": "x"},
        "fields": {
            "catch_quality": "unclear", "species_mentioned": ["striper"],
            "water_body": None, "location_region": "barnegat_bay",
            "date": "2024-10-15", "bait_mentioned": [], "tide_phase": "unknown",
            "confidence": 0.9,
        },
    }))
    # no date → dropped
    lines.append(json.dumps({
        "raw": {"source_name": "t", "scrape_date": datetime.now(timezone.utc).isoformat(), "body": "x"},
        "fields": {
            "catch_quality": "good_catch", "species_mentioned": ["striper"],
            "water_body": None, "location_region": "barnegat_bay",
            "date": None, "bait_mentioned": [], "tide_phase": "unknown",
            "confidence": 0.9,
        },
    }))
    # only "other" species → dropped
    lines.append(json.dumps({
        "raw": {"source_name": "t", "scrape_date": datetime.now(timezone.utc).isoformat(), "body": "x"},
        "fields": {
            "catch_quality": "good_catch", "species_mentioned": ["other"],
            "water_body": None, "location_region": "barnegat_bay",
            "date": "2024-10-15", "bait_mentioned": [], "tide_phase": "unknown",
            "confidence": 0.9,
        },
    }))
    struct_path.write_text("\n".join(lines) + "\n")
    df = extract_labels_from_subset(struct_path, region_to_spot={"barnegat_bay": 1})
    assert len(df) == 0


def test_extract_labels_no_fish_yields_y_zero(tmp_path):
    from ml.labels import extract_labels_from_subset

    struct_path = tmp_path / "subset.jsonl"
    rec = {
        "raw": {
            "source_name": "test",
            "scrape_date": datetime.now(timezone.utc).isoformat(),
            "body": "x",
        },
        "fields": {
            "catch_quality": "no_fish",
            "species_mentioned": ["striper"],
            "water_body": None,
            "location_region": "barnegat_bay",
            "date": "2024-10-15",
            "bait_mentioned": [],
            "tide_phase": "unknown",
            "confidence": 0.9,
        },
    }
    struct_path.write_text(json.dumps(rec) + "\n")
    df = extract_labels_from_subset(struct_path, region_to_spot={"barnegat_bay": 1})
    assert len(df) == 1
    assert df.iloc[0]["y"] == 0


def test_extract_labels_raises_when_subset_missing(tmp_path):
    from ml.labels import extract_labels_from_subset

    with pytest.raises(FileNotFoundError):
        extract_labels_from_subset(tmp_path / "missing.jsonl", region_to_spot={})
