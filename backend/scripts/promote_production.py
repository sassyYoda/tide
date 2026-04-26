"""Promote best-by-validation-AUC run per species to MLflow `production` alias (D-12, M-13).

Per D-12: both subset and full runs are candidates; normally the full-corpus
run wins but this is empirical, not assumed. Decision is by ``auc_val``.

MLflow registered-model naming convention: ``activity-{species}`` (e.g.
``activity-striper``). Alias: ``production`` points to the best version.

Run:

    cd backend
    DATABASE_URL=postgresql+asyncpg://tide:tide@localhost:5432/tide \\
    DATABASE_SYNC_URL=postgresql+psycopg2://tide:tide@localhost:5432/tide \\
    uv run python -m scripts.promote_production
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient

from app.config import settings
from ml.species_config import SPECIES_LIST
from ml.train import EXPERIMENT_NAME

log = logging.getLogger(__name__)

# parents[0]=scripts, parents[1]=backend, parents[2]=repo_root
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY_REPORT_PATH = REPO_ROOT / "data" / "model_registry_report.json"


def _best_run_for_species(
    client: MlflowClient, experiment_id: str, species: str
):
    """Best-by-validation-AUC across XGBoost runs for a species.

    Excludes:
      - LightGBM baseline runs (``params.baseline = 'lightgbm'``)
      - Skipped runs (``params.skip_reason`` is set)
      - Runs missing ``auc_val`` metric entirely

    Returns the best mlflow.entities.Run, or ``None`` if none qualify.
    """
    runs = client.search_runs(
        experiment_ids=[experiment_id],
        filter_string=f"params.species = '{species}'",
        order_by=["metrics.auc_val DESC"],
        max_results=50,
    )
    eligible = [
        r
        for r in runs
        if r.data.params.get("baseline") != "lightgbm"
        and "skip_reason" not in r.data.params
        and "auc_val" in r.data.metrics
    ]
    if not eligible:
        return None
    return eligible[0]


def promote_all() -> dict[str, Any]:
    """Promote best XGBoost run per species to ``production`` alias.

    Returns a per-species report dict; also writes
    ``data/model_registry_report.json`` for Plan 07 loader consumption.
    """
    # Honor an explicitly-set MLFLOW_TRACKING_URI (test fixtures use this for
    # tmp-dir isolation); otherwise fall back to Pydantic settings — which is
    # itself populated from MLFLOW_TRACKING_URI at import time, so this is a
    # belt-and-braces guard against module-import-vs-fixture-order ordering.
    uri = os.environ.get("MLFLOW_TRACKING_URI", settings.mlflow_tracking_uri)
    mlflow.set_tracking_uri(uri)
    client = MlflowClient()
    exp = client.get_experiment_by_name(EXPERIMENT_NAME)
    if exp is None:
        raise RuntimeError(
            f"Experiment {EXPERIMENT_NAME} does not exist — run training first"
        )
    report: dict[str, Any] = {}
    for species in SPECIES_LIST:
        best = _best_run_for_species(client, exp.experiment_id, species)
        if best is None:
            log.warning("no-best-run species=%s", species)
            report[species] = {"promoted": False, "reason": "no_eligible_runs"}
            continue
        model_name = f"activity-{species}"
        # Calibrated sklearn artifact is the inference target (Plan 07 loads it).
        model_uri = f"runs:/{best.info.run_id}/calibrated_{species}"
        try:
            registered = mlflow.register_model(model_uri=model_uri, name=model_name)
        except Exception as e:  # pragma: no cover - mlflow API drift / artifact missing
            log.exception("register-failed species=%s error=%s", species, e)
            report[species] = {
                "promoted": False,
                "reason": f"register_failed: {e}",
            }
            continue
        client.set_registered_model_alias(model_name, "production", registered.version)
        cal_code = best.data.metrics.get("calibration_method_code")
        report[species] = {
            "promoted": True,
            "run_id": best.info.run_id,
            "run_name": best.data.tags.get("mlflow.runName"),
            "model_name": model_name,
            "version": registered.version,
            "auc_val": best.data.metrics.get("auc_val"),
            "auc_test": best.data.metrics.get("auc_test"),
            "brier_test": best.data.metrics.get("brier_test"),
            "precision_at_top25_test": best.data.metrics.get("precision_at_top25_test"),
            "calibration_method": (
                "isotonic"
                if cal_code == 2
                else "sigmoid"
                if cal_code == 1
                else "uncalibrated"
            ),
        }
    REGISTRY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_REPORT_PATH.write_text(json.dumps(report, indent=2))
    log.info(
        "promotion-report path=%s species_count=%d",
        REGISTRY_REPORT_PATH,
        len(report),
    )
    return report


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    promote_all()


__all__ = ["promote_all", "REGISTRY_REPORT_PATH"]
