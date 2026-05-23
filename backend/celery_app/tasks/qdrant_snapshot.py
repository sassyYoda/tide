"""REL-04 / L-07 — daily Qdrant ``fishing_reports`` collection snapshot task.

Beat schedule fires this at 04:00 UTC daily (15 minutes BEFORE the pg_dump
backup at 04:15 UTC — staggered so the two heavy disk operations don't
contend). Each run:

1. Asks the Qdrant server to create a snapshot of the ``fishing_reports``
   collection (Qdrant snapshots are point-in-time per-collection archives;
   the server writes them to its own storage volume).
2. Best-effort copies the resulting file from the server-side mount path
   (``qdrant_storage/snapshots/<collection>/<name>``) to
   ``LOCAL_SNAPSHOT_DIR`` (``data/qdrant_snapshots/``). When Qdrant is
   running on a remote host (Phase 6 GCS migration), the server-side path
   won't exist on the Celery worker filesystem — we log a warning and skip
   the local copy without failing the task. Phase 6 will switch to
   ``QDRANT_SNAPSHOT_TARGET=gs://...`` and upload via the storage SDK.
3. Prunes any local snapshot files older than ``RETENTION_DAYS`` (7 days
   per Pitfall P5 — keeps disk usage bounded; Phase 6 GCS adds longer-term
   off-site retention).

Design notes:

- ``AsyncQdrantClient`` is async; the Celery task body is sync. We bridge
  with ``asyncio.run(...)`` exactly once per task invocation (creates a
  fresh event loop — Celery workers don't share a loop across tasks).
- Task name is import-path-stable: ``celery_app.tasks.qdrant_snapshot.
  snapshot_fishing_reports``. Beat schedule and any direct
  ``celery_app.send_task(...)`` callers reference this string.
- ``bind=True`` matches the canonical backup task pattern; ``self`` is
  unused at MVP but lets us extend the body with retry / state inspection
  without changing the signature (REL-04 hooks for Phase 6).
- The pruning helper is exported (``_prune_old_snapshots``) so tests can
  exercise it directly without spinning a Celery worker.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from datetime import datetime, timezone  # noqa: F401 — re-exported for tests
from pathlib import Path

from celery_app import celery_app
from qdrant.client import get_qdrant


log = logging.getLogger(__name__)


# Module constants — overridable by tests via monkeypatch (the helper +
# the task body reference these names at call time, NOT at import time, so
# monkeypatch.setattr(qdrant_snapshot, "LOCAL_SNAPSHOT_DIR", tmp) works).
LOCAL_SNAPSHOT_DIR = Path("data/qdrant_snapshots")
SERVER_SIDE_SNAPSHOT_ROOT = Path("qdrant_storage/snapshots")
COLLECTION_NAME = "fishing_reports"
RETENTION_DAYS = 7


def _prune_old_snapshots(dir_: Path, days: int) -> int:
    """Delete files in ``dir_`` whose mtime is older than ``days`` ago.

    Returns the count of files unlinked. Missing-directory case returns 0
    (the first task run may execute before any snapshot has landed).
    """
    if not dir_.exists():
        return 0
    cutoff = time.time() - (days * 86400)
    deleted = 0
    for entry in dir_.iterdir():
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                deleted += 1
        except OSError as e:  # pragma: no cover — best-effort
            log.warning("qdrant_snapshot: failed to prune %s: %s", entry, e)
    return deleted


@celery_app.task(
    name="celery_app.tasks.qdrant_snapshot.snapshot_fishing_reports", bind=True
)
def snapshot_fishing_reports(self) -> dict:
    """Create a Qdrant snapshot of ``fishing_reports`` + prune >7-day-old files.

    Returns a dict with the snapshot descriptor name, the local target path
    (empty string when the server-side file wasn't reachable from this
    worker), and the count of pruned files.
    """

    # Re-read module attributes at call time so monkeypatched test values
    # are honoured. (Capturing the names in this function-local namespace
    # also keeps the test-mock surface explicit.)
    from celery_app.tasks import qdrant_snapshot as _mod

    local_dir = _mod.LOCAL_SNAPSHOT_DIR
    server_root = _mod.SERVER_SIDE_SNAPSHOT_ROOT
    collection = _mod.COLLECTION_NAME
    retention_days = _mod.RETENTION_DAYS

    async def _create():
        client = get_qdrant()
        return await client.create_snapshot(collection_name=collection, wait=True)

    snap = asyncio.run(_create())
    # Qdrant snapshot descriptor exposes ``.name`` per the v1.x API.
    snap_name = snap.name
    local_dir.mkdir(parents=True, exist_ok=True)
    target = local_dir / snap_name
    src = server_root / collection / snap_name

    if src.exists():
        shutil.copy2(src, target)
        log.info("qdrant_snapshot: wrote %s", target)
        target_str = str(target)
    else:
        # Phase 6 — when Qdrant runs on a remote host or a GCS-backed
        # volume the worker can't see the snapshot file directly. Log + skip.
        # ``QDRANT_SNAPSHOT_TARGET=gs://...`` will land in Phase 6 as the
        # upload branch (env-var check); Phase 5 keeps this stub-and-warn.
        log.warning(
            "qdrant_snapshot: server-side snapshot exists but src=%s not found locally "
            "(remote Qdrant?)",
            src,
        )
        target_str = ""

    pruned = _prune_old_snapshots(local_dir, retention_days)
    return {"snapshot": snap_name, "path": target_str, "pruned": pruned}


__all__ = [
    "snapshot_fishing_reports",
    "_prune_old_snapshots",
    "LOCAL_SNAPSHOT_DIR",
    "SERVER_SIDE_SNAPSHOT_ROOT",
    "COLLECTION_NAME",
    "RETENTION_DAYS",
]
