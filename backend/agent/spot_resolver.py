"""Fishing-spot resolution: fuzzy name match → haversine fallback → no-pin top-N.

D-05 contract:
1. spot_name fuzzy match via rapidfuzz.process.extractOne(scorer=WRatio,
   score_cutoff=settings.rapidfuzz_threshold). Threshold locked in Wave 0
   benchmark (see 03-WAVE0-NOTES.md). Default 65 (Wave-0 verified 17/20 @ 65
   vs 13/20 @ the prior D-05.1 default of 80).
2. lat/lon fallback: haversine ≤ 5 km nearest neighbor against the 30 seeded
   spots.
3. No-pin fallback: caller queries top-N scored spots universe-wide.

PATTERN: module-level singleton + lazy-load-at-import (mirrors ml.model._SPECIES_MODELS).
The 30 spots change rarely (manual seed); reload requires app restart.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Literal

from rapidfuzz import fuzz, process
from sqlalchemy import select

from app.config import settings

log = logging.getLogger(__name__)

ResolutionStrategy = Literal["fuzzy_name", "haversine", "no_pin", "none"]


# Acronym/nickname → canonical-expansion map. Pre-translated through this
# table before the rapidfuzz match so short-token nicknames (e.g. "IBSP")
# can resolve to a verbose canonical spot name (e.g. "Island Beach State Park
# — A7 Pocket") that WRatio with cutoff=settings.rapidfuzz_threshold (65)
# cannot otherwise reach. Conservative entries only — IBSP is the verified
# motivating case from the "barnegat inlet vs IBSP for fluke" comparison
# prompt. Do not invent acronyms.
_ACRONYM_EXPANSIONS: dict[str, str] = {
    "ibsp": "Island Beach State Park",
    "ibspark": "Island Beach State Park",
    "i.b.s.p.": "Island Beach State Park",
}

# Punctuation we strip when tokenizing for the acronym lookup. Period is
# intentionally preserved inside the token (so "i.b.s.p." survives intact
# as a single token and matches the map key).
_ACRONYM_TOKEN_SEPARATORS = (",", ";", ":", "!", "?", "(", ")", "[", "]", "/", "\\", '"', "'")


def _maybe_expand_acronyms(query: str) -> str:
    """Replace whole-token acronyms with their canonical expansion.

    Case-insensitive whole-token match only — a free-text query like
    "IBSP surf in IBSP" expands both tokens; an embedded substring like
    "myIBSPplan" is left alone. The original casing of non-matching tokens
    is preserved.
    """
    if not query:
        return query
    # Normalize punctuation to spaces so tokens split cleanly.
    work = query
    for sep in _ACRONYM_TOKEN_SEPARATORS:
        work = work.replace(sep, " ")
    tokens = work.split()
    if not tokens:
        return query
    out: list[str] = []
    changed = False
    for tok in tokens:
        key = tok.lower()
        expansion = _ACRONYM_EXPANSIONS.get(key)
        if expansion is not None:
            out.append(expansion)
            changed = True
        else:
            out.append(tok)
    return " ".join(out) if changed else query


@dataclass(frozen=True)
class ResolvedSpot:
    spot_id: int | None
    spot_name: str | None
    lat: float | None
    lon: float | None
    strategy: ResolutionStrategy


# Module-level cache; populated at import unless opted out via TIDE_LAZY_SPOT_LOAD=1.
_SPOTS: list[dict[str, Any]] = []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Standard formula; no external dep needed."""
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _load_all_spots_sync() -> list[dict[str, Any]]:
    """Sync load of all FishingSpot rows. Used at import time only.

    Uses a sync engine to avoid mixing event loops at import time. The
    spot_resolver module is imported by FastAPI startup AND by the Celery
    worker boot — both paths must work.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from db.models import FishingSpot

    engine = create_engine(settings.database_sync_url, pool_pre_ping=True)
    try:
        with Session(engine) as s:
            rows = s.execute(select(FishingSpot)).scalars().all()
            return [
                {
                    "id": r.spot_id,
                    "name": r.name,
                    "lat": float(r.lat),
                    "lon": float(r.lon),
                }
                for r in rows
            ]
    finally:
        engine.dispose()


def _maybe_load_at_import() -> None:
    if os.environ.get("TIDE_LAZY_SPOT_LOAD") == "1":
        log.info("spot_resolver: TIDE_LAZY_SPOT_LOAD=1, deferring spot load")
        return
    try:
        _SPOTS.extend(_load_all_spots_sync())
        log.info("spot_resolver: loaded %d spots at import", len(_SPOTS))
    except Exception as e:
        log.warning("spot_resolver: deferred load due to error: %s", e)


_maybe_load_at_import()


def reset_for_test(spots: list[dict[str, Any]]) -> None:
    """Test hook — replace _SPOTS with a known fixture set."""
    _SPOTS.clear()
    _SPOTS.extend(spots)


def resolve_spot(
    query: str | None,
    lat: float | None = None,
    lon: float | None = None,
) -> ResolvedSpot:
    """Return the best ResolvedSpot for a (query, lat, lon) triple.

    Algorithm per D-05:
    1. If `query` non-empty: rapidfuzz WRatio match against _SPOTS names with
       score_cutoff=settings.rapidfuzz_threshold (default 65 — Wave 0 A4 verified
       17/20 @ 65 vs 13/20 @ 80; D-05.1 originally 80, lowered to 65). On hit:
       strategy="fuzzy_name".
    2. Else / no fuzzy hit, and lat+lon present: haversine nearest neighbor;
       if distance ≤ 5 km, strategy="haversine".
    3. Else: strategy="no_pin" (caller does top-N fallback) or strategy="none"
       if no input at all.
    """
    if not _SPOTS:
        log.warning(
            "spot_resolver: _SPOTS empty — call reset_for_test or check DB load"
        )

    # Path 1: fuzzy name
    if query and query.strip():
        # Pre-translate well-known acronyms/nicknames (e.g. "IBSP" →
        # "Island Beach State Park") so WRatio with the locked cutoff of
        # settings.rapidfuzz_threshold (65) can find the canonical spot.
        # Only the fuzzy-match input is rewritten; the verbatim user query
        # still goes to other consumers (RAG, logging).
        expanded = _maybe_expand_acronyms(query.strip())
        names = [s["name"] for s in _SPOTS]
        match = process.extractOne(
            expanded,
            names,
            scorer=fuzz.WRatio,
            score_cutoff=settings.rapidfuzz_threshold,
        )
        if match is not None:
            _matched_name, _score, idx = match
            spot = _SPOTS[idx]
            return ResolvedSpot(
                spot_id=spot["id"],
                spot_name=spot["name"],
                lat=spot["lat"],
                lon=spot["lon"],
                strategy="fuzzy_name",
            )

    # Path 2: haversine fallback
    if lat is not None and lon is not None and _SPOTS:
        best: tuple[float, dict[str, Any]] | None = None
        for s in _SPOTS:
            d = _haversine_km(lat, lon, s["lat"], s["lon"])
            if best is None or d < best[0]:
                best = (d, s)
        if best is not None and best[0] <= 5.0:
            spot = best[1]
            return ResolvedSpot(
                spot_id=spot["id"],
                spot_name=spot["name"],
                lat=spot["lat"],
                lon=spot["lon"],
                strategy="haversine",
            )

    # Path 3: nothing matched
    if (query and query.strip()) or (lat is not None and lon is not None):
        return ResolvedSpot(None, None, None, None, "no_pin")
    return ResolvedSpot(None, None, None, None, "none")
