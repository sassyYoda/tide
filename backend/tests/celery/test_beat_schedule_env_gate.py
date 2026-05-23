"""Pitfall P12 — verify beat_schedule gate on TIDE_INGEST_VIA_CLOUD_RUN_JOBS env flag.

When the env var is truthy (set by Cloud Run Jobs), the VM-side Celery beat
schedule MUST strip the 3 ingest entries (poll_noaa_stations, poll_open_meteo,
compute_solunar) so the cron triggers don't double-fire. The 3 backup/scorer
entries stay regardless — Cloud Run Jobs do NOT own those.
"""

from __future__ import annotations

import importlib

import pytest


pytestmark = pytest.mark.unit


@pytest.fixture
def reset_celery_module():
    """Force reimport of celery_app so the env flag is re-read on each test.

    Yields to the test, then reloads celery_app at teardown so the next test's
    initial state is the (test-process-default) unflagged behavior. Without
    this, an earlier test that set the flag to "true" would leave the cached
    module's beat_schedule missing the ingest entries for any subsequent test.
    """
    import celery_app

    yield
    # Restore by reimport with the test process's current env.
    importlib.reload(celery_app)


def test_beat_schedule_strips_ingest_when_flag_true(monkeypatch, reset_celery_module):
    monkeypatch.setenv("TIDE_INGEST_VIA_CLOUD_RUN_JOBS", "true")
    import celery_app

    importlib.reload(celery_app)
    schedule = celery_app.celery_app.conf.beat_schedule
    assert "poll_noaa_stations" not in schedule
    assert "poll_open_meteo" not in schedule
    assert "compute_solunar" not in schedule
    # Backup/snapshot/scorer stay — Cloud Run Jobs do NOT own them.
    assert "backup_timescaledb" in schedule
    assert "snapshot_qdrant" in schedule
    assert "score_all_spots" in schedule


def test_beat_schedule_keeps_ingest_when_flag_unset(monkeypatch, reset_celery_module):
    monkeypatch.delenv("TIDE_INGEST_VIA_CLOUD_RUN_JOBS", raising=False)
    import celery_app

    importlib.reload(celery_app)
    schedule = celery_app.celery_app.conf.beat_schedule
    assert "poll_noaa_stations" in schedule
    assert "poll_open_meteo" in schedule
    assert "compute_solunar" in schedule
    assert len(schedule) == 6


@pytest.mark.parametrize("falsy", ["", "false", "no", "0"])
def test_beat_schedule_keeps_ingest_when_flag_falsy(
    monkeypatch, reset_celery_module, falsy
):
    monkeypatch.setenv("TIDE_INGEST_VIA_CLOUD_RUN_JOBS", falsy)
    import celery_app

    importlib.reload(celery_app)
    schedule = celery_app.celery_app.conf.beat_schedule
    assert "poll_noaa_stations" in schedule
    assert "poll_open_meteo" in schedule
    assert "compute_solunar" in schedule
