"""Health router — explicitly NOT gated on data freshness.

K8s / compose / Cloud Run liveness probes must return 200 as long as the
process is running and able to service HTTP. If we gated this on the
freshness of the ingest pipeline, a stalled NOAA feed would kill the pod
and cascade into further availability loss instead of just 503-ing
``/conditions`` (which is the intended failure mode — see Plan 06 plan
``must_haves.truths`` and threat T-01-06-04).
"""

from __future__ import annotations

from fastapi import APIRouter


router = APIRouter()


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


__all__ = ["router"]
