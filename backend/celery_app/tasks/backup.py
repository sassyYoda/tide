"""REL-03 / INFRA-04 — nightly pg_dump backup task → GCS.

The Celery beat schedule (``celery_app/__init__.py``) fires this task daily at
04:15 UTC. Each run:

1. Shell out to ``pg_dump --format=custom --no-owner --no-acl`` against the
   Tide Timescale database using the sync (libpq-compatible) DSN.
2. Upload the resulting dump to the configured GCS bucket under
   ``timescaledb/tide_<UTC-timestamp>.sql``.
3. Delete the local dump file (T-01-07-01 — never leave dump artefacts on
   worker disk).

Design notes:

- The subprocess arguments are a fixed list (no shell interpolation) — the
  bucket name is passed to ``storage.Client().bucket(name)``, a Python SDK
  call, not a shell token (T-01-07-02).
- ``subprocess.run(..., check=True)`` raises ``CalledProcessError`` on a
  non-zero exit, which propagates to Celery and logs visibly (T-01-07-05).
- If ``settings.gcs_backup_bucket`` is empty the task is a no-op returning a
  ``"skipped"`` marker string. This is the local-dev / no-cloud posture
  (Compose runs without GCS credentials).
- ``_dsn_for_pg_dump`` strips the SQLAlchemy ``+psycopg2`` driver suffix so
  the DSN is a plain libpq connection string — pg_dump does not understand
  the SQLAlchemy dialect prefix.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.cloud import storage

from app.config import settings
from celery_app import celery_app


logger = logging.getLogger(__name__)


# Phase 6 / plan 06-02 — GCS-side retention window for pg_dump snapshots.
# 7 days mirrors the tide-pgdump bucket lifecycle policy (terraform/modules/gcs).
# Application-side pruning here is belt-and-suspenders: if the GCS lifecycle
# rule is mis-applied or disabled, this keeps the bucket inside the 5 GB GCS
# free tier (Pitfall A5). Mirrors qdrant_snapshot._prune_old_snapshots (local-fs).
PGDUMP_RETENTION_DAYS = 7
PGDUMP_GCS_PREFIX = "timescaledb/"


def _prune_old_gcs_blobs(bucket_name: str, prefix: str, days: int) -> int:
    """Delete GCS blobs under gs://<bucket>/<prefix> whose time_created is older than `days`.

    Args:
        bucket_name: GCS bucket name. Empty string == local-dev posture; no-op
            without constructing a ``storage.Client`` (avoids surfacing missing
            GOOGLE_APPLICATION_CREDENTIALS in tests).
        prefix: object-name prefix to scope the listing (e.g., ``"timescaledb/"``).
        days: retention window. Blobs older than ``now - days`` are deleted.

    Returns:
        Count of blobs successfully deleted. Per-blob delete failures are caught
        and logged so a single transient GCS error does not stop pruning of the
        remaining stale blobs (best-effort retention).

    Idempotent + safe to call after every successful pg_dump upload.
    """
    if not bucket_name:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    deleted = 0
    for blob in client.list_blobs(bucket, prefix=prefix):
        if blob.time_created and blob.time_created < cutoff:
            try:
                blob.delete()
                deleted += 1
                logger.info(
                    "pg_dump prune: deleted gs://%s/%s (created %s)",
                    bucket_name,
                    blob.name,
                    blob.time_created,
                )
            except Exception as exc:  # pragma: no cover — exercised in test
                logger.warning(
                    "pg_dump prune: failed to delete gs://%s/%s: %s",
                    bucket_name,
                    blob.name,
                    exc,
                )
    return deleted


def _dsn_for_pg_dump(sqlalchemy_url: str) -> str:
    """Convert a SQLAlchemy sync URL into a libpq-compatible DSN for pg_dump.

    ``postgresql+psycopg2://u:p@h/d`` → ``postgresql://u:p@h/d``. A URL that
    already lacks the driver suffix is returned unchanged.
    """
    if sqlalchemy_url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + sqlalchemy_url[len("postgresql+psycopg2://"):]
    return sqlalchemy_url


@celery_app.task(name="celery_app.tasks.backup.backup_timescaledb_to_gcs", bind=True)
def backup_timescaledb_to_gcs(self) -> str:
    """Dump the Tide TimescaleDB and upload the result to GCS.

    Returns:
        The ``gs://`` URL of the uploaded dump on success, or the marker
        string ``"skipped (no bucket configured)"`` when
        ``settings.gcs_backup_bucket`` is empty.
    """
    if not settings.gcs_backup_bucket:
        logger.info("backup_timescaledb_to_gcs: no GCS_BACKUP_BUCKET set — skipping")
        return "skipped (no bucket configured)"

    dsn = _dsn_for_pg_dump(settings.database_sync_url)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    blob_name = f"timescaledb/tide_{timestamp}.sql"

    dump_path = Path(tempfile.gettempdir()) / f"tide_{timestamp}.sql"
    try:
        cmd = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            f"--file={dump_path}",
            dsn,
        ]
        logger.info(
            "backup_timescaledb_to_gcs: running pg_dump to %s", dump_path
        )
        # subprocess.run with a fixed list — no shell, no interpolation.
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            # WR-03: Celery's default exception stringifier drops captured
            # stdout/stderr. Surface them before re-raising so the on-call
            # has pg_dump's actual error (e.g. FATAL: role does not exist)
            # in the task log, not just the generic exit-status line.
            logger.error(
                "pg_dump failed rc=%d stdout=%r stderr=%r",
                exc.returncode,
                exc.stdout,
                exc.stderr,
            )
            raise

        client = storage.Client()
        bucket = client.bucket(settings.gcs_backup_bucket)
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(dump_path))

        gs_url = f"gs://{settings.gcs_backup_bucket}/{blob_name}"
        logger.info("backup_timescaledb_to_gcs: uploaded %s", gs_url)

        # Phase 6 — GCS-side 7-day retention (Pitfall A5). Best-effort: a prune
        # failure must NOT fail the backup itself, otherwise a stuck retention
        # bug would block fresh snapshots from being recorded.
        try:
            pruned = _prune_old_gcs_blobs(
                settings.gcs_backup_bucket, PGDUMP_GCS_PREFIX, days=PGDUMP_RETENTION_DAYS
            )
            if pruned:
                logger.info(
                    "backup_timescaledb_to_gcs: pruned %d old blobs (>%d days)",
                    pruned,
                    PGDUMP_RETENTION_DAYS,
                )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "backup_timescaledb_to_gcs: prune step failed (non-fatal): %s", exc
            )

        return gs_url
    finally:
        # T-01-07-01: never leave the dump file on worker disk.
        try:
            if dump_path.exists():
                dump_path.unlink()
        except OSError:  # pragma: no cover — best-effort cleanup
            logger.warning("failed to unlink %s", dump_path)


__all__ = [
    "backup_timescaledb_to_gcs",
    "_dsn_for_pg_dump",
    "_prune_old_gcs_blobs",
    "PGDUMP_RETENTION_DAYS",
    "PGDUMP_GCS_PREFIX",
]
