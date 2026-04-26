"""Build (labels_df + features_df) for training from Plan 01's subset.jsonl.

Steps:
  1. Load seeds/fishing_spots.json → build region_to_spot + station_id_by_spot
     + spot_type_by_id (using array index + 1 as spot_id, matching the BIGSERIAL
     order the alembic 0005 migration inserts the rows in).
  2. extract_labels_from_subset(subset.jsonl, region_to_spot) → positives
  3. sample_pseudo_absences(positives) → negatives
  4. Concat → labels_df; build_features_for_rows for every (spot, time, species)
     → features_df
  5. Concat features alongside labels → merged DataFrame for split + train

Region mapping (per Wave 3 runtime-context guidance):

    barnegat / barnegat_bay → spot_id 1  (Barnegat Inlet — North Jetty)
    manasquan               → spot_id 3  (Manasquan Inlet — North Jetty)
    sandy_hook              → spot_id 5  (Shark River Inlet — North Jetty,
                                         the closest jetty to Sandy Hook in seed)
    ibsp / island_beach     → spot_id 2  (Barnegat Inlet — South Jetty,
                                         immediately adjacent to IBSP)
    other_nj / unknown      → spot_id 1  (default fall-through)

This region map is intentionally narrow at MVP — the scrapers from Plan 02-01
only surfaced these regions in the corpus. Plan 02-04 will expand it.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from ml.features import FEATURE_NAMES, build_features_for_rows
from ml.labels import extract_labels_from_subset, sample_pseudo_absences

log = logging.getLogger(__name__)

# build_training_set.py at backend/scripts/build_training_set.py
# parents[0]=scripts, parents[1]=backend, parents[2]=repo_root
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SEEDS_PATH = REPO_ROOT / "seeds" / "fishing_spots.json"
DEFAULT_SUBSET_PATH = REPO_ROOT / "data" / "structured_reports" / "subset.jsonl"


# Map ReportFields.location_region → spot-name substring(s). First matching
# spot in the seed array (in BIGSERIAL order) wins. Substrings are normalized
# to lowercase before matching.
REGION_HINTS: dict[str, tuple[str, ...]] = {
    "barnegat": ("barnegat",),
    "barnegat_bay": ("barnegat",),
    "manasquan": ("manasquan",),
    # Sandy Hook is north of the seeded jetty universe (Shark River is closest)
    "sandy_hook": ("shark river",),
    "ibsp": ("island beach", "ibsp"),
    "island_beach": ("island beach", "ibsp"),
}


def load_spot_maps() -> tuple[dict[str, int], dict[int, str], dict[int, str]]:
    """Returns ``(region_to_spot, spot_type_by_id, station_id_by_spot)``.

    spot_id is assigned as ``array_index + 1`` to mirror the BIGSERIAL ID that
    alembic migration 0005 produces when seeding the same JSON array in order.
    """
    spots = json.loads(SEEDS_PATH.read_text())
    spot_type_by_id: dict[int, str] = {}
    station_id_by_spot: dict[int, str] = {}
    region_to_spot: dict[str, int] = {}

    for idx, spot in enumerate(spots):
        sid = idx + 1
        spot_type_by_id[sid] = spot.get("spot_type", "flat")
        station_id_by_spot[sid] = spot.get("nearest_station") or ""
        name_lower = (spot.get("name") or "").lower()
        for region, hints in REGION_HINTS.items():
            if region in region_to_spot:
                continue
            if any(h in name_lower for h in hints):
                region_to_spot[region] = sid

    if "other_nj" not in region_to_spot and spots:
        region_to_spot["other_nj"] = 1
    if "unknown" not in region_to_spot and spots:
        region_to_spot["unknown"] = 1

    return region_to_spot, spot_type_by_id, station_id_by_spot


async def build(
    session: AsyncSession,
    subset_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    """Read subset.jsonl, build labels + features, return merged DataFrame.

    Returns:
        ``{"labels_df", "features_df", "merged", "feature_names"}``.
    """
    subset_path = subset_path or DEFAULT_SUBSET_PATH
    region_to_spot, spot_type_by_id, station_id_by_spot = load_spot_maps()
    log.info("region_to_spot map: %s", region_to_spot)

    positives = extract_labels_from_subset(subset_path, region_to_spot)
    negatives = sample_pseudo_absences(positives)
    labels_df = pd.concat([positives, negatives], ignore_index=True)
    if labels_df.empty:
        raise RuntimeError(
            f"No labels extracted from {subset_path} — region_to_spot keys: "
            f"{sorted(region_to_spot.keys())}"
        )
    log.info(
        "Labels: total=%d (pos=%d, neg=%d)",
        len(labels_df),
        int(labels_df["y"].sum()),
        int((labels_df["y"] == 0).sum()),
    )

    feature_rows = list(
        zip(labels_df["spot_id"], labels_df["label_time"], labels_df["species"])
    )
    features_df = await build_features_for_rows(
        session,
        feature_rows,
        spot_type_by_id=spot_type_by_id,
        station_id_by_spot=station_id_by_spot,
    )

    if features_df.empty:
        raise RuntimeError(
            "build_features_for_rows produced zero rows — every spot_id is "
            "missing from station_id_by_spot or every label_time is outside the "
            "environmental backfill window."
        )

    # Concat features alongside labels — features were generated row-by-row in
    # the same order as labels_df, so the index alignment is row-positional.
    feat_only = features_df.drop(columns=["spot_id", "label_time", "species"]).reset_index(
        drop=True
    )
    merged = pd.concat([labels_df.reset_index(drop=True), feat_only], axis=1)

    return {
        "labels_df": labels_df,
        "features_df": features_df,
        "merged": merged,
        "feature_names": FEATURE_NAMES,
    }


__all__ = ["build", "load_spot_maps", "REGION_HINTS"]
