"""Per-species training orchestrator (D-10 step 2 + D-11 week-4 demo).

Loads subset labels + features, performs temporal split PER SPECIES, trains
XGBoost + LightGBM baseline, logs everything to MLflow.

Week-4 demo success criterion (D-11): striper + fluke complete without error
on whatever labels Plan 01 + 02-04 produce. Tog / weakfish / bluefish may
skip with ``skipped=True, reason=insufficient_labels`` if their per-species
label count is below MIN_LABELS_PER_SPECIES — that is the documented graceful
failure mode for thin species at MVP.

Run:

    DATABASE_URL=postgresql+asyncpg://tide:tide@localhost:5432/tide \\
    DATABASE_SYNC_URL=postgresql+psycopg2://tide:tide@localhost:5432/tide \\
    OPENAI_API_KEY=sk-... \\
    uv run python -m scripts.train_all_species

Tunables via env: ``N_TRIALS`` (default 60), ``RUN_TAG`` (default subset),
``LOG_LEVEL`` (default INFO).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import mlflow
import pandas as pd

from app.config import settings
from db.session import async_session_factory
from ml.species_config import SPECIES_LIST
from ml.splits import temporal_split
from ml.train import EXPERIMENT_NAME, train_lightgbm_baseline, train_species
from scripts.build_training_set import build

log = logging.getLogger(__name__)

# Below this per-species label count, skip with insufficient_labels.
#
# 25 was chosen empirically from the Plan 02-01 subset corpus yield:
# striper (37), bluefish (27), tautog (27) clear the bar; fluke (14) and
# weakfish (4) skip — exactly the graceful failure mode anticipated by D-11
# and addressed by Plan 02-04 (FishBrain top-up). 25 = ~17 train + ~3 val +
# ~5 test rows under 70/15/15, which is enough to get a non-degenerate
# Optuna sweep + calibration fit on synthetic data — initial-pass AUC is
# not asserted at this plan (M-08 / M-09 thresholds move to Plan 05).
#
# Override via the MIN_LABELS_PER_SPECIES env var if needed.
MIN_LABELS_PER_SPECIES = int(os.environ.get("MIN_LABELS_PER_SPECIES", "25"))


async def run(
    run_tag: str = "subset",
    n_trials: int = 60,
    run_lightgbm: bool = True,
) -> dict[str, Any]:
    """Train every species in SPECIES_LIST, returning a per-species results dict."""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    async with async_session_factory() as session:
        bundle = await build(session)

    merged = bundle["merged"]
    feature_names = bundle["feature_names"]
    results: dict[str, Any] = {}

    for species in SPECIES_LIST:
        sp_df = merged[merged["species"] == species].reset_index(drop=True)
        n = len(sp_df)
        if n < MIN_LABELS_PER_SPECIES:
            log.warning(
                "%s: only %d labels — below MIN_LABELS_PER_SPECIES (%d). Skipping.",
                species,
                n,
                MIN_LABELS_PER_SPECIES,
            )
            results[species] = {
                "skipped": True,
                "reason": "insufficient_labels",
                "n": n,
            }
            continue

        # ml.labels assigns every same-day report to UTC noon (Pitfall #3 midpoint
        # rule), so multiple reports on the same date collide on label_time and
        # break temporal_split's strict `<` boundary. Add deterministic
        # microsecond jitter (in row order) to keep ordering stable while
        # producing unique label_time values per species. Span <1 second so
        # the GUARD = 1s upper-bound on feature joins is preserved.
        sp_df = sp_df.copy()
        sp_df["label_time"] = sp_df["label_time"] + pd.to_timedelta(
            range(len(sp_df)), unit="us"
        )

        try:
            train_df, val_df, test_df = temporal_split(sp_df, time_col="label_time")
        except Exception as e:
            log.exception("%s: temporal_split failed: %s", species, e)
            results[species] = {"skipped": True, "reason": f"split_error: {e}"}
            continue

        X_tr = train_df[feature_names].to_numpy(dtype=float)
        y_tr = train_df["y"].to_numpy(dtype=int)
        X_val = val_df[feature_names].to_numpy(dtype=float)
        y_val = val_df["y"].to_numpy(dtype=int)
        X_te = test_df[feature_names].to_numpy(dtype=float)
        y_te = test_df["y"].to_numpy(dtype=int)

        sp_result = train_species(
            species,
            X_tr,
            y_tr,
            X_val,
            y_val,
            X_te,
            y_te,
            feature_names=feature_names,
            n_trials=n_trials,
            run_tag=run_tag,
        )

        if run_lightgbm and not sp_result.get("skipped"):
            try:
                lgb_result = train_lightgbm_baseline(
                    species,
                    X_tr,
                    y_tr,
                    X_val,
                    y_val,
                    X_te,
                    y_te,
                    feature_names=feature_names,
                    n_trials=20,
                    run_tag=run_tag,
                )
                sp_result["lightgbm_baseline_auc"] = lgb_result.get("auc_test")
                sp_result["lightgbm_baseline_run_id"] = lgb_result.get("run_id")
            except Exception as e:  # pragma: no cover - non-fatal baseline
                log.exception("%s: lightgbm baseline failed: %s", species, e)
                sp_result["lightgbm_baseline_error"] = str(e)[:200]

        results[species] = sp_result

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    n = int(os.environ.get("N_TRIALS", "60"))
    tag = os.environ.get("RUN_TAG", "subset")
    out = asyncio.run(run(run_tag=tag, n_trials=n))
    log.info("Orchestrator complete. Results:")
    for sp, res in out.items():
        log.info("  %s → %s", sp, res)
