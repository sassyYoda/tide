"""XGBoost per-species model singleton (M-12).

Loaded ONCE at FastAPI startup + Celery worker boot via MLflow
``activity-{species}@production`` alias resolution. Per the Plan 02-05
contract (``data/model_registry_report.json``), some species may NOT have a
production-aliased version because their best run was gated below M-08/M-09
thresholds; the loader logs a structured warning and skips that species
rather than crashing the worker.

This deviates from the literal PLAN draft text ("fail-fast if any missing")
in line with the 02-05 SUMMARY's "Plan 07 contract for the production
loader" — Wave-5 reality is that 0/5 species cleared production gates, so
strict fail-fast would brick the scorer entirely. The fallback policy is
deferred to the scorer task: missing-model species cells are skipped + the
``failure`` count in the task return reflects the gap.

Invariant per T-02-03-01 / T-02-07-01 mitigation: ``MLFLOW_TRACKING_URI``
must point at a trusted prefix (./, file://, gs://). Anything else raises
RuntimeError before MLflow attempts to deserialise pickled artifacts —
loading a malicious calibrated CalibratedClassifierCV pickle from an
attacker-controlled URI would be RCE-equivalent.

``TIDE_LAZY_MODEL_LOAD=1`` opts out of the import-time load (used by tests
that set up a tmp MLflow tracking directory in a fixture).
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

import mlflow
import numpy as np
from mlflow.tracking import MlflowClient

from app.config import settings
from ml.species_config import SPECIES_LIST

log = logging.getLogger(__name__)

SPECIES_MODELS: dict[str, dict[str, Any]] = {}
FEATURE_NAMES: list[str] = []

_TRUSTED_URI_PREFIXES: tuple[str, ...] = ("./", "file://", "gs://")


def _trusted_tracking_uri() -> str:
    """Resolve + validate ``MLFLOW_TRACKING_URI`` to a trusted prefix.

    Honors ``MLFLOW_TRACKING_URI`` from the environment first (test fixtures
    use ``monkeypatch.setenv``); falls back to Pydantic Settings default.
    Raises RuntimeError on any URI that doesn't start with a known-trusted
    prefix — protects against an attacker-controlled tracking server feeding
    pickled artifacts at unpickle time.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI", settings.mlflow_tracking_uri)
    if not (
        uri.startswith(_TRUSTED_URI_PREFIXES)
        or uri == "./mlruns"
    ):
        raise RuntimeError(f"Untrusted MLFLOW_TRACKING_URI: {uri!r}")
    return uri


def _iter_json(path: str):
    """Yield every ``*.json`` file at or below ``path`` (file or dir)."""
    p = pathlib.Path(path)
    if p.is_file():
        yield p
        return
    for f in p.rglob("*.json"):
        yield f


def _load_one_species(client: MlflowClient, species: str) -> dict[str, Any] | None:
    """Resolve ``activity-{species}@production`` and load its artifacts.

    Returns the per-species bundle dict, or None if no production version
    exists (gated/un-promoted species). Raises only on hard MLflow errors
    that aren't "alias missing".
    """
    model_name = f"activity-{species}"
    try:
        version = client.get_model_version_by_alias(model_name, "production")
    except Exception as e:
        # mlflow raises a generic RestException / MlflowException with a
        # "RESOURCE_DOES_NOT_EXIST" code when the alias is unset. Treat any
        # alias-resolution failure as "no production model" — gated species
        # land here per 02-05 SUMMARY's Plan 07 contract.
        log.warning(
            "no production alias for %s: %s — skipping (model gated or unpromoted)",
            model_name,
            e,
        )
        return None

    # Calibrated sklearn artifact is the inference target; xgboost base is
    # used by SHAP TreeExplainer (calibrated wrapper hides the tree
    # structure SHAP needs). Both are logged by ml.train.train_species.
    calibrated = mlflow.sklearn.load_model(f"models:/{model_name}@production")
    base = mlflow.xgboost.load_model(f"runs:/{version.run_id}/model_{species}")

    meta_path = client.download_artifacts(version.run_id, "meta")
    meta_file = next(iter(_iter_json(meta_path)), None)
    if meta_file is None:
        raise RuntimeError(f"{model_name}: meta/*.json artifact missing")
    meta = json.loads(meta_file.read_text())
    return {
        "calibrated": calibrated,
        "base": base,
        "feature_names": meta["feature_names"],
        "model_version": meta.get("model_version", version.run_id[:12]),
        "run_id": version.run_id,
        "alias_version": version.version,
    }


def load_all_models(allow_missing: bool = True) -> None:
    """Populate ``SPECIES_MODELS`` + ``FEATURE_NAMES`` from MLflow.

    Default ``allow_missing=True`` reflects the Wave-5 reality that gated
    species exist; per the Plan 02-05 contract, the scorer must continue
    operating against the species that DID promote. Set ``allow_missing=False``
    when you want a hard fail-fast (e.g., a CI gate that requires every
    species pre-registered).
    """
    mlflow.set_tracking_uri(_trusted_tracking_uri())
    client = MlflowClient()
    global FEATURE_NAMES
    SPECIES_MODELS.clear()
    FEATURE_NAMES = []

    missing: list[str] = []
    for species in SPECIES_LIST:
        bundle = _load_one_species(client, species)
        if bundle is None:
            missing.append(species)
            continue
        # Validate cross-species feature alignment — every promoted model must
        # share the FEATURE_NAMES list (pin in train.py).
        if not FEATURE_NAMES:
            FEATURE_NAMES = list(bundle["feature_names"])
        elif FEATURE_NAMES != bundle["feature_names"]:
            raise RuntimeError(
                f"{species}: feature_names mismatch with previously-loaded species"
            )
        SPECIES_MODELS[species] = {
            k: v for k, v in bundle.items() if k != "feature_names"
        }
        log.info(
            "loaded %s (alias_version=%s, run_id=%s)",
            species,
            bundle["alias_version"],
            bundle["run_id"],
        )

    if missing and not allow_missing:
        raise RuntimeError(
            f"missing production aliases for: {missing} "
            "(set allow_missing=True or run scripts.promote_production)"
        )
    if missing:
        log.warning(
            "model.py loaded %d/%d species; missing=%s",
            len(SPECIES_MODELS),
            len(SPECIES_LIST),
            missing,
        )


def score_one(species: str, X_row: np.ndarray) -> float:
    """Single-row inference. ≤50ms on warmed-up process (M-12).

    Raises KeyError if the species has no production model loaded — callers
    (the Celery scorer) check ``species in SPECIES_MODELS`` first.
    """
    cal = SPECIES_MODELS[species]["calibrated"]
    return float(cal.predict_proba(X_row.reshape(1, -1))[0, 1])


def _maybe_load_at_import() -> None:
    """Import-time loader. Opt out via ``TIDE_LAZY_MODEL_LOAD=1``."""
    if os.environ.get("TIDE_LAZY_MODEL_LOAD") == "1":
        return
    try:
        load_all_models(allow_missing=True)
    except Exception as e:
        # Don't brick the worker on first boot — log + leave SPECIES_MODELS
        # empty. The scorer task surfaces empty-model state via its
        # ``failure`` counter on the first run.
        log.warning("model.py import-time load skipped: %s", e)


_maybe_load_at_import()


__all__ = [
    "SPECIES_MODELS",
    "FEATURE_NAMES",
    "load_all_models",
    "score_one",
]
