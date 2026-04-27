"""Data Fetcher node — spot resolution + conditions read + ML score.

NO LLM. Pure DB + ML.

Behavior contracts:

- D-02.3: TimescaleDB lookups are <50 ms each; no caching at this layer
  (the freshness gate from Phase 1 already enforces ≤30 min cadence).
- A-09: empty ``SPECIES_MODELS`` or species not in dict ⇒
  ``ml_score_available=False``; do not raise.
- D-03.2: ``data_age > 35 min`` ⇒ ``conditions_stale=True``; do not 503.
- D-05.3: ``strategy='no_pin'`` ⇒ top-N (=3) scored spots universe-wide;
  the highest is selected as ``spot_id``.
- P-06: XGBoost inference per spot ≤ 50 ms.

Read source: ``activity_scores`` (composite PK ``(spot_id, species, time)``)
is the canonical store written by the Celery beat scorer every 15 min
(see ``backend/celery_app/tasks/scorer.py``). The Data Fetcher reads the
LATEST row for the (spot, species) pair — features live in
``raw_payload['features']``, SHAP in ``shap_values['top_features']``.

ML signature note (deviation from PLAN.md ``<interfaces>``): the
Phase-2 ``ml.model.score_one(species, X_row)`` signature takes a numpy
row and returns a single float. SHAP comes from ``ml.shap_utils.top_k_shap``.
This module reuses the persisted (score, shap) pair when fresh — the
Celery scorer recomputed them ≤ 15 min ago by contract — and only
re-runs ``score_one`` when forced (a feature gate kept off at MVP).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select

from agent.spot_resolver import ResolvedSpot, resolve_spot
from agent.state import TideAgentState

log = logging.getLogger(__name__)

FRESHNESS_THRESHOLD = timedelta(minutes=35)
TOP_N_FALLBACK = 3

# Whitelist of conditions fields surfaced to the SSE wire (T-03-02-03):
# the raw ``raw_payload['features']`` jsonb has ~45 columns; we expose a
# small, stable subset for UI display.
_CONDITIONS_WHITELIST: tuple[str, ...] = (
    "tide_height_m",
    "tide_phase",
    "wind_speed_mps",
    "wind_speed_ms",
    "wind_dir_deg",
    "pressure_hpa",
    "pressure_mb",
    "pressure_delta_3h",
    "water_temp_c",
    "solunar_quality",
    "solunar_score",
)


def _summarize_conditions(raw_payload: Any) -> dict[str, Any]:
    """Pluck the whitelisted fields from a persisted feature payload.

    The scorer writes ``raw_payload = {"features": {<FEATURE_NAMES → float>},
    "model_run_id": ...}``. We surface only the small UI-relevant subset
    so downstream SSE events stay compact and don't leak the full feature
    vector (T-03-02-03 information disclosure mitigation).
    """
    if not isinstance(raw_payload, dict):
        return {}
    features = raw_payload.get("features")
    if not isinstance(features, dict):
        return {}
    return {k: features[k] for k in _CONDITIONS_WHITELIST if k in features}


def _shap_top3_names(shap_values: Any) -> list[str] | None:
    """Extract a list of 3 feature names from the persisted SHAP payload.

    Scorer wrote ``shap_values = {"top_features": [{"feature": ..., "value": ...}, ...]}``.
    We return just the names (the Synthesizer is told *which* features
    drove the score; values are kept server-side for now).
    """
    if not isinstance(shap_values, dict):
        return None
    top = shap_values.get("top_features")
    if not isinstance(top, list):
        # Permissive: also handle {"top3": [...names]} legacy shape if it exists.
        legacy = shap_values.get("top3")
        if isinstance(legacy, list):
            return [str(x) for x in legacy[:3]]
        return None
    names: list[str] = []
    for entry in top[:3]:
        if isinstance(entry, dict) and "feature" in entry:
            names.append(str(entry["feature"]))
        elif isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, (list, tuple)) and entry:
            names.append(str(entry[0]))
    return names or None


async def _read_latest_activity_score(
    session: Any,
    spot_id: int,
    species: str | None,
) -> dict[str, Any]:
    """Read the latest ``ActivityScore`` row for a (spot, species) pair.

    Returns a dict with ``score``, ``shap_top3``, ``time``, ``conditions``,
    ``raw_payload``. All keys may be ``None`` when no row exists.
    """
    from db.models import ActivityScore

    stmt = select(ActivityScore).where(ActivityScore.spot_id == spot_id)
    if species:
        stmt = stmt.where(ActivityScore.species == species)
    stmt = stmt.order_by(desc(ActivityScore.time)).limit(1)

    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return {
            "score": None,
            "shap_top3": None,
            "time": None,
            "conditions": None,
            "raw_payload": None,
        }

    return {
        "score": float(row.score) if row.score is not None else None,
        "shap_top3": _shap_top3_names(row.shap_values),
        "time": row.time,
        "conditions": _summarize_conditions(row.raw_payload),
        "raw_payload": row.raw_payload,
    }


async def _read_spot_meta(session: Any, spot_id: int) -> dict[str, Any] | None:
    """Read FishingSpot metadata for the resolved spot_id."""
    from db.models import FishingSpot

    row = (
        await session.execute(
            select(FishingSpot).where(FishingSpot.spot_id == spot_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "name": row.name,
        "lat": float(row.lat),
        "lon": float(row.lon),
    }


async def _topn_fallback(
    session: Any, species: str | None, n: int = TOP_N_FALLBACK,
) -> int | None:
    """Top-scored spot id for the species (D-05.3 no-pin fallback).

    Picks the highest-scoring spot in the most recent activity_scores window.
    """
    from db.models import ActivityScore

    stmt = select(ActivityScore.spot_id, ActivityScore.score).order_by(
        desc(ActivityScore.score)
    )
    if species:
        stmt = stmt.where(ActivityScore.species == species)
    stmt = stmt.limit(n)
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None
    # rows is a list of Row objects; first column is spot_id.
    return int(rows[0][0])


async def _fresh_score_one_spot(
    session: Any, spot_id: int, species: str,
) -> tuple[float | None, list[str] | None]:
    """OPTIONAL: re-run ``score_one`` on the persisted feature vector.

    The Celery scorer recomputed (score, shap) ≤ 15 min ago — for MVP we
    prefer the persisted score and only force a fresh re-inference when a
    future plan hands us new conditions. Returns ``(None, None)`` when the
    species is not in ``SPECIES_MODELS`` (A-09 graceful path).

    Defensively imported so tests that monkeypatch ``ml.model`` see the
    patched dict, and so the import does not crash the data fetcher when
    the ml package is unavailable in some lightweight unit envs.
    """
    try:
        import numpy as np

        from ml.features import FEATURE_NAMES
        from ml.model import SPECIES_MODELS, score_one
    except Exception as e:  # pragma: no cover — dep-availability guard
        log.warning("data_fetcher: ml import failed: %s", e)
        return (None, None)

    if species not in SPECIES_MODELS:
        return (None, None)

    from db.models import ActivityScore

    row = (
        await session.execute(
            select(ActivityScore)
            .where(
                ActivityScore.spot_id == spot_id,
                ActivityScore.species == species,
            )
            .order_by(desc(ActivityScore.time))
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or not isinstance(row.raw_payload, dict):
        return (None, None)
    features = row.raw_payload.get("features")
    if not isinstance(features, dict):
        return (None, None)
    if not FEATURE_NAMES:
        return (None, None)
    try:
        x_row = np.array(
            [float(features.get(k, 0.0) or 0.0) for k in FEATURE_NAMES],
            dtype=float,
        )
        score = score_one(species, x_row)
        return (float(score), _shap_top3_names(row.shap_values))
    except Exception as e:
        log.warning(
            "data_fetcher: score_one failed for spot=%s species=%s: %s",
            spot_id, species, e,
        )
        return (None, None)


def _normalize_to_utc(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


async def data_fetcher_node(state: TideAgentState) -> dict[str, Any]:
    """Resolve spot → read conditions + score → set graceful flags.

    Returns a partial state-update dict. Never raises for missing-model
    or stale-data conditions — those are signalled via flags.
    """
    from db.session import async_session_factory

    t0 = time.perf_counter()
    species = state.get("species_canonical")
    location_hint = state.get("location_hint") or {}
    raw_name = state.get("location_hint_raw") or location_hint.get("spot_name")
    lat = location_hint.get("lat")
    lon = location_hint.get("lon")

    resolved: ResolvedSpot = resolve_spot(raw_name, lat, lon)
    update: dict[str, Any] = {
        "spot_resolution_strategy": resolved.strategy,
        "spot_id": resolved.spot_id,
        "spot_name": resolved.spot_name,
        "spot_lat": resolved.lat,
        "spot_lon": resolved.lon,
        # Defaults — adjusted below as we discover state.
        "ml_score_available": False,
        "conditions_stale": False,
        "conditions": None,
        "ml_score": None,
        "shap_top3": None,
        "data_age_seconds": None,
    }

    async with async_session_factory() as session:
        # No-pin fallback (D-05.3): pick the top-scored spot for the species.
        if resolved.spot_id is None and resolved.strategy == "no_pin":
            fb_id = await _topn_fallback(session, species)
            if fb_id is not None:
                update["spot_id"] = fb_id
                meta = await _read_spot_meta(session, fb_id)
                if meta is not None:
                    update["spot_name"] = meta["name"]
                    update["spot_lat"] = meta["lat"]
                    update["spot_lon"] = meta["lon"]

        if update.get("spot_id") is not None:
            # Conditions + persisted score for the resolved (spot, species).
            data = await _read_latest_activity_score(
                session, update["spot_id"], species,
            )
            update["conditions"] = data["conditions"]

            persisted_score = data["score"]
            persisted_shap = data["shap_top3"]
            t_score = data["time"]
            if t_score is not None:
                t_score_utc = _normalize_to_utc(t_score)
                age = (datetime.now(tz=timezone.utc) - t_score_utc).total_seconds()
                update["data_age_seconds"] = age
                if age > FRESHNESS_THRESHOLD.total_seconds():
                    update["conditions_stale"] = True
                    log.warning(
                        "data_fetcher: conditions stale (age=%.0fs) for spot=%s",
                        age, update["spot_id"],
                    )

            if species:
                # Persisted score is the canonical Phase-3 source. Only
                # fall back to fresh score_one when persisted is missing
                # AND a model is loaded for the species.
                if persisted_score is not None:
                    update["ml_score"] = persisted_score
                    update["shap_top3"] = persisted_shap
                    update["ml_score_available"] = True
                else:
                    fresh_t0 = time.perf_counter()
                    fresh_score, fresh_shap = await _fresh_score_one_spot(
                        session, update["spot_id"], species,
                    )
                    xgb_ms = (time.perf_counter() - fresh_t0) * 1000
                    log.debug(
                        "data_fetcher: ml fresh-inference %.1fms spot=%s species=%s",
                        xgb_ms, update["spot_id"], species,
                    )
                    if fresh_score is not None:
                        update["ml_score"] = fresh_score
                        update["shap_top3"] = fresh_shap
                        update["ml_score_available"] = True
                    else:
                        # A-09: graceful — species missing from
                        # SPECIES_MODELS or no data available.
                        update["ml_score_available"] = False
            else:
                # No species requested → conditions only, no ML score.
                update["ml_score_available"] = False

    update["data_fetcher_latency_ms"] = (time.perf_counter() - t0) * 1000
    return update


__all__ = [
    "FRESHNESS_THRESHOLD",
    "TOP_N_FALLBACK",
    "data_fetcher_node",
    "_read_latest_activity_score",
    "_topn_fallback",
    "_fresh_score_one_spot",
    "_summarize_conditions",
    "_shap_top3_names",
]
