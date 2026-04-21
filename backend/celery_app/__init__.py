"""Celery app factory with stable beat schedule.

Task names are import-path based and STABLE — Plans 02–05 reference these exact
strings directly. Changing a task name is a schema break for operators.

Plan 01 ships with `include=[]` because the task modules don't exist yet.
Plan 05 re-adds the `include` list once `celery_app.tasks.{noaa,meteo,solunar,backup}`
exist.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings


celery_app = Celery(
    "tide",
    broker=settings.redis_url,
    backend=settings.redis_url,  # results also in Redis
    # Plan 05 wires the ingest task modules; Plan 07 adds the backup task.
    include=[
        "celery_app.tasks.noaa",
        "celery_app.tasks.meteo",
        "celery_app.tasks.solunar",
        "celery_app.tasks.backup",
    ],
)

_ingest_task_modules = (
    "celery_app.tasks.noaa",
    "celery_app.tasks.meteo",
    "celery_app.tasks.solunar",
    "celery_app.tasks.backup",
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
    # the infra shape is locked at Wave 0.
    beat_schedule={
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
            # computation helper (ingest.solunar.compute_solunar) — the Celery
            # task is named compute_solunar_task to avoid a name collision.
            "task": "celery_app.tasks.solunar.compute_solunar_task",
            "schedule": crontab(minute=0),  # top of every hour
        },
        "backup_timescaledb": {
            "task": "celery_app.tasks.backup.backup_timescaledb_to_gcs",
            "schedule": crontab(hour=4, minute=15),  # 04:15 UTC daily
        },
    },
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
        except ImportError:
            # Task module not yet present (e.g. during Plan 01 bootstrap) —
            # `include=[]` case already satisfied, skip silently.
            pass


_register_ingest_tasks()
