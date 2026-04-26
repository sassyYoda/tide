"""Hybrid retrieval with RRF fusion + recency decay (R-06, R-07, R-08, R-09)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    DatetimeRange,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchAny,
    MatchValue,
    Prefetch,
    SparseVector,
)

from qdrant.schema import (
    COLLECTION_NAME,
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
)

# R-08 recency bands
RECENCY_MULT: list[tuple[timedelta, float]] = [
    (timedelta(hours=24), 1.00),
    (timedelta(hours=72), 0.80),
    (timedelta(weeks=1), 0.60),
    (timedelta(days=30), 0.40),
]
DEFAULT_FALLBACK = 0.20

# R-07 hard cutoff (pre-filter — applied at Qdrant)
DATE_FILTER_WINDOW = timedelta(days=30)


def recency_multiplier(report_date: datetime, now: datetime) -> float:
    """R-08 — age-based multiplier bands."""
    age = now - report_date
    for threshold, mult in RECENCY_MULT:
        if age <= threshold:
            return mult
    return DEFAULT_FALLBACK


def _build_filter(
    species: str,
    location_region: str | None,
    cutoff: datetime,
) -> Filter:
    must: list[FieldCondition] = [
        FieldCondition(key="species_mentioned", match=MatchAny(any=[species])),
        FieldCondition(key="date", range=DatetimeRange(gte=cutoff.isoformat())),
    ]
    if location_region:
        must.append(
            FieldCondition(key="location_region", match=MatchValue(value=location_region))
        )
    return Filter(must=must)


async def hybrid_retrieve(
    client: AsyncQdrantClient,
    dense_vec: list[float],
    sparse_vec: SparseVector,
    species: str,
    location_region: str | None = None,
    top_k: int = 5,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Returns top-k list of {id, score_adjusted, score_raw, payload}.

    score_adjusted = RRF_score * recency_multiplier (post-fusion re-rank).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - DATE_FILTER_WINDOW
    q_filter = _build_filter(species, location_region, cutoff)
    resp = await client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            Prefetch(query=dense_vec, using=DENSE_VECTOR_NAME, limit=20, filter=q_filter),
            Prefetch(query=sparse_vec, using=SPARSE_VECTOR_NAME, limit=20, filter=q_filter),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        query_filter=q_filter,
        limit=top_k * 3,
        with_payload=True,
    )
    adjusted: list[tuple[float, Any]] = []
    for p in resp.points:
        payload = p.payload or {}
        date_str = payload.get("date")
        if not date_str:
            continue
        try:
            report_date = datetime.fromisoformat(date_str)
            if report_date.tzinfo is None:
                report_date = report_date.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        mult = recency_multiplier(report_date, now)
        adjusted.append((p.score * mult, p))
    adjusted.sort(key=lambda t: -t[0])
    return [
        {
            "id": str(p.id),
            "score_raw": float(p.score),
            "score_adjusted": float(adj),
            "payload": dict(p.payload or {}),
        }
        for adj, p in adjusted[:top_k]
    ]


__all__ = [
    "RECENCY_MULT",
    "DEFAULT_FALLBACK",
    "DATE_FILTER_WINDOW",
    "recency_multiplier",
    "hybrid_retrieve",
]
