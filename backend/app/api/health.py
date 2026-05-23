"""REL-01 readiness probe — ``/healthz`` exposes the L-05 4-field shape.

This module is the Phase 5 Wave 1 (plan 05-02) replacement for the
historical liveness stub. The previous shape (``{"status":"ok"}`` HTTP 200
no matter what) was a Cloud Run liveness signal. Phase 5 promotes /healthz
to a *readiness* probe: it returns 503 when any of {data freshness, Qdrant
connectivity, model load} is degraded. GCP Cloud Run does NOT use a K8s-
style liveness probe (which would kill the pod on 503), so 503 is safe and
informative — it tells the LB to take this instance out of the rotation
without restarting it.

Historical rationale paragraph (kept for context — see Phase 1 threat
T-01-06-04): the original /healthz was deliberately NOT gated on data
freshness because a K8s liveness probe gating on freshness would cascade
ingest failures into pod restarts. We preserved that invariant by giving
``/conditions/{station_id}`` its own per-route freshness gate. With Cloud
Run as the deploy target, /healthz can safely report 503 on degradation
without losing the pod.

Response shape (L-05):

    {
        "ts_lag_seconds": int,    # seconds since freshest CAGG row;
                                  # -1 if the DB query raised
        "qdrant_ok": bool,        # client.get_collections() succeeded
        "model_loaded": bool,     # lifespan handler flipped the flag
        "status": "ok" | "degraded"
    }

HTTP status: 200 when status="ok", 503 when status="degraded".

Pitfall P3 mitigation: ``Cache-Control: no-store`` is set as the first
line of the handler — load balancers and proxies MUST NOT cache the result
or they'll keep serving stale 200s after the underlying service degrades.

Pitfall P8 mitigation: the ``model_loaded`` flag is flipped by the FastAPI
lifespan handler at startup (``app/main.py``), NOT lazily on first request.
This makes /healthz an honest startup signal even before the first
``/api/v1/query`` arrives.

Pitfall P4 mitigation: NO labels on the freshness query (this is an
aggregate over all stations — RESEARCH §Q4 line 367). The single
``ts_lag_seconds`` value collapses 9 NOAA stations into one freshness
signal. Per-station freshness is exposed separately by the per-route
``data_age_seconds`` gauge in ``ingest.metrics``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps.db import get_session
from qdrant.client import get_qdrant


log = logging.getLogger(__name__)

router = APIRouter()


# Threshold = 30 minutes (1800 s). Matches D-10 data freshness target
# (RESEARCH §Q4 line 402). Aligned with the per-station freshness gate
# (FRESHNESS_THRESHOLD=35 min in app/deps/freshness.py) but slightly
# tighter — /healthz reports degraded earlier than the route does so the
# LB can pull the instance before user-facing 503s start firing.
FRESHNESS_THRESHOLD_SECONDS = 1800


# Module-level mutable state. We use a dict (not a global bool) because
# ``global`` rebinding inside test monkeypatches doesn't play well with
# import-cached module references, while ``dict.__setitem__`` mutates the
# same object the importers already hold.
_MODEL_LOADED_FLAG: dict[str, bool] = {"loaded": False}


def mark_model_loaded() -> None:
    """Flip the model_loaded flag to True. Called by the lifespan handler
    in ``app/main.py`` once the Phase 2 model registry warmup succeeds."""
    _MODEL_LOADED_FLAG["loaded"] = True


def reset_model_loaded_for_tests() -> None:
    """Reset the model_loaded flag to False. Test-only — production code
    should never call this."""
    _MODEL_LOADED_FLAG["loaded"] = False


@router.get("/healthz", include_in_schema=False)
async def healthz(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Pitfall P3 — FIRST line. No path downstream may forget this header.
    response.headers["Cache-Control"] = "no-store"

    # ─── 1) Freshness probe — aggregate MAX(bucket) across all stations ───
    # NOTE: NO WHERE clause (RESEARCH §Q4 line 367) — /healthz reports the
    # freshest row anywhere in the system. Per-station freshness is the
    # /conditions/{station_id} route's job.
    ts_lag: int
    try:
        result = await session.execute(
            text("SELECT EXTRACT(EPOCH FROM (NOW() - MAX(bucket))) FROM conditions_15min")
        )
        row = result.first()
        raw = row[0] if row is not None else None
        # raw is None when conditions_15min is empty — treat as worst-case stale.
        ts_lag = int(raw) if raw is not None else -1
    except (SQLAlchemyError, Exception) as e:  # noqa: BLE001
        # Pitfall: a single broken DB query must not 500 /healthz — it must
        # 503 with ts_lag_seconds=-1 so the LB can act.
        log.warning("healthz: ts_lag probe failed: %s", e)
        ts_lag = -1

    # ─── 2) Qdrant readiness ─────────────────────────────────────────────
    qdrant_ok = False
    try:
        await get_qdrant().get_collections()
        qdrant_ok = True
    except Exception as e:  # noqa: BLE001 — any failure means not ready
        log.warning("healthz: qdrant probe failed: %s", e)
        qdrant_ok = False

    # ─── 3) Model load flag (lifespan-driven; Pitfall P8) ────────────────
    model_loaded = _MODEL_LOADED_FLAG["loaded"]

    # ─── 4) Compose the L-05 status decision ─────────────────────────────
    status = (
        "ok"
        if (
            ts_lag >= 0
            and ts_lag < FRESHNESS_THRESHOLD_SECONDS
            and qdrant_ok
            and model_loaded
        )
        else "degraded"
    )

    if status == "degraded":
        response.status_code = 503

    return {
        "ts_lag_seconds": ts_lag,
        "qdrant_ok": qdrant_ok,
        "model_loaded": model_loaded,
        "status": status,
    }


__all__ = [
    "router",
    "mark_model_loaded",
    "reset_model_loaded_for_tests",
    "FRESHNESS_THRESHOLD_SECONDS",
]
