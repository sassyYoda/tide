"""Celery app factory with stable beat schedule.

Task names are import-path based and STABLE — Plans 02–05 reference these exact
strings directly. Changing a task name is a schema break for operators.

Plan 05 wires the `include=[...]` list since
`celery_app.tasks.{noaa,meteo,solunar,backup}` now exist. The
`_register_ingest_tasks` helper preserves the Plan 01 bootstrap ergonomics
(being tolerant of a genuinely-missing module file during early plan work)
but narrows the exception handler to `ModuleNotFoundError` so that a real
ImportError inside an existing task module (bad transitive import, syntax
error surfacing as ImportError, etc.) surfaces instead of being swallowed.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

from app.config import settings


# Phase 6 plan 06-04 — Pitfall P12 gate. Cloud Run Jobs (NOAA/Open-Meteo/solunar)
# own the ingest cron in production; when this env flag is truthy the VM-side
# Celery beat MUST drop those 3 entries so we never double-fire (polluting
# Prometheus counters + wasting NOAA's polite-use API budget). Read at module
# import time so a single env mutation cleanly toggles the schedule shape.
_INGEST_VIA_CLOUD_RUN_JOBS = os.environ.get(
    "TIDE_INGEST_VIA_CLOUD_RUN_JOBS", ""
).lower() in ("1", "true", "yes")


celery_app = Celery(
    "tide",
    broker=settings.redis_url,
    backend=settings.redis_url,  # results also in Redis
    # Plan 05 wires the ingest task modules; Plan 07 adds the backup task.
    # Phase 2 Plan 07 adds the per-15-min ML scorer.
    include=[
        "celery_app.tasks.noaa",
        "celery_app.tasks.meteo",
        "celery_app.tasks.solunar",
        "celery_app.tasks.backup",
        "celery_app.tasks.scorer",
        "celery_app.tasks.qdrant_snapshot",
    ],
)

_ingest_task_modules = (
    "celery_app.tasks.noaa",
    "celery_app.tasks.meteo",
    "celery_app.tasks.solunar",
    "celery_app.tasks.backup",
    "celery_app.tasks.scorer",
    "celery_app.tasks.qdrant_snapshot",
)

# Phase 6 plan 06-04 — Pitfall P12. Backup/snapshot/scorer ALWAYS run on the
# VM beat (Cloud Run Jobs do NOT own them). Ingest entries are appended only
# when the env-flag is unset/falsy; production sets it via the Cloud Run Jobs
# env so the beat skips ingest and the Scheduler cron is the sole driver.
_beat_schedule: dict[str, dict] = {
    "backup_timescaledb": {
        "task": "celery_app.tasks.backup.backup_timescaledb_to_gcs",
        "schedule": crontab(hour=4, minute=15),  # 04:15 UTC daily
    },
    # Phase 5 Plan 02 — REL-04 daily Qdrant snapshot. Fires 15 min BEFORE
    # the pg_dump backup so the two heavy disk operations stagger.
    "snapshot_qdrant": {
        "task": "celery_app.tasks.qdrant_snapshot.snapshot_fishing_reports",
        "schedule": crontab(hour=4, minute=0),  # 04:00 UTC daily
    },
    # Phase 2 Plan 07 — per-spot × per-species ML scorer (M-11).
    # Cadence aligns with NOAA + feature freshness budget.
    "score_all_spots": {
        "task": "celery_app.tasks.scorer.score_all_spots",
        "schedule": crontab(minute="*/15"),
    },
}
if not _INGEST_VIA_CLOUD_RUN_JOBS:
    _beat_schedule.update(
        {
            "poll_noaa_stations": {
                "task": "celery_app.tasks.noaa.poll_noaa_stations",
                "schedule": crontab(minute="*/15"),  # every 15 min on the dot
            },
            "poll_open_meteo": {
                "task": "celery_app.tasks.meteo.poll_open_meteo",
                "schedule": crontab(minute="*/30"),
            },
            "compute_solunar": {
                # Plan 05 disambiguates the task function name from the pure
                # computation helper (ingest.solunar.compute_solunar) — the
                # Celery task is named compute_solunar_task to avoid a name
                # collision.
                "task": "celery_app.tasks.solunar.compute_solunar_task",
                "schedule": crontab(minute=0),  # top of every hour
            },
        }
    )

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,  # requeue if worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # fair dispatch for slow I/O tasks
    broker_connection_retry_on_startup=True,
    task_default_queue="tide",
    # STABLE TASK NAMES — Phase 2 imports these directly.
    # Tasks themselves are added in Plan 05; the schedule is scaffolded here so
    # the infra shape is locked at Wave 0. The 6-vs-3 entry shape is gated on
    # TIDE_INGEST_VIA_CLOUD_RUN_JOBS above (Pitfall P12).
    beat_schedule=_beat_schedule,
)


def _register_ingest_tasks() -> None:
    """Eagerly import the Plan 05 ingest task modules so their decorators
    register the tasks on ``celery_app.tasks`` at ``from celery_app import
    celery_app`` time — not just when the Celery worker bootstraps. This
    makes ``'celery_app.tasks.noaa.poll_noaa_stations' in celery_app.tasks``
    true in plain Python shells / unit tests / the orchestrator's verify
    snippet.
    """
    import importlib

    for mod in _ingest_task_modules:
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            # WR-04: only swallow "the module file is genuinely absent"
            # (Plan 01 bootstrap case). Any other ImportError — e.g. a
            # misspelled import inside an existing task module or a missing
            # transitive dependency — MUST propagate so Celery bootstrap
            # fails loudly rather than silently failing to register the task.
            continue


_register_ingest_tasks()
