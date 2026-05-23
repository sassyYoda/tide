"""REL-04 / L-07 integration tests for ``celery_app.tasks.qdrant_snapshot``.

These tests exercise the Wave 1 (plan 05-02) Qdrant snapshot Celery task
that writes a daily snapshot of the ``fishing_reports`` collection to local
disk (Phase 6 wires GCS via ``QDRANT_SNAPSHOT_TARGET=gs://...``).

Wave 0 (this file) ships RED SKELETONS — each test body is ``pass`` with a
``@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")`` so the CI
quick suite stays green. Wave 1 fills the assertions per RESEARCH §Q6
(lines 465-528) recipe, modelled on
``backend/tests/integration/test_backup.py``.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")
def test_snapshot_writes_local_file():
    """Snapshot task writes a .snapshot file to ``data/qdrant_snapshots/``.

    Wave 1: mock ``get_qdrant().create_snapshot()``, assert the resulting
    file lands at ``LOCAL_SNAPSHOT_DIR / snap_name``.
    """
    pass


@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")
def test_snapshot_prunes_old():
    """Pitfall P5: every task run prunes >7-day-old snapshots.

    Wave 1: seed 8 fake .snapshot files with varying mtimes; run the task;
    assert exactly the 8-day-old file is unlinked.
    """
    pass


@pytest.mark.skip(reason="Wave 1 — landed via 05-02-PLAN")
def test_snapshot_handles_missing_src():
    """Task no-ops gracefully if Qdrant is unreachable (no exception leak).

    Wave 1: monkeypatch ``get_qdrant()`` to raise; run the task; assert it
    returns a "skipped" string and does NOT propagate the exception (Celery
    retry would otherwise re-fire and storm the unreachable service).
    """
    pass
