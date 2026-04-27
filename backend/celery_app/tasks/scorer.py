"""Per-spot × per-species XGBoost scorer Celery task (M-11).

Beat schedule: every 15 minutes (aligned with NOAA + feature freshness).
Writes one ``ActivityScore`` row per (spot, species) tuple, with SHAP top-3
in ``shap_values`` JSONB and the full feature vector in ``raw_payload``
(D-09 replayability).

Task name is import-path-based and STABLE — do not rename
(``celery_app/__init__.py`` task-name convention).

Per the Plan 02-05 contract (``data/model_registry_report.json``), gated
species (no production-aliased model in MLflow) are skipped at score time;
the task surfaces them in the ``failure`` count rather than crashing.

Confidence label rule (Open Question #4):
- ``high`` if ≥3 prior ActivityScore rows for spot+species in last 72h
- ``moderate`` if ≥1 prior ActivityScore row in last 7d
- ``low`` otherwise
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from celery_app import celery_app
from db import session as db_session
from db.models import ActivityScore, FishingSpot

log = logging.getLogger(__name__)

# Open Question #4 — confidence label thresholds. These count prior scored
# rows as a proxy for "reports" (the Phase 2 corpus is not yet wired into
# the live scorer; once the corpus produces labels in Phase 5, this can
# pivot to count fishing_reports rows directly).
CONF_HIGH_MIN_REPORTS = 3
CONF_HIGH_WINDOW_HOURS = 72
CONF_MOD_WINDOW_DAYS = 7


@celery_app.task(name="celery_app.tasks.scorer.score_all_spots", bind=True)
def score_all_spots(self) -> dict:
    """Beat-scheduled per-species scorer. Delegates to the async helper.

    Returns ``{"success": int, "failure": int, "duration_ms": int}`` so the
    Phase 5 LLMOps dashboards can monitor scorer health without hitting MLflow.
    """
    return asyncio.run(_score_all_async())


async def _confidence_label(
    session, spot_id: int, species: str, now: datetime
) -> str:
    """Return ``high`` / ``moderate`` / ``low`` per Open Question #4.

    Uses prior ActivityScore counts (is_forecast=False) within the two time
    windows. Initially every (spot, species) returns ``low`` because the
    table is empty; the first cohort of writes seeds future ticks.
    """
    cutoff_72h = now - timedelta(hours=CONF_HIGH_WINDOW_HOURS)
    cutoff_7d = now - timedelta(days=CONF_MOD_WINDOW_DAYS)
    count_72h = (
        await session.execute(
            select(func.count())
            .select_from(ActivityScore)
            .where(ActivityScore.spot_id == spot_id)
            .where(ActivityScore.species == species)
            .where(ActivityScore.is_forecast.is_(False))
            .where(ActivityScore.time >= cutoff_72h)
        )
    ).scalar_one()
    if count_72h >= CONF_HIGH_MIN_REPORTS:
        return "high"
    count_7d = (
        await session.execute(
            select(func.count())
            .select_from(ActivityScore)
            .where(ActivityScore.spot_id == spot_id)
            .where(ActivityScore.species == species)
            .where(ActivityScore.is_forecast.is_(False))
            .where(ActivityScore.time >= cutoff_7d)
        )
    ).scalar_one()
    if count_7d >= 1:
        return "moderate"
    return "low"


async def _score_all_async() -> dict[str, Any]:
    """Load spots → build features in one batch → per-species predict + SHAP → write rows."""
    # Imports are deferred so worker boot doesn't hard-fail when ml.model's
    # MLflow load encounters a transient registry hiccup. Per Plan 02-05
    # contract: scoreboard remains operable for promoted species even when
    # gated species are absent from SPECIES_MODELS.
    from ml.features import FEATURE_NAMES, build_features_for_rows
    from ml.model import SPECIES_MODELS
    from ml.shap_utils import top_k_shap
    from ml.species_config import SPECIES_LIST

    now = datetime.now(timezone.utc)
    written = 0
    failed = 0
    started = _time.perf_counter()

    async with db_session.async_session_factory() as session:
        spots = (await session.execute(select(FishingSpot))).scalars().all()
        if not spots:
            log.warning("no spots in fishing_spots table — nothing to score")
            return {"success": 0, "failure": 0, "duration_ms": 0}
        spot_type_by_id = {s.spot_id: (s.spot_type or "flat") for s in spots}
        # FishingSpot uses ``nearest_station`` (FK to noaa_stations); the
        # feature builder expects ``station_id`` keying so map it explicitly.
        station_id_by_spot = {s.spot_id: s.nearest_station for s in spots}

        # Build features for every (spot, species) tuple at the same `now`.
        feature_rows = [
            (s.spot_id, now, species) for s in spots for species in SPECIES_LIST
        ]
        try:
            features_df = await build_features_for_rows(
                session,
                feature_rows,
                spot_type_by_id=spot_type_by_id,
                station_id_by_spot=station_id_by_spot,
            )
        except Exception as e:
            log.exception("feature build failed: %s", e)
            return {
                "success": 0,
                "failure": len(feature_rows),
                "error": str(e)[:200],
            }

    # Separate write session — the read session above closes before we open a
    # write transaction. session.merge() on (spot_id, species, time) composite
    # PK gives us idempotency on retry: the same `now` overwrites prior rows.
    async with db_session.async_session_factory() as write_session:
        for _, row in features_df.iterrows():
            species = row["species"]
            bundle = SPECIES_MODELS.get(species)
            if bundle is None:
                # Gated / unpromoted species per Plan 02-05 — log + skip.
                # Counts as a failure so the metric surface tells the truth.
                failed += 1
                log.warning(
                    "no production model for species=%s spot=%s — skipping (gated)",
                    species,
                    row["spot_id"],
                )
                continue
            try:
                calibrated = bundle["calibrated"]
                base = bundle["base"]
                model_version = bundle["model_version"]
                feat_arr = row[FEATURE_NAMES].to_numpy(dtype=float)
                score = float(
                    calibrated.predict_proba(feat_arr.reshape(1, -1))[0, 1]
                )
                shap_top = top_k_shap(base, feat_arr, FEATURE_NAMES, k=3)
                confidence = await _confidence_label(
                    write_session, int(row["spot_id"]), species, now
                )
                # session.merge(ActivityScore(...)) — composite-PK upsert.
                await write_session.merge(ActivityScore(
                    spot_id=int(row["spot_id"]),
                    species=species,
                    time=now,
                    score=score,
                    shap_values={"top_features": shap_top},
                    model_version=model_version,
                    confidence=confidence,
                    is_forecast=False,
                    raw_payload={
                        "features": {k: float(row[k]) for k in FEATURE_NAMES},
                        "model_run_id": bundle.get("run_id"),
                    },
                ))
                written += 1
            except SQLAlchemyError as e:
                failed += 1
                log.exception(
                    "db write failed spot=%s species=%s: %s",
                    row["spot_id"],
                    species,
                    e,
                )
            except Exception as e:
                failed += 1
                log.exception(
                    "score failed spot=%s species=%s: %s",
                    row["spot_id"],
                    species,
                    e,
                )
        try:
            await write_session.commit()
        except Exception as e:
            log.exception("commit failed: %s", e)
            failed += written
            written = 0

    duration_ms = int((_time.perf_counter() - started) * 1000)
    log.info(
        "score_all_spots done: success=%d failed=%d duration_ms=%d",
        written,
        failed,
        duration_ms,
    )
    return {"success": written, "failure": failed, "duration_ms": duration_ms}


__all__ = ["score_all_spots", "_score_all_async"]
