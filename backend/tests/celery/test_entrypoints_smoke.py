"""INFRA-03 — smoke-test that each Cloud Run Jobs entrypoint main() calls
the underlying Celery task via .apply().get() exactly once and returns 0.

The entrypoint modules are thin wrappers (no broker round-trip) — these tests
verify the wiring without actually executing the task body (which would need
the full DB/HTTP stack).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


pytestmark = pytest.mark.unit


def _patch_task(monkeypatch, task_dotted_path: str, return_value="ok"):
    """Replace `task.apply` with a stub whose `.get()` returns ``return_value``.

    Returns the patched `applied` mock so the caller can assert on it.
    """
    from importlib import import_module

    mod_path, attr = task_dotted_path.rsplit(".", 1)
    mod = import_module(mod_path)
    task = getattr(mod, attr)
    applied = MagicMock()
    applied.get.return_value = return_value
    monkeypatch.setattr(task, "apply", lambda *a, **kw: applied)
    return applied


def test_ingest_noaa_main_invokes_task(monkeypatch):
    applied = _patch_task(
        monkeypatch,
        "celery_app.tasks.noaa.poll_noaa_stations",
        return_value="6 stations polled",
    )
    from celery_app.entrypoints import ingest_noaa

    assert ingest_noaa.main() == 0
    applied.get.assert_called_once()


def test_ingest_meteo_main_invokes_task(monkeypatch):
    applied = _patch_task(
        monkeypatch,
        "celery_app.tasks.meteo.poll_open_meteo",
        return_value="9 stations",
    )
    from celery_app.entrypoints import ingest_meteo

    assert ingest_meteo.main() == 0
    applied.get.assert_called_once()


def test_compute_solunar_main_invokes_task(monkeypatch):
    applied = _patch_task(
        monkeypatch,
        "celery_app.tasks.solunar.compute_solunar_task",
        return_value="done",
    )
    from celery_app.entrypoints import compute_solunar

    assert compute_solunar.main() == 0
    applied.get.assert_called_once()
