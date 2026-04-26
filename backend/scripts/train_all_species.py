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
from scripts.build_training_set import CORPUS_PATH, DEFAULT_SUBSET_PATH, build

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
    enforce_gates: bool = False,
) -> dict[str, Any]:
    """Train every species in SPECIES_LIST, returning a per-species results dict.

    Plan 02-05 wiring:
      - ``run_tag='subset'`` reads ``DEFAULT_SUBSET_PATH`` (Plan 02-01 input — Plan 03 demo).
      - ``run_tag='full'`` reads ``CORPUS_PATH`` (Plan 02-04 corpus.jsonl — Plan 05 retrain).
      - ``enforce_gates=True`` asserts M-08 / M-09 gates with D-04/D-16 tautog
        fallback decision tree (low-label-regime pass-with-note 0.65–0.72;
        unconditional pass ≥ 0.72; fail < 0.65).
    """
    # Honor an explicitly-set MLFLOW_TRACKING_URI (test fixtures use this for
    # tmp-dir isolation); otherwise fall back to Pydantic settings.
    uri = os.environ.get("MLFLOW_TRACKING_URI", settings.mlflow_tracking_uri)
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(EXPERIMENT_NAME)

    corpus = CORPUS_PATH if run_tag == "full" else DEFAULT_SUBSET_PATH
    if not corpus.exists():
        raise FileNotFoundError(f"Training corpus missing: {corpus}")
    log.info("training corpus: %s (run_tag=%s)", corpus, run_tag)

    async with async_session_factory() as session:
        bundle = await build(session, subset_path=corpus)

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

    if enforce_gates:
        _check_quality_gates(results)
    return results


def _check_quality_gates(results: dict[str, Any]) -> None:
    """M-08 / M-09 gate check with D-04 + D-16 tautog fallback decision tree.

    D-04: AUC ≥ 0.72 hard target unless documented low-label regime.
    D-16: Tautog labelscarcity is anticipated. Decision tree:
        - tautog AUC ≥ 0.72  → unconditional pass (with everyone else)
        - tautog AUC 0.65-0.72 → pass-with-note (logged as warning, not raised)
        - tautog AUC < 0.65   → fail (raise)

    M-09: Brier ≤ 0.22 AND Precision@Top25% ≥ 0.65 are hard for ALL species.

    A skipped species (insufficient_labels / single_class_fold / empty_fold) is
    logged as a warning only — the orchestrator already left a synthetic skip
    run in MLflow with the reason; do not re-fail here.

    Raises ``RuntimeError`` listing every failure if any gate fails.
    """
    failures: list[str] = []
    warnings_: list[str] = []
    for species, r in results.items():
        if r.get("skipped"):
            warnings_.append(
                f"{species}: skipped — {r.get('reason', 'unknown')}"
            )
            continue
        # All three are required for non-skipped species; missing means the
        # train_species loop crashed in a way that should be a hard failure.
        if "auc_test" not in r or "brier_test" not in r or "p_at_25_test" not in r:
            failures.append(
                f"{species}: missing gate metrics (auc_test/brier_test/p_at_25_test) — "
                f"got keys {sorted(r.keys())}"
            )
            continue
        auc = r["auc_test"]
        brier = r["brier_test"]
        p25 = r["p_at_25_test"]
        # M-08 AUC gate with D-04/D-16 tautog fallback
        if species == "tautog":
            if auc < 0.65:
                failures.append(
                    f"tautog: AUC {auc:.3f} < 0.65 (low-label fallback floor — D-16)"
                )
            elif auc < 0.72:
                warnings_.append(
                    f"tautog: AUC {auc:.3f} in 0.65-0.72 range — pass-with-note per D-16"
                )
        else:
            if auc < 0.72:
                failures.append(
                    f"{species}: AUC {auc:.3f} < 0.72 (M-08)"
                )
        # M-09 gates — Brier and P@25 are hard for every promoted species.
        if brier > 0.22:
            failures.append(
                f"{species}: Brier {brier:.3f} > 0.22 (M-09)"
            )
        if p25 < 0.65:
            failures.append(
                f"{species}: P@25 {p25:.3f} < 0.65 (M-09)"
            )
    for w in warnings_:
        log.warning("QUALITY-NOTE %s", w)
    if failures:
        raise RuntimeError(
            "Quality gates failed:\n  " + "\n  ".join(failures)
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    n = int(os.environ.get("N_TRIALS", "60"))
    tag = os.environ.get("RUN_TAG", "subset")
    enforce = os.environ.get("ENFORCE_GATES", "0") == "1" or tag == "full"
    out = asyncio.run(run(run_tag=tag, n_trials=n, enforce_gates=enforce))
    log.info("Orchestrator complete. Results:")
    for sp, res in out.items():
        log.info("  %s → %s", sp, res)
