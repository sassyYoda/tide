"""``/conditions/{station_id}`` route — gated on :func:`require_fresh_conditions`.

The route reads from four places and stitches a :class:`ConditionsResponse`:

- ``conditions_15min`` CAGG (Plan 02) — latest bucket for sensor averages
- ``weather_observations`` (Plan 05) — latest row for pressure-trend values
  (stored under ``raw_payload['_pressure_trend']`` because Plan 02's schema
  does not yet have typed columns for those fields; Plan 05 summary Known
  Stubs §"Pressure-trend output" documents the deferral)
- ``solunar_values`` (Plan 05) — latest hour's solunar snapshot
- ``noaa_stations`` (Plan 03 seed) — station master (name lookup)

All four are joined by ``station_id``. The CAGG read is the authoritative
``observed_at``; the other three are best-effort (None on missing row).

Phase 1 deferral — ``TidalBlock.next_high`` / ``next_low`` fields remain
``None`` in this route; Phase 3's LangGraph agent will populate them from
``noaa_harmonic_forecasts`` (already pre-staged by Plan 05). Reserving
the schema keys now means Phase 3 can populate without a breaking change.
See 01-RESEARCH.md Open Question #2 (RESOLVED: deferred).

Threat mitigations in-file:

- T-01-06-01 (station_id tampering) — ``text(...)`` with named bind only;
  no string concat. 404 if the station is unknown.
- T-01-06-03 (DB hammer) — route is gated by the freshness dependency,
  which micro-caches; only one CAGG MAX(bucket) query per ~10s per
  station.
- T-01-06-06 (LKG surfacing) — this route reads ONLY from the CAGG + the
  regular observation tables; LKG keys are never queried here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.db import get_session
from app.deps.freshness import require_fresh_conditions
from app.models.response import (
    ConditionsResponse,
    ErrorEnvelope,
    SolunarBlock,
    TidalBlock,
    WeatherBlock,
)


router = APIRouter()


# Four small CTEs joined onto the stations master (no cross-station work
# happens inside a single request — all filters bind :station_id). Values
# for the pressure-trend fields live under raw_payload['_pressure_trend']
# because Plan 02's weather_observations does not have typed columns for
# them; Plan 05 summary documents this as an intentional schema deferral.
_CONDITIONS_QUERY = text(
    """
    WITH latest AS (
        SELECT
            c.station_id,
            c.bucket,
            c.water_level_m,
            c.water_temp_c,
            c.wind_speed_ms,
            -- CAGG column is wind_dir_deg; alias to the API-contract name.
            c.wind_dir_deg              AS wind_direction_deg,
            c.surface_pressure_hpa,
            c.air_temperature_c,
            -- CAGG does NOT expose precipitation_mm — only precipitation_prob_pct.
            c.precipitation_prob_pct,
            c.cloud_cover_pct
        FROM conditions_15min c
        WHERE c.station_id = :station_id
        ORDER BY c.bucket DESC
        LIMIT 1
    ),
    trend AS (
        SELECT
            (raw_payload #>> '{_pressure_trend,pressure_delta_1h}')::float8
                AS pressure_delta_1h,
            (raw_payload #>> '{_pressure_trend,pressure_delta_3h}')::float8
                AS pressure_delta_3h,
            (raw_payload #>> '{_pressure_trend,pressure_delta_6h}')::float8
                AS pressure_delta_6h,
            (raw_payload #>> '{_pressure_trend,pressure_trend_label}')
                AS pressure_trend_label
        FROM weather_observations
        WHERE station_id = :station_id
        ORDER BY time DESC
        LIMIT 1
    ),
    sol AS (
        SELECT
            moon_phase,
            illumination,
            lunar_day,
            sunrise,
            sunset,
            next_major_start,
            next_major_end,
            next_minor_start,
            next_minor_end,
            quality_score
        FROM solunar_values
        WHERE station_id = :station_id
        ORDER BY time DESC
        LIMIT 1
    ),
    st AS (
        SELECT station_id, name FROM noaa_stations WHERE station_id = :station_id
    )
    SELECT
        st.station_id AS st_station_id,
        st.name       AS station_name,
        l.water_level_m,
        l.water_temp_c,
        l.wind_speed_ms,
        l.wind_direction_deg,
        l.surface_pressure_hpa,
        l.air_temperature_c,
        l.precipitation_prob_pct,
        l.cloud_cover_pct,
        t.pressure_delta_1h,
        t.pressure_delta_3h,
        t.pressure_delta_6h,
        t.pressure_trend_label,
        s.moon_phase,
        s.illumination,
        s.lunar_day,
        s.sunrise,
        s.sunset,
        s.next_major_start,
        s.next_major_end,
        s.next_minor_start,
        s.next_minor_end,
        s.quality_score
    FROM st
    LEFT JOIN latest l ON l.station_id = st.station_id
    LEFT JOIN trend  t ON TRUE
    LEFT JOIN sol    s ON TRUE
    """
)


@router.get(
    "/conditions/{station_id}",
    response_model=ConditionsResponse,
    responses={
        503: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
    },
)
async def get_conditions(
    station_id: str,
    latest_bucket: datetime = Depends(require_fresh_conditions),
    session: AsyncSession = Depends(get_session),
) -> ConditionsResponse:
    """Return the freshest conditions snapshot for ``station_id``."""
    result = await session.execute(
        _CONDITIONS_QUERY, {"station_id": station_id}
    )
    row = result.mappings().first()

    # station unknown → 404 (404/503 split per RESEARCH §12)
    if row is None or row.get("st_station_id") is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "station_not_found",
                "message": f"Station {station_id} unknown",
            },
        )

    now = datetime.now(timezone.utc)
    age_seconds = int((now - latest_bucket).total_seconds())

    return ConditionsResponse(
        station_id=row["st_station_id"],
        station_name=row["station_name"],
        observed_at=latest_bucket,
        data_age_seconds=age_seconds,
        tidal=TidalBlock(
            current_level_m=row.get("water_level_m"),
            water_temp_c=row.get("water_temp_c"),
            # Phase 2 will classify the tidal phase from the harmonic curve.
            phase="unknown",
            # next_high / next_low INTENTIONALLY None at Phase 1 — Plan 05
            # pre-stages data in noaa_harmonic_forecasts; Phase 3 LangGraph
            # agent populates these from that table. See 01-RESEARCH.md
            # Open Question #2 (RESOLVED: deferred).
            next_high=None,
            next_high_level_m=None,
            next_low=None,
            next_low_level_m=None,
        ),
        weather=WeatherBlock(
            wind_speed_ms=row.get("wind_speed_ms"),
            wind_direction_deg=row.get("wind_direction_deg"),
            surface_pressure_hpa=row.get("surface_pressure_hpa"),
            pressure_delta_1h=row.get("pressure_delta_1h"),
            pressure_delta_3h=row.get("pressure_delta_3h"),
            pressure_delta_6h=row.get("pressure_delta_6h"),
            pressure_trend_label=row.get("pressure_trend_label"),
            air_temperature_c=row.get("air_temperature_c"),
            # precipitation_prob_pct is now sourced from the CAGG, which
            # propagates it from weather_observations (Plan 05 ingest now
            # populates the column from Open-Meteo's hourly forecast).
            precipitation_prob_pct=row.get("precipitation_prob_pct"),
            cloud_cover_pct=row.get("cloud_cover_pct"),
        ),
        solunar=SolunarBlock(
            moon_phase=row.get("moon_phase") or 0.0,
            illumination=row.get("illumination") or 0.0,
            lunar_day=row.get("lunar_day") or 0.0,
            next_major_start=row.get("next_major_start"),
            next_major_end=row.get("next_major_end"),
            next_minor_start=row.get("next_minor_start"),
            next_minor_end=row.get("next_minor_end"),
            quality_score=row.get("quality_score") or 0.0,
        ),
        sunrise=row.get("sunrise"),
        sunset=row.get("sunset"),
    )


__all__ = ["router"]
