"""Phase 6 / plan 06-02 — GCS-side 7-day blob retention for pg_dump snapshots.

Tests the ``_prune_old_gcs_blobs`` helper added to ``celery_app.tasks.backup``
(Pitfall A5 — keep the tide-pgdump bucket within the 5 GB GCS free tier even
if Cloud Storage's lifecycle policy is mis-applied). Mirrors the pattern in
``celery_app.tasks.qdrant_snapshot._prune_old_snapshots`` (local-fs) but
operates on GCS via ``storage.Client().list_blobs(...)``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


pytestmark = pytest.mark.unit


def _fake_blob(name: str, age_days: float) -> MagicMock:
    """Build a MagicMock that quacks like a google.cloud.storage.Blob."""
    b = MagicMock()
    b.name = name
    b.time_created = datetime.now(timezone.utc) - timedelta(days=age_days)
    return b


@patch("celery_app.tasks.backup.storage.Client")
def test_prune_deletes_blobs_older_than_7_days(mock_client_cls):
    """Stale blob (>7d) gets delete()d; fresh + edge (<7d) do not."""
    from celery_app.tasks.backup import _prune_old_gcs_blobs

    b_fresh = _fake_blob("timescaledb/tide_FRESH.sql", age_days=1)
    b_edge = _fake_blob("timescaledb/tide_EDGE.sql", age_days=6.5)
    b_stale = _fake_blob("timescaledb/tide_STALE.sql", age_days=10)
    mock_client = MagicMock()
    mock_client.list_blobs.return_value = [b_fresh, b_edge, b_stale]
    mock_client_cls.return_value = mock_client

    deleted = _prune_old_gcs_blobs("tide-pgdump", "timescaledb/", days=7)

    assert deleted == 1
    b_stale.delete.assert_called_once()
    b_fresh.delete.assert_not_called()
    b_edge.delete.assert_not_called()


@patch("celery_app.tasks.backup.storage.Client")
def test_prune_returns_zero_when_bucket_empty(mock_client_cls):
    """Empty list_blobs → 0 deletions, no exceptions."""
    from celery_app.tasks.backup import _prune_old_gcs_blobs

    mock_client = MagicMock()
    mock_client.list_blobs.return_value = []
    mock_client_cls.return_value = mock_client

    assert _prune_old_gcs_blobs("tide-pgdump", "timescaledb/", days=7) == 0


def test_prune_returns_zero_when_bucket_name_empty():
    """Empty bucket name (local-dev posture) → 0 deletions, no storage.Client
    construction (avoids credential errors in tests without GOOGLE_APPLICATION_CREDENTIALS)."""
    from celery_app.tasks.backup import _prune_old_gcs_blobs

    with patch("celery_app.tasks.backup.storage.Client") as mock_client_cls:
        result = _prune_old_gcs_blobs("", "timescaledb/", days=7)

    assert result == 0
    mock_client_cls.assert_not_called()


@patch("celery_app.tasks.backup.storage.Client")
def test_prune_swallows_per_blob_delete_failures(mock_client_cls):
    """A failed delete() on one blob does not stop pruning of subsequent blobs."""
    from celery_app.tasks.backup import _prune_old_gcs_blobs

    b1 = _fake_blob("timescaledb/tide_A.sql", age_days=30)
    b1.delete.side_effect = RuntimeError("transient gcs failure")
    b2 = _fake_blob("timescaledb/tide_B.sql", age_days=30)
    mock_client = MagicMock()
    mock_client.list_blobs.return_value = [b1, b2]
    mock_client_cls.return_value = mock_client

    deleted = _prune_old_gcs_blobs("tide-pgdump", "timescaledb/", days=7)

    # b1 raised → not counted; b2 succeeded → counted. Helper must not propagate.
    assert deleted == 1
    b1.delete.assert_called_once()
    b2.delete.assert_called_once()
