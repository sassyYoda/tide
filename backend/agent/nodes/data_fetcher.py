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

Read sources (decoupled — see Phase 6 post-launch fix):
- Conditions come from the raw observation tables — ``tidal_observations``,
  ``weather_observations``, ``solunar_values`` — keyed by
  ``fishing_spots.nearest_station``. ``data_age_seconds`` is derived from
  the freshest observation row across the three feeds.
- ML score + SHAP still come from ``activity_scores`` written by the
  ``score_all_spots`` Celery task. When no production model is loaded for
  the species (Phase 2 M-08/M-09 promotion deferred to v1.x), no
  ``ActivityScore`` rows exist; ``ml_score_available`` flips False but
  ``conditions`` still surfaces live readings.

ML signature note (deviation from PLAN.md ``<interfaces>``): the
Phase-2 ``ml.model.score_one(species, X_row)`` signature takes a numpy
row and returns a single float. SHAP comes from ``ml.shap_utils.top_k_shap``.
This module reuses the persisted (score, shap) pair when fresh and only
re-runs ``score_one`` when forced (a feature gate kept off at MVP).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select, text

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

    ``conditions`` is retained on this dict for legacy callers / tests, but
    ``data_fetcher_node`` no longer treats it as the canonical conditions
    source — that role moved to ``_read_latest_conditions`` so a missing ML
    model can't blank out live environmental readings.
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


# Fields surfaced to the synthesizer prompt. Keep narrow + named the way an
# angler would read them so the LLM doesn't have to translate column names.
async def _read_latest_conditions(
    session: Any, station_id: str,
) -> dict[str, Any]:
    """Read latest tidal + weather + solunar values directly for ``station_id``.

    Returns a dict with two keys:

    - ``conditions``: flat dict of human-readable fields (or ``None`` when no
      data exists for the station yet).
    - ``observed_at``: the freshest ``time`` across the three reads — used to
      compute ``data_age_seconds`` and the ``conditions_stale`` flag.

    Implementation: three small ORDER BY time DESC LIMIT 1 reads (one per
    feed). Each is a single index seek on (station_id, time DESC) — cheap
    enough that we don't need the ``conditions_15min`` CAGG here.
    """
    out: dict[str, Any] = {}
    freshest: datetime | None = None

    tide_row = (
        await session.execute(
            text(
                "SELECT time, water_level_m, water_temp_c, wind_speed_ms, "
                "wind_dir_deg, current_speed_ms, current_dir_deg "
                "FROM tidal_observations WHERE station_id = :sid "
                "ORDER BY time DESC LIMIT 1"
            ),
            {"sid": station_id},
        )
    ).mappings().first()
    if tide_row is not None:
        for k in (
            "water_level_m",
            "water_temp_c",
            "current_speed_ms",
            "current_dir_deg",
        ):
            if tide_row.get(k) is not None:
                out[k] = tide_row[k]
        # Wind from NOAA when present takes precedence over Open-Meteo
        # because the gauge is co-located with the station vs. interpolated.
        if tide_row.get("wind_speed_ms") is not None:
            out["wind_speed_ms"] = tide_row["wind_speed_ms"]
        if tide_row.get("wind_dir_deg") is not None:
            out["wind_dir_deg"] = tide_row["wind_dir_deg"]
        if tide_row.get("time") is not None:
            freshest = tide_row["time"]

    weather_row = (
        await session.execute(
            text(
                "SELECT time, wind_speed_ms, wind_dir_deg, surface_pressure_hpa, "
                "temperature_2m_c, precipitation_prob_pct, cloud_cover_pct "
                "FROM weather_observations WHERE station_id = :sid "
                "ORDER BY time DESC LIMIT 1"
            ),
            {"sid": station_id},
        )
    ).mappings().first()
    if weather_row is not None:
        # Fill wind only when NOAA didn't supply it (gauge-vs-interpolated).
        if (
            weather_row.get("wind_speed_ms") is not None
            and "wind_speed_ms" not in out
        ):
            out["wind_speed_ms"] = weather_row["wind_speed_ms"]
        if (
            weather_row.get("wind_dir_deg") is not None
            and "wind_dir_deg" not in out
        ):
            out["wind_dir_deg"] = weather_row["wind_dir_deg"]
        for src, dst in (
            ("surface_pressure_hpa", "surface_pressure_hpa"),
            ("temperature_2m_c", "air_temperature_c"),
            ("precipitation_prob_pct", "precipitation_prob_pct"),
            ("cloud_cover_pct", "cloud_cover_pct"),
        ):
            if weather_row.get(src) is not None:
                out[dst] = weather_row[src]
        if weather_row.get("time") is not None:
            if freshest is None or weather_row["time"] > freshest:
                freshest = weather_row["time"]

    sol_row = (
        await session.execute(
            text(
                "SELECT time, moon_phase, illumination, lunar_day, "
                "quality_score, sunrise, sunset, "
                "next_major_start, next_major_end, "
                "next_minor_start, next_minor_end "
                "FROM solunar_values WHERE station_id = :sid "
                "ORDER BY time DESC LIMIT 1"
            ),
            {"sid": station_id},
        )
    ).mappings().first()
    if sol_row is not None:
        for k in ("moon_phase", "illumination", "lunar_day"):
            if sol_row.get(k) is not None:
                out[k] = sol_row[k]
        if sol_row.get("quality_score") is not None:
            out["solunar_quality_score"] = sol_row["quality_score"]
        for k in (
            "sunrise",
            "sunset",
            "next_major_start",
            "next_major_end",
            "next_minor_start",
            "next_minor_end",
        ):
            if sol_row.get(k) is not None:
                out[k] = sol_row[k].isoformat()
        if sol_row.get("time") is not None:
            if freshest is None or sol_row["time"] > freshest:
                freshest = sol_row["time"]

    return {
        "conditions": out or None,
        "observed_at": freshest,
    }


async def _read_spot_station(session: Any, spot_id: int) -> str | None:
    """Return the ``nearest_station`` for ``spot_id``, or None if unknown."""
    from db.models import FishingSpot

    row = (
        await session.execute(
            select(FishingSpot.nearest_station).where(
                FishingSpot.spot_id == spot_id
            )
        )
    ).first()
    if row is None:
        return None
    return str(row[0]) if row[0] is not None else None


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

    Primary path: highest-scoring spot in the most recent ``activity_scores``
    window. When no model has been promoted (Phase 2 M-08/M-09 deferred),
    ``activity_scores`` is empty; fall back to any ``fishing_spots`` row that
    lists the species, ordered by ``spot_id`` so the choice is deterministic.
    """
    from db.models import ActivityScore, FishingSpot

    stmt = select(ActivityScore.spot_id, ActivityScore.score).order_by(
        desc(ActivityScore.score)
    )
    if species:
        stmt = stmt.where(ActivityScore.species == species)
    stmt = stmt.limit(n)
    rows = (await session.execute(stmt)).all()
    if rows:
        return int(rows[0][0])

    # Pre-promotion fallback — pick a deterministic spot that lists the species.
    spot_stmt = select(FishingSpot.spot_id).order_by(FishingSpot.spot_id)
    if species:
        spot_stmt = spot_stmt.where(FishingSpot.species.any(species))
    spot_stmt = spot_stmt.limit(1)
    spot_row = (await session.execute(spot_stmt)).first()
    if spot_row is None:
        return None
    return int(spot_row[0])


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


async def _load_candidate_spots_by_species(
    session: Any, species: str | None, limit: int = 5,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` deterministic fishing_spots rows for the species.

    Each row: ``{spot_id, name, lat, lon, station_id}``. Caller fetches
    conditions per-row. Order is ``spot_id ASC`` so behavior is reproducible.
    """
    from db.models import FishingSpot

    stmt = select(
        FishingSpot.spot_id,
        FishingSpot.name,
        FishingSpot.lat,
        FishingSpot.lon,
        FishingSpot.nearest_station,
    ).order_by(FishingSpot.spot_id)
    if species:
        stmt = stmt.where(FishingSpot.species.any(species))
    stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "spot_id": int(r[0]),
            "spot_name": r[1],
            "lat": float(r[2]),
            "lon": float(r[3]),
            "station_id": r[4],
        })
    return out


async def _fuzzy_resolve_each(
    session: Any, names: list[str], species: str | None,
) -> list[dict[str, Any]]:
    """Resolve each name string to a fishing_spots row via the spot resolver.

    Names that fail to resolve are dropped (logged as warnings). Returns
    a list of ``{spot_id, spot_name, lat, lon, station_id}`` dicts. Order
    follows input order.
    """
    out: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for name in names:
        if not name or not name.strip():
            continue
        res: ResolvedSpot = resolve_spot(name)
        if res.spot_id is None or res.spot_id in seen_ids:
            log.info("data_fetcher: compare candidate '%s' did not resolve", name)
            continue
        seen_ids.add(res.spot_id)
        station_id = await _read_spot_station(session, res.spot_id)
        out.append({
            "spot_id": res.spot_id,
            "spot_name": res.spot_name,
            "lat": res.lat,
            "lon": res.lon,
            "station_id": station_id,
            "user_query_term": name,
        })
    return out


async def _enrich_candidates_with_conditions(
    session: Any, candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach ``conditions`` + ``data_age_seconds`` to each candidate in-place."""
    now = datetime.now(tz=timezone.utc)
    for cand in candidates:
        station_id = cand.get("station_id")
        if not station_id:
            cand["conditions"] = None
            cand["data_age_seconds"] = None
            continue
        cond = await _read_latest_conditions(session, station_id)
        cand["conditions"] = cond["conditions"]
        if cond["observed_at"] is not None:
            t_obs = _normalize_to_utc(cond["observed_at"])
            cand["data_age_seconds"] = (now - t_obs).total_seconds()
        else:
            cand["data_age_seconds"] = None
    return candidates


async def data_fetcher_node(state: TideAgentState) -> dict[str, Any]:
    """Resolve spot(s) → read conditions + score → set graceful flags.

    Branches on ``state['intent']``:
    - ``definition``: skip spot/conditions read entirely (RAG-only path).
    - ``comparison``: resolve every name in ``compare_locations_raw`` and
      fetch per-spot conditions. The first successfully resolved candidate
      becomes the canonical ``spot_id`` for the SSE payload; the synthesizer
      sees the full list and ranks.
    - ``best-of-all``: fetch up to 5 candidate fishing_spots for the species,
      one canonical pick (lowest spot_id) surfaced for the payload.
    - default (``fishing-recommendation``): single-spot resolve, with a
      no-pin / "none" fallback that fires whenever the resolver returns no
      spot AND a species was supplied.

    Returns a partial state-update dict. Never raises — missing-model /
    stale-conditions / unresolved-spot cases are signalled via flags.
    """
    from db.session import async_session_factory

    t0 = time.perf_counter()
    intent = state.get("intent") or "fishing-recommendation"
    species = state.get("species_canonical")

    # Definition queries skip the entire DB read path — they're answered
    # from the RAG corpus + general knowledge by the synthesizer.
    if intent == "definition":
        return {
            "spot_resolution_strategy": "none",
            "spot_id": None,
            "spot_name": None,
            "spot_lat": None,
            "spot_lon": None,
            "ml_score_available": False,
            "conditions_stale": False,
            "conditions": None,
            "ml_score": None,
            "shap_top3": None,
            "data_age_seconds": None,
            "candidate_spots": None,
            "data_fetcher_latency_ms": (time.perf_counter() - t0) * 1000,
        }

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
        "candidate_spots": None,
    }

    async with async_session_factory() as session:
        # ── Multi-spot intents resolve candidates first ──────────────────
        candidates: list[dict[str, Any]] = []
        if intent == "comparison":
            names = state.get("compare_locations_raw") or []
            if names:
                candidates = await _fuzzy_resolve_each(session, names, species)
        elif intent == "best-of-all":
            candidates = await _load_candidate_spots_by_species(
                session, species, limit=5,
            )
            for c in candidates:
                c["user_query_term"] = None

        if candidates:
            await _enrich_candidates_with_conditions(session, candidates)
            update["candidate_spots"] = candidates
            # First candidate becomes the canonical pick for the SSE
            # payload + freshness gauge. Synthesizer prompt then ranks all
            # candidates explicitly in its text output.
            primary = candidates[0]
            update["spot_id"] = primary["spot_id"]
            update["spot_name"] = primary["spot_name"]
            update["spot_lat"] = primary["lat"]
            update["spot_lon"] = primary["lon"]
            update["conditions"] = primary.get("conditions")
            update["data_age_seconds"] = primary.get("data_age_seconds")
            if (
                update["data_age_seconds"] is not None
                and update["data_age_seconds"] > FRESHNESS_THRESHOLD.total_seconds()
            ):
                update["conditions_stale"] = True
            # ML score path is best-effort even for multi-spot; only run
            # when a species was supplied. The persisted-score read is cheap
            # (single PK lookup) and falls back to a fresh score if needed.
            if species:
                score_row = await _read_latest_activity_score(
                    session, primary["spot_id"], species,
                )
                if score_row["score"] is not None:
                    update["ml_score"] = score_row["score"]
                    update["shap_top3"] = score_row["shap_top3"]
                    update["ml_score_available"] = True
            update["data_fetcher_latency_ms"] = (
                (time.perf_counter() - t0) * 1000
            )
            return update

        # ── Single-spot path (fishing-recommendation default + no-pin) ───
        # No-pin fallback (D-05.3): pick a spot for the species when the
        # resolver could not. Triggers on either "no_pin" (query string
        # supplied but didn't fuzzy-match) or "none" (no query string at
        # all — happens when planner extracted location_hint_raw=null).
        if (
            resolved.spot_id is None
            and resolved.strategy in ("no_pin", "none")
            and species is not None
        ):
            fb_id = await _topn_fallback(session, species)
            if fb_id is not None:
                update["spot_id"] = fb_id
                meta = await _read_spot_meta(session, fb_id)
                if meta is not None:
                    update["spot_name"] = meta["name"]
                    update["spot_lat"] = meta["lat"]
                    update["spot_lon"] = meta["lon"]

        if update.get("spot_id") is not None:
            # Conditions come from the raw observation tables (decoupled from
            # ActivityScore so a missing ML model can't blank them out).
            station_id = await _read_spot_station(session, update["spot_id"])
            if station_id is not None:
                cond = await _read_latest_conditions(session, station_id)
                update["conditions"] = cond["conditions"]
                if cond["observed_at"] is not None:
                    t_obs_utc = _normalize_to_utc(cond["observed_at"])
                    age = (
                        datetime.now(tz=timezone.utc) - t_obs_utc
                    ).total_seconds()
                    update["data_age_seconds"] = age
                    if age > FRESHNESS_THRESHOLD.total_seconds():
                        update["conditions_stale"] = True
                        log.warning(
                            "data_fetcher: conditions stale (age=%.0fs) station=%s",
                            age, station_id,
                        )

            # Persisted score (ML) — independent of conditions read above.
            data = await _read_latest_activity_score(
                session, update["spot_id"], species,
            )
            persisted_score = data["score"]
            persisted_shap = data["shap_top3"]

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
