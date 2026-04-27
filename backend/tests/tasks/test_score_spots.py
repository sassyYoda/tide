"""M-11 + M-13 — score_all_spots beat schedule + task registration."""
from __future__ import annotations

import pytest  # noqa: F401 — fixtures auto-discovered


def test_beat_schedule_registers_15min_scorer():
    """Plan 07: celery_app beat schedule contains 'score_all_spots' @ 15min cadence."""
    from celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "score_all_spots" in schedule
    entry = schedule["score_all_spots"]
    assert entry["task"] == "celery_app.tasks.scorer.score_all_spots"
    cron = entry["schedule"]
    cron_repr = repr(cron)
    minutes = getattr(cron, "minute", None)
    assert (
        "*/15" in cron_repr
        or (minutes is not None and {0, 15, 30, 45}.issubset(set(minutes)))
    ), f"score_all_spots schedule not */15: {cron_repr}"


def test_task_name_is_stable():
    """Task names are import-path-based and STABLE per celery_app docstring."""
    from celery_app.tasks.scorer import score_all_spots

    assert score_all_spots.name == "celery_app.tasks.scorer.score_all_spots"


def test_task_registered_in_include_list():
    from celery_app import celery_app

    assert "celery_app.tasks.scorer" in celery_app.conf.include
