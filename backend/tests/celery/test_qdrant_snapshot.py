"""REL-04 / L-07 integration tests for ``celery_app.tasks.qdrant_snapshot``.

These tests exercise the Wave 1 (plan 05-02) Qdrant snapshot Celery task
that writes a daily snapshot of the ``fishing_reports`` collection to local
disk. Phase 6 wires GCS upload via ``QDRANT_SNAPSHOT_TARGET=gs://...``.

The task body bridges async (``AsyncQdrantClient.create_snapshot``) to sync
(Celery worker) via ``asyncio.run``. The tests monkeypatch
``qdrant.client.get_qdrant`` AND the module-level snapshot-dir constants so
no real Qdrant container is needed (and so the tests run hermetically under
``tmp_path``).

Mirrors the pattern in ``backend/tests/integration/test_backup.py``: invoke
``snapshot_fishing_reports.run()`` directly to bypass the Celery dispatch
layer (we test the task body, not Celery itself — Celery plumbing is
covered by ``test_backup.py``'s parallel scenario).
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration


def test_snapshot_writes_local_file(tmp_path, monkeypatch, caplog):
    """Snapshot task writes a .snapshot file to LOCAL_SNAPSHOT_DIR.

    Mocks ``get_qdrant().create_snapshot`` to return a descriptor pointing at
    a server-side file we pre-create under ``tmp_path``; asserts the task
    copies it into the local snapshot dir.
    """
    import celery_app.tasks.qdrant_snapshot as snap_mod

    local_dir = tmp_path / "local"
    server_root = tmp_path / "server"
    monkeypatch.setattr(snap_mod, "LOCAL_SNAPSHOT_DIR", local_dir)
    monkeypatch.setattr(snap_mod, "SERVER_SIDE_SNAPSHOT_ROOT", server_root)

    snap_name = "test-snap-2026-05-23.snapshot"
    src_dir = server_root / snap_mod.COLLECTION_NAME
    src_dir.mkdir(parents=True)
    (src_dir / snap_name).write_bytes(b"fake-snapshot-bytes")

    fake_descriptor = MagicMock()
    fake_descriptor.name = snap_name
    fake_client = MagicMock()
    fake_client.create_snapshot = AsyncMock(return_value=fake_descriptor)
    monkeypatch.setattr(snap_mod, "get_qdrant", lambda: fake_client)

    result = snap_mod.snapshot_fishing_reports.run()

    assert (local_dir / snap_name).exists(), "snapshot file not copied to local dir"
    assert (local_dir / snap_name).read_bytes() == b"fake-snapshot-bytes"
    assert result["snapshot"] == snap_name
    assert result["path"] == str(local_dir / snap_name)
    assert result["pruned"] == 0  # nothing old to prune in a fresh tmp_path
    fake_client.create_snapshot.assert_awaited_once_with(
        collection_name=snap_mod.COLLECTION_NAME, wait=True
    )


def test_snapshot_prunes_old(tmp_path):
    """Pitfall P5: ``_prune_old_snapshots`` deletes files older than 7 days.

    Seed 8 .snapshot files with mtimes spanning 0..8 days old; expect the
    single 8-day-old file to be unlinked and the other 7 to remain.
    """
    from celery_app.tasks.qdrant_snapshot import _prune_old_snapshots

    now = time.time()
    one_day = 86400
    seeded: list[Path] = []
    for days_old in range(9):  # 0..8 days
        f = tmp_path / f"snap-{days_old}d.snapshot"
        f.write_bytes(b"x")
        target_time = now - days_old * one_day
        # Bump 7-day-old slightly newer so it does NOT trip the cutoff (cutoff
        # is exactly 7 days; we want only strictly-older files removed).
        if days_old == 7:
            target_time = now - 7 * one_day + 60  # 7d - 1 minute = inside window
        import os

        os.utime(f, (target_time, target_time))
        seeded.append(f)

    deleted = _prune_old_snapshots(tmp_path, days=7)

    assert deleted == 1, f"expected 1 file pruned, got {deleted}"
    # Only the 8-day-old file should be missing.
    assert not seeded[8].exists(), "8d file should have been deleted"
    for i in range(8):
        assert seeded[i].exists(), f"{i}d file was wrongly deleted"


def test_snapshot_handles_missing_src(tmp_path, monkeypatch, caplog):
    """Server-side src file absent → log warning, skip copy, task still returns.

    Simulates the Phase 6 remote-Qdrant case where the worker cannot see the
    server-side snapshot path directly. The task must NOT raise — Celery
    would otherwise retry-storm an already-unreachable service.
    """
    import logging
    import celery_app.tasks.qdrant_snapshot as snap_mod

    local_dir = tmp_path / "local"
    server_root = tmp_path / "server"  # exists but the snapshot file inside does NOT
    monkeypatch.setattr(snap_mod, "LOCAL_SNAPSHOT_DIR", local_dir)
    monkeypatch.setattr(snap_mod, "SERVER_SIDE_SNAPSHOT_ROOT", server_root)

    snap_name = "ghost.snapshot"
    fake_descriptor = MagicMock()
    fake_descriptor.name = snap_name
    fake_client = MagicMock()
    fake_client.create_snapshot = AsyncMock(return_value=fake_descriptor)
    monkeypatch.setattr(snap_mod, "get_qdrant", lambda: fake_client)

    caplog.set_level(logging.WARNING, logger="celery_app.tasks.qdrant_snapshot")
    result = snap_mod.snapshot_fishing_reports.run()

    # Local target was NOT written (server-side file didn't exist locally).
    assert not (local_dir / snap_name).exists()
    # Task did not raise; return dict carries all three keys.
    assert set(result.keys()) == {"snapshot", "path", "pruned"}
    assert result["snapshot"] == snap_name
    assert result["path"] == ""  # empty when copy skipped
    # The warning log surfaces the missing src.
    assert any(
        "not found locally" in rec.message for rec in caplog.records
    ), f"expected 'not found locally' in warning logs; got {caplog.records}"
