"""REL-03 integration tests for ``celery_app.tasks.backup``.

These tests exercise the backup task directly (not via Celery) because the
task body is the interesting part — the Celery plumbing is already covered
by the task decorator + beat-schedule wiring. We patch ``subprocess.run``
and ``google.cloud.storage.Client`` so no real pg_dump binary or GCS client
is touched.

Three scenarios:

1. ``test_skipped_when_no_bucket`` — the no-op path used by local Compose
   (no cloud creds in the environment).
2. ``test_uploads_when_bucket_configured`` — the happy path: verifies the
   pg_dump command is well-formed, the GCS blob path is canonical, and
   ``upload_from_filename`` is called exactly once.
3. ``test_dsn_conversion`` — ``_dsn_for_pg_dump`` strips the ``+psycopg2``
   SQLAlchemy driver suffix but leaves plain ``postgresql://`` URLs alone.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from celery_app.tasks.backup import (
    _dsn_for_pg_dump,
    backup_timescaledb_to_gcs,
)


pytestmark = pytest.mark.integration


def test_skipped_when_no_bucket(monkeypatch):
    """Empty bucket → task returns skip marker without running pg_dump."""
    import celery_app.tasks.backup as backup_mod

    monkeypatch.setattr(backup_mod.settings, "gcs_backup_bucket", "")

    with patch.object(backup_mod, "subprocess") as sub_mod, patch.object(
        backup_mod.storage, "Client"
    ) as client_cls:
        # Call the task body directly (bypass Celery dispatch).
        result = backup_timescaledb_to_gcs.run()

    assert result == "skipped (no bucket configured)"
    sub_mod.run.assert_not_called()
    client_cls.assert_not_called()


def test_uploads_when_bucket_configured(monkeypatch, tmp_path):
    """Populated bucket → pg_dump runs, blob uploads, gs:// URL returned."""
    import celery_app.tasks.backup as backup_mod

    monkeypatch.setattr(backup_mod.settings, "gcs_backup_bucket", "test-bucket")
    monkeypatch.setattr(
        backup_mod.settings,
        "database_sync_url",
        "postgresql+psycopg2://tide:tide@localhost:5432/tide",
    )
    # Keep the dump-path predictable and avoid polluting /tmp.
    monkeypatch.setattr(backup_mod.tempfile, "gettempdir", lambda: str(tmp_path))

    fake_blob = MagicMock()
    fake_bucket = MagicMock()
    fake_bucket.blob.return_value = fake_blob
    fake_client = MagicMock()
    fake_client.bucket.return_value = fake_bucket

    # Simulate pg_dump actually writing a file so the finally-unlink branch
    # has something to remove (mirrors real behaviour).
    def fake_subprocess_run(cmd, *args, **kwargs):
        # The --file=<path> arg is the 5th element by construction.
        for token in cmd:
            if isinstance(token, str) and token.startswith("--file="):
                Path(token.split("=", 1)[1]).write_bytes(b"fake dump")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(
        backup_mod.subprocess, "run", side_effect=fake_subprocess_run
    ) as mock_run, patch.object(
        backup_mod.storage, "Client", return_value=fake_client
    ):
        result = backup_timescaledb_to_gcs.run()

    # pg_dump call shape
    assert mock_run.call_count == 1
    cmd = mock_run.call_args.args[0]
    assert "pg_dump" in cmd
    assert "--format=custom" in cmd
    assert "--no-owner" in cmd
    assert "--no-acl" in cmd
    # DSN passed as the last positional with the +psycopg2 suffix stripped
    assert cmd[-1] == "postgresql://tide:tide@localhost:5432/tide"

    # GCS shape. Phase 6 / plan 06-02 added a post-upload prune step that calls
    # ``storage.Client().bucket(...)`` a second time for the retention sweep, so
    # we no longer assert called_once — the contract is "bucket is the configured
    # one whenever it IS resolved" (every call uses "test-bucket").
    assert fake_client.bucket.call_count >= 1
    for call in fake_client.bucket.call_args_list:
        assert call.args == ("test-bucket",)
    blob_name = fake_bucket.blob.call_args_list[0].args[0]
    assert blob_name.startswith("timescaledb/tide_")
    assert blob_name.endswith(".sql") or blob_name.endswith(".sql.gz")
    fake_blob.upload_from_filename.assert_called_once()

    # Return value
    assert result.startswith("gs://test-bucket/timescaledb/tide_")


def test_dsn_conversion():
    """``+psycopg2`` driver suffix is stripped; plain URLs pass through."""
    assert (
        _dsn_for_pg_dump("postgresql+psycopg2://u:p@h/d")
        == "postgresql://u:p@h/d"
    )
    assert (
        _dsn_for_pg_dump("postgresql://u:p@h/d")
        == "postgresql://u:p@h/d"
    )
