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
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select, text

from agent.spot_resolver import ResolvedSpot, resolve_spot
from agent.state import TideAgentState

log = logging.getLogger(__name__)

FRESHNESS_THRESHOLD = timedelta(minutes=35)
TOP_N_FALLBACK = 3

# best-of-week sweep horizon + per-species candidate cap.
_WEEK_HORIZON = timedelta(days=7)
_WEEK_CANDIDATE_LIMIT = 8
_WEEK_TOP_N = 5
_NJ_TZ = ZoneInfo("America/New_York")


def _score_slot(
    quality_score: float | None,
    local_hour: int,
    wind_speed_ms: float | None,
    precip_prob_pct: float | None,
    *,
    has_tide: bool = True,
) -> float:
    """Heuristic fishability proxy for a single forecast hour (NOT ML).

    This is an explicitly rules-based stand-in for the per-species XGBoost
    activity model. No model has been promoted (M-08/M-09 deferred to v1.x),
    so best-of-week ranks future hours with this transparent heuristic. A
    future ML-promotion phase should swap this for ``ml.model.score_one`` so
    the sweep ranks by calibrated probability instead.

    Inputs:
    - ``quality_score``: 0..1 solunar quality (the dominant term).
    - ``local_hour``: America/New_York hour-of-day (for the low-light bonus).
    - ``wind_speed_ms`` / ``precip_prob_pct``: forecast weather (may be None).
    - ``has_tide``: whether a tide forecast row joined for this hour.

    Returns a non-negative score (clamped at 0).

    Completeness preference: solunar quality is near-identical across the
    fleet at any given hour (it's astronomical), so ties are common. A slot
    missing its weather or tide forecast row takes a small penalty so a
    fully-covered slot wins the tie — the angler gets a recommendation we
    can actually back with wind + tide numbers rather than a data gap.
    """
    score = float(quality_score) if quality_score is not None else 0.0
    # Prime low-light feeding windows (dawn 5-8, dusk 17-20 local).
    if local_hour in (5, 6, 7, 8) or local_hour in (17, 18, 19, 20):
        score += 0.10
    # Wind penalty — chop kills the bite and shore access.
    if wind_speed_ms is not None:
        if wind_speed_ms > 12:
            score -= 0.30
        elif wind_speed_ms > 8:
            score -= 0.15
    # Heavy-precip penalty.
    if precip_prob_pct is not None and precip_prob_pct > 60:
        score -= 0.15
    # Completeness preference (tiebreaker) — deprioritize data gaps so the
    # winning slot always carries wind + tide we can cite.
    if wind_speed_ms is None:
        score -= 0.02
    if not has_tide:
        score -= 0.02
    return max(0.0, score)


async def _sweep_week_for_spot(
    session: Any,
    cand: dict[str, Any],
    *,
    now: datetime,
    horizon_end: datetime,
) -> dict[str, Any] | None:
    """Sweep a single spot's next-7-days forecast and return its best slot.

    One solunar query for the window, one weather-forecast query (loaded into
    an hour-keyed dict), one tide-forecast query (also hour-keyed). Then score
    each solunar hour in Python. Returns the best-scoring slot as a
    ``week_optimal`` entry dict, or ``None`` when no solunar rows exist.
    """
    sid = cand.get("station_id")
    if not sid:
        return None

    sol_rows = (
        await session.execute(
            text(
                "SELECT time, quality_score FROM solunar_values "
                "WHERE station_id = :sid AND time BETWEEN :lo AND :hi "
                "ORDER BY time"
            ),
            {"sid": sid, "lo": now, "hi": horizon_end},
        )
    ).mappings().all()
    if not sol_rows:
        return None

    # Weather forecast rows for the window, keyed by truncated hour.
    wx_rows = (
        await session.execute(
            text(
                "SELECT time, wind_speed_ms, precipitation_prob_pct, "
                "cloud_cover_pct FROM weather_observations "
                "WHERE station_id = :sid AND is_forecast = TRUE "
                "  AND time BETWEEN :lo AND :hi"
            ),
            {"sid": sid, "lo": now, "hi": horizon_end},
        )
    ).mappings().all()
    wx_by_hour: dict[datetime, Any] = {}
    for w in wx_rows:
        t = _normalize_to_utc(w["time"]).replace(minute=0, second=0, microsecond=0)
        wx_by_hour[t] = w

    # Tide forecast rows for the window, keyed by truncated hour (most-recently
    # issued prediction wins per hour).
    tide_rows = (
        await session.execute(
            text(
                "SELECT target_time, predicted_level_m, hi_lo, issued_at "
                "FROM noaa_harmonic_forecasts "
                "WHERE station_id = :sid AND target_time BETWEEN :lo AND :hi "
                "ORDER BY issued_at ASC"
            ),
            {"sid": sid, "lo": now, "hi": horizon_end},
        )
    ).mappings().all()
    tide_by_hour: dict[datetime, Any] = {}
    for tr in tide_rows:
        t = _normalize_to_utc(tr["target_time"]).replace(
            minute=0, second=0, microsecond=0
        )
        tide_by_hour[t] = tr  # later issued_at overwrites (ORDER BY ASC)

    best: dict[str, Any] | None = None
    for s in sol_rows:
        when = _normalize_to_utc(s["time"])
        hour_key = when.replace(minute=0, second=0, microsecond=0)
        local_hour = when.astimezone(_NJ_TZ).hour
        wx = wx_by_hour.get(hour_key)
        wind = wx["wind_speed_ms"] if wx else None
        precip = wx["precipitation_prob_pct"] if wx else None
        cloud = wx["cloud_cover_pct"] if wx else None
        tide = tide_by_hour.get(hour_key)
        tide_level = tide["predicted_level_m"] if tide else None
        tide_hi_lo = tide["hi_lo"] if tide else None

        score = _score_slot(
            s["quality_score"], local_hour, wind, precip,
            has_tide=tide is not None,
        )
        slot = {
            "spot_id": cand["spot_id"],
            "spot_name": cand["spot_name"],
            "station_id": sid,
            "when": when.isoformat(),
            "solunar_quality": s["quality_score"],
            "score": score,
            "tide_level_m": tide_level,
            "tide_hi_lo": tide_hi_lo,
            "wind_speed_ms": wind,
            "precip_prob_pct": precip,
            "cloud_cover_pct": cloud,
            # Carry lat/lon for the canonical pick.
            "lat": cand.get("lat"),
            "lon": cand.get("lon"),
        }
        if best is None or score > best["score"]:
            best = slot
    return best


async def _sweep_week(
    session: Any, species: str | None,
) -> list[dict[str, Any]]:
    """Run the best-of-week sweep across all candidate spots for the species.

    Returns the top ``_WEEK_TOP_N`` slots (best slot per spot), sorted by
    score DESC. Empty list when no candidates or no solunar rows in window.
    """
    candidates = await _load_candidate_spots_by_species(
        session, species, limit=_WEEK_CANDIDATE_LIMIT,
    )
    if not candidates:
        return []
    now = datetime.now(tz=timezone.utc)
    horizon_end = now + _WEEK_HORIZON
    slots: list[dict[str, Any]] = []
    for cand in candidates:
        best = await _sweep_week_for_spot(
            session, cand, now=now, horizon_end=horizon_end,
        )
        if best is not None:
            slots.append(best)
    slots.sort(key=lambda s: s["score"], reverse=True)
    return slots[:_WEEK_TOP_N]

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
    session: Any,
    station_id: str,
    *,
    target_time: datetime | None = None,
) -> dict[str, Any]:
    """Read tidal + weather + solunar values for ``station_id``.

    When ``target_time`` is ``None`` (or in the past), reads the latest
    observation rows — same behavior as the original implementation.

    When ``target_time`` is in the future (within the 7-day forecast
    horizon), reads tide level + hi/lo from ``noaa_harmonic_forecasts``
    and the matching ``solunar_values`` hour. Wind / pressure / air-temp
    fall back to the latest observation (no forecast feed wired yet),
    and water temp likewise stays on the observation row. When ANY value
    came from a forecast read, ``conditions['_forecast_for']`` is set to
    the ISO timestamp of ``target_time`` so the synthesizer can caveat.

    Returns:
        ``{"conditions": dict | None, "observed_at": datetime | None}``.
        ``observed_at`` is the freshest ``time`` across the three reads
        (used to compute ``data_age_seconds`` / ``conditions_stale`` by
        the caller). For forecast reads the caller normally overrides
        this with ``target_time`` since the freshness gauge has different
        semantics for future windows.
    """
    out: dict[str, Any] = {}
    freshest: datetime | None = None
    used_forecast = False

    # Decide whether to consult the forecast tables. We only do so when
    # ``target_time`` is strictly in the future relative to "now" — past
    # windows always read from the observation tables (the historical
    # truth, not a stale prediction).
    use_forecast = False
    if target_time is not None:
        target_time_utc = _normalize_to_utc(target_time)
        if target_time_utc > datetime.now(tz=timezone.utc):
            use_forecast = True
    else:
        target_time_utc = None

    # ── Tide / water level ────────────────────────────────────────────
    if use_forecast and target_time_utc is not None:
        # Pick the forecast row nearest target_time within ±30 min,
        # preferring the most recently issued prediction for ties.
        fc_row = (
            await session.execute(
                text(
                    "SELECT target_time, predicted_level_m, hi_lo "
                    "FROM noaa_harmonic_forecasts "
                    "WHERE station_id = :sid "
                    "  AND target_time BETWEEN :lo AND :hi "
                    "ORDER BY abs(extract(epoch FROM (target_time - :tgt))) ASC, "
                    "         issued_at DESC "
                    "LIMIT 1"
                ),
                {
                    "sid": station_id,
                    "lo": target_time_utc - timedelta(minutes=30),
                    "hi": target_time_utc + timedelta(minutes=30),
                    "tgt": target_time_utc,
                },
            )
        ).mappings().first()
        if fc_row is not None and fc_row.get("predicted_level_m") is not None:
            out["water_level_m"] = fc_row["predicted_level_m"]
            if fc_row.get("hi_lo") is not None:
                out["tide_hi_lo"] = fc_row["hi_lo"]
            if fc_row.get("target_time") is not None:
                freshest = fc_row["target_time"]
            used_forecast = True

    # Always read latest tidal_observations for water_temp / wind / current
    # (and as fallback for water_level when forecast row is missing).
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
        # Only fill water_level_m from the observation when forecast didn't
        # supply one (matrix: forecast wins for future windows, observation
        # for past/now).
        if "water_level_m" not in out and tide_row.get("water_level_m") is not None:
            out["water_level_m"] = tide_row["water_level_m"]
        for k in (
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
            if freshest is None or tide_row["time"] > freshest:
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

    # ── Solunar ───────────────────────────────────────────────────────
    sol_row = None
    if use_forecast and target_time_utc is not None:
        # Composite PK is (station_id, time) — pick the row closest to
        # target_time (typically within an hour since solunar is hourly).
        sol_row = (
            await session.execute(
                text(
                    "SELECT time, moon_phase, illumination, lunar_day, "
                    "quality_score, sunrise, sunset, "
                    "next_major_start, next_major_end, "
                    "next_minor_start, next_minor_end "
                    "FROM solunar_values WHERE station_id = :sid "
                    "ORDER BY abs(extract(epoch FROM (time - :tgt))) ASC "
                    "LIMIT 1"
                ),
                {"sid": station_id, "tgt": target_time_utc},
            )
        ).mappings().first()
        if sol_row is not None:
            used_forecast = True

    if sol_row is None:
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

    if used_forecast and target_time is not None and out:
        out["_forecast_for"] = _normalize_to_utc(target_time).isoformat()

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
    session: Any,
    candidates: list[dict[str, Any]],
    *,
    target_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Attach ``conditions`` + ``data_age_seconds`` to each candidate in-place.

    ``target_time`` (UTC, optional) is threaded through to
    ``_read_latest_conditions`` so candidates honor the user's intended
    fishing window. For future windows the freshness gauge degenerates
    (the forecast IS the data for that window), so ``data_age_seconds``
    is clamped to 0 when ``target_time`` is in the future.
    """
    now = datetime.now(tz=timezone.utc)
    is_future = target_time is not None and target_time > now
    for cand in candidates:
        station_id = cand.get("station_id")
        if not station_id:
            cand["conditions"] = None
            cand["data_age_seconds"] = None
            continue
        cond = await _read_latest_conditions(
            session, station_id, target_time=target_time,
        )
        cand["conditions"] = cond["conditions"]
        if is_future and target_time is not None:
            # Forecast read: observed_at semantics flip — the data is "for"
            # target_time, age is 0 for future, positive for past windows.
            cand["data_age_seconds"] = max(
                0.0, (now - target_time).total_seconds()
            )
        elif cond["observed_at"] is not None:
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
            "week_optimal": None,
            "data_fetcher_latency_ms": (time.perf_counter() - t0) * 1000,
        }

    location_hint = state.get("location_hint") or {}
    raw_name = state.get("location_hint_raw") or location_hint.get("spot_name")
    lat = location_hint.get("lat")
    lon = location_hint.get("lon")

    # Target time window — planner emits TZ-aware datetimes (America/New_York).
    # Normalize to UTC so downstream SQL bounds are unambiguous. When the
    # window is beyond the 7-day forecast horizon, fall back to "latest
    # observation" (no forecast rows will exist that far out).
    target_time_raw = state.get("time_window_start")
    target_time: datetime | None = None
    if target_time_raw is not None:
        target_time = _normalize_to_utc(target_time_raw)
        horizon = datetime.now(tz=timezone.utc) + timedelta(days=7)
        if target_time > horizon:
            target_time = None  # too far — degrade to latest observation

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
        "week_optimal": None,
    }

    async with async_session_factory() as session:
        # ── best-of-week: sweep the 7-day forecast across all candidates ──
        if intent == "best-of-week":
            week_optimal = await _sweep_week(session, species)
            if week_optimal:
                winner = week_optimal[0]
                update["week_optimal"] = week_optimal
                update["spot_id"] = winner["spot_id"]
                update["spot_name"] = winner["spot_name"]
                update["spot_lat"] = winner.get("lat")
                update["spot_lon"] = winner.get("lon")
                # Build a conditions dict from the winning forecast slot so
                # downstream confidence + rendering see grounded values.
                conds: dict[str, Any] = {
                    "water_level_m": winner.get("tide_level_m"),
                    "solunar_quality_score": winner.get("solunar_quality"),
                    "wind_speed_ms": winner.get("wind_speed_ms"),
                    "precipitation_prob_pct": winner.get("precip_prob_pct"),
                    "cloud_cover_pct": winner.get("cloud_cover_pct"),
                    "_forecast_for": winner["when"],
                }
                # Drop None entries so the synthesizer doesn't render blanks.
                update["conditions"] = {
                    k: v for k, v in conds.items() if v is not None
                }
                update["data_age_seconds"] = 0
                update["conditions_stale"] = False
                # ML best-effort on the winning spot (no model promoted at MVP).
                if species:
                    score_row = await _read_latest_activity_score(
                        session, winner["spot_id"], species,
                    )
                    if score_row["score"] is not None:
                        update["ml_score"] = score_row["score"]
                        update["shap_top3"] = score_row["shap_top3"]
                        update["ml_score_available"] = True
                update["data_fetcher_latency_ms"] = (
                    (time.perf_counter() - t0) * 1000
                )
                return update
            # No candidates / no solunar rows in window: fall through to the
            # existing best-of-all behavior (don't crash, don't fabricate).
            log.info(
                "data_fetcher: best-of-week sweep empty for species=%s; "
                "falling back to best-of-all", species,
            )
            intent = "best-of-all"

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
            await _enrich_candidates_with_conditions(
                session, candidates, target_time=target_time,
            )
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
            # For future windows the forecast IS the data — staleness flag
            # should stay False (the enrich helper already clamped age to 0).
            now_for_stale = datetime.now(tz=timezone.utc)
            is_future_window = (
                target_time is not None and target_time > now_for_stale
            )
            if (
                not is_future_window
                and update["data_age_seconds"] is not None
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
                cond = await _read_latest_conditions(
                    session, station_id, target_time=target_time,
                )
                update["conditions"] = cond["conditions"]
                now_utc = datetime.now(tz=timezone.utc)
                is_future_window = (
                    target_time is not None and target_time > now_utc
                )
                if is_future_window and target_time is not None:
                    # Forecast read: age is 0 for future windows, positive
                    # for past. Staleness gate is bypassed (the forecast IS
                    # the data for that window).
                    age = max(0.0, (now_utc - target_time).total_seconds())
                    update["data_age_seconds"] = age
                elif cond["observed_at"] is not None:
                    t_obs_utc = _normalize_to_utc(cond["observed_at"])
                    age = (now_utc - t_obs_utc).total_seconds()
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
    "_score_slot",
    "_read_latest_activity_score",
    "_topn_fallback",
    "_fresh_score_one_spot",
    "_summarize_conditions",
    "_shap_top3_names",
]
