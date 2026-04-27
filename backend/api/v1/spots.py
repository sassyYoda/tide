"""GET /api/v1/spots — scored spots within a bbox + optional species filter (API-02).

Read path:

1. Parse the bbox query string (``lat1,lon1,lat2,lon2``); 422 if malformed.
2. SELECT ``fishing_spots`` rows whose ``(lat, lon)`` lie inside the bbox.
3. For each spot: SELECT the latest non-forecast ``activity_scores`` row
   (filtered by species if provided). Compute ``data_age_seconds`` against
   ``datetime.now(UTC)``.
4. Return ``[]`` when the bbox matches nothing or the score table is empty.

This is a PURE DB read — no agent, no LLM, no rate limit (the map UI calls
this for every pan/zoom; rate limiting it would defeat the demo's purpose).

CORS preflight is handled by ``CORSMiddleware`` registered in
``app.main.create_app()`` for both this route and ``/api/v1/query``.

NOTE on the FishingSpot ORM (deviation from PLAN.md ``<action>`` example):
the model uses ``spot_id`` (NOT ``id``) as its primary key column. The
seed factory in tests must include the required NOT NULL columns
``water_body``, ``spot_type``, ``access_type``, ``species``, and
``nearest_station`` (FK to noaa_stations).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.db import get_session
from db.models import ActivityScore, FishingSpot

log = logging.getLogger(__name__)

router = APIRouter()


class SpotScore(BaseModel):
    """One row of the /api/v1/spots response.

    ``score`` / ``confidence`` / ``species`` / ``last_score_time`` /
    ``data_age_seconds`` are ``None`` when the spot exists in the bbox but
    has no scoring rows (cold spot — Celery scorer hasn't reached it yet).
    """

    spot_id: int
    name: str
    lat: float
    lon: float
    score: float | None = None
    confidence: str | None = None
    species: str | None = None
    last_score_time: datetime | None = None
    data_age_seconds: float | None = None


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    """Parse 'lat1,lon1,lat2,lon2' → 4-tuple of floats. 422 on any malformation.

    Required: lat1 ≤ lat2 and lon1 ≤ lon2 (south-west corner first).
    """
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(
            status_code=422, detail="bbox must be 'lat1,lon1,lat2,lon2'"
        )
    try:
        lat1, lon1, lat2, lon2 = (float(x) for x in parts)
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail="bbox values must be numbers"
        ) from e
    if lat1 > lat2 or lon1 > lon2:
        raise HTTPException(
            status_code=422,
            detail="bbox: lat1 <= lat2 and lon1 <= lon2 required",
        )
    return lat1, lon1, lat2, lon2


@router.get("/spots", response_model=list[SpotScore])
async def list_spots(
    bbox: str = Query(..., description="lat1,lon1,lat2,lon2"),
    species: str | None = Query(None, max_length=32),
    hours_ahead: int = Query(0, ge=0, le=48),
    session: AsyncSession = Depends(get_session),
) -> list[SpotScore]:
    """Return scored spots within bbox.

    ``hours_ahead`` reserved for future forecast use; Phase 3 returns current
    scores only (forecast support is v1.x).
    """
    lat1, lon1, lat2, lon2 = _parse_bbox(bbox)

    spots_stmt = select(FishingSpot).where(
        and_(
            FishingSpot.lat >= lat1,
            FishingSpot.lat <= lat2,
            FishingSpot.lon >= lon1,
            FishingSpot.lon <= lon2,
        )
    )
    spots: list[Any] = list((await session.execute(spots_stmt)).scalars().all())
    if not spots:
        return []

    out: list[SpotScore] = []
    now = datetime.now(tz=timezone.utc)
    for spot in spots:
        score_stmt = (
            select(ActivityScore)
            .where(
                ActivityScore.spot_id == spot.spot_id,
                ActivityScore.is_forecast.is_(False),
            )
        )
        if species:
            score_stmt = score_stmt.where(ActivityScore.species == species)
        score_stmt = score_stmt.order_by(desc(ActivityScore.time)).limit(1)
        row = (await session.execute(score_stmt)).scalar_one_or_none()

        if row is None:
            out.append(
                SpotScore(
                    spot_id=spot.spot_id,
                    name=spot.name,
                    lat=float(spot.lat),
                    lon=float(spot.lon),
                    score=None,
                    confidence=None,
                    species=None,
                    last_score_time=None,
                    data_age_seconds=None,
                )
            )
        else:
            t = (
                row.time
                if row.time.tzinfo is not None
                else row.time.replace(tzinfo=timezone.utc)
            )
            out.append(
                SpotScore(
                    spot_id=spot.spot_id,
                    name=spot.name,
                    lat=float(spot.lat),
                    lon=float(spot.lon),
                    score=float(row.score) if row.score is not None else None,
                    confidence=row.confidence,
                    species=row.species,
                    last_score_time=t,
                    data_age_seconds=(now - t).total_seconds(),
                )
            )
    return out


__all__ = ["router", "SpotScore"]
