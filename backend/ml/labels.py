"""Label extraction from report corpus (D-01) + pseudo-absence negatives (D-03).

Pipeline:
  1. Read data/structured_reports/subset.jsonl (StructuredReport records)
  2. Resolve report.location_region → spot_id (caller-supplied mapping)
  3. Emit positive rows: (spot_id, label_time, species, y=1) fanned out over species_mentioned
  4. Sample pseudo-absence negatives per species, restricted to (spot, time) where
     some OTHER species had a positive within ±72h (Pitfall #4)
  5. Cap n_neg ≤ 2 * n_pos per species (D-03)

Per Wave 1 handoff (02-01-SUMMARY.md): post_date is null for ~98% of records,
so reports with no parsed report.fields.date are dropped here. Plan 04
(corpus completion) is expected to lift the date-resolution rate.
"""
from __future__ import annotations

import logging
import pathlib
import random
from datetime import date as _date
from datetime import datetime, time, timedelta, timezone

import pandas as pd

from ingest.reports.schema import StructuredReport
from ml.species_config import SPECIES_LIST

log = logging.getLogger(__name__)

# D-03 cap: negatives:positives ≤ 2:1 per species
NEG_POS_RATIO_CAP = 2.0

# Pitfall #4 window: negatives must be within ±72h of some positive (any species) at same spot
PSEUDO_ABSENCE_WINDOW = timedelta(hours=72)

# Pitfall #3 midpoint rule: report.date → timestamp at UTC noon (represents midday fishing session)
DEFAULT_LABEL_TIME_OF_DAY = time(12, 0, tzinfo=timezone.utc)


def _resolve_spot(report_location_region: str, region_to_spot: dict[str, int]) -> int | None:
    return region_to_spot.get(report_location_region)


def _label_time_from_report(report_date: _date) -> datetime:
    """Pitfall #3 — use midday UTC as the fishing-session midpoint."""
    return datetime.combine(report_date, DEFAULT_LABEL_TIME_OF_DAY)


def extract_labels_from_subset(
    subset_path: pathlib.Path,
    region_to_spot: dict[str, int],
) -> pd.DataFrame:
    """Returns a DataFrame with columns: spot_id, label_time, species, y, source_report_id.

    Parameters
    ----------
    subset_path
        Path to data/structured_reports/subset.jsonl (StructuredReport JSONL).
    region_to_spot
        Mapping of canonical LOCATION_REGION tag → representative spot_id.
        Reports whose location_region is not in the mapping are dropped
        with a diagnostic log entry.
    """
    if not subset_path.exists():
        raise FileNotFoundError(f"Structured report corpus missing: {subset_path}")
    rows: list[dict] = []
    dropped = {
        "unresolved_region": 0,
        "no_date": 0,
        "no_species": 0,
        "unclear_outcome": 0,
        "validation_error": 0,
    }
    with subset_path.open() as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            try:
                rec = StructuredReport.model_validate_json(line)
            except Exception as exc:  # pragma: no cover - defensive
                dropped["validation_error"] += 1
                log.warning("subset.jsonl line %d failed validation: %s", i, exc)
                continue
            if rec.fields.catch_quality == "unclear":
                dropped["unclear_outcome"] += 1
                continue
            # Date resolution: prefer LLM-extracted fields.date (anchors a date
            # mentioned in body text), then forum post timestamp from raw.post_date
            # (the actual post-creation timestamp — usually within a day of the
            # fishing event for forum reports). Final fallback to raw.scrape_date
            # is intentionally NOT used: scrape time is unrelated to the fishing
            # event and would corrupt temporal joins.
            resolved_date = rec.fields.date or rec.raw.post_date
            if resolved_date is None:
                dropped["no_date"] += 1
                continue
            spot_id = _resolve_spot(rec.fields.location_region, region_to_spot)
            if spot_id is None:
                dropped["unresolved_region"] += 1
                continue
            label_time = _label_time_from_report(resolved_date)
            # Outcome encoding: good_catch → 1, slow → 0, no_fish → 0
            y = 1 if rec.fields.catch_quality == "good_catch" else 0
            species_in_scope = [s for s in rec.fields.species_mentioned if s in SPECIES_LIST]
            if not species_in_scope:
                dropped["no_species"] += 1
                continue
            for species in species_in_scope:
                rows.append({
                    "spot_id": spot_id,
                    "label_time": label_time,
                    "species": species,
                    "y": y,
                    "source_report_id": i,
                })
    log.info("extract_labels_from_subset dropped %s; emitted %d rows", dropped, len(rows))
    return pd.DataFrame(rows)


def sample_pseudo_absences(
    positives_df: pd.DataFrame,
    rng_seed: int = 42,
    ratio_cap: float = NEG_POS_RATIO_CAP,
    window: timedelta = PSEUDO_ABSENCE_WINDOW,
) -> pd.DataFrame:
    """Generate (spot, time, species, y=0) tuples from the set of (spot, time) pairs
    where SOME species had a positive within ±window.

    Per Pitfall #4: this prevents negatives from being trivially "night/winter when nobody fished"
    — the negative is now "someone was fishing here within ±window, but not for species X".
    """
    cols = ["spot_id", "label_time", "species", "y", "source_report_id"]
    if positives_df.empty:
        return pd.DataFrame(columns=cols)

    rng = random.Random(rng_seed)
    positives_df = positives_df[positives_df["y"] == 1].copy()
    # Universe of (spot, time) tuples where SOMETHING was caught — Pitfall #4 mitigation.
    universe = positives_df[["spot_id", "label_time"]].drop_duplicates().reset_index(drop=True)

    neg_rows: list[dict] = []
    for species in SPECIES_LIST:
        sp_pos = positives_df[positives_df["species"] == species].copy()
        n_pos = len(sp_pos)
        if n_pos == 0:
            continue
        target_n_neg = min(int(n_pos * ratio_cap), len(universe))

        candidates: list[tuple[int, datetime]] = []
        for _, u in universe.iterrows():
            same_spot = sp_pos[sp_pos["spot_id"] == u["spot_id"]]
            if same_spot.empty:
                candidates.append((int(u["spot_id"]), u["label_time"]))
                continue
            # exclude (spot, time) where this species had a positive within ±window
            deltas = (same_spot["label_time"] - u["label_time"]).abs()
            if (deltas <= window).any():
                continue
            candidates.append((int(u["spot_id"]), u["label_time"]))

        if not candidates:
            continue
        rng.shuffle(candidates)
        for spot_id, label_time in candidates[:target_n_neg]:
            neg_rows.append({
                "spot_id": spot_id,
                "label_time": label_time,
                "species": species,
                "y": 0,
                "source_report_id": None,
            })
    log.info(
        "sample_pseudo_absences emitted %d negatives across %d species",
        len(neg_rows),
        len(SPECIES_LIST),
    )
    if not neg_rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(neg_rows)


def compute_scale_pos_weight(y_train) -> float:
    """Per PITFALLS.md §2 — scale_pos_weight = n_neg / n_pos on TRAIN FOLD ONLY.

    Synthetic-minority oversampling is banned (D-05 amendment to M-05); use this
    weight directly as XGBoost's ``scale_pos_weight`` hyperparameter instead.
    """
    import numpy as np

    y_arr = np.asarray(y_train)
    n_neg = int((y_arr == 0).sum())
    n_pos = int((y_arr == 1).sum())
    if n_pos == 0:
        raise ValueError("Cannot compute scale_pos_weight: zero positives in train fold")
    return n_neg / n_pos


__all__ = [
    "NEG_POS_RATIO_CAP",
    "PSEUDO_ABSENCE_WINDOW",
    "extract_labels_from_subset",
    "sample_pseudo_absences",
    "compute_scale_pos_weight",
]
