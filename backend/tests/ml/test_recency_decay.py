"""R-08 — recency multiplier bands."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from qdrant.retriever import DEFAULT_FALLBACK, recency_multiplier


BASE = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)


def test_within_24h_full():
    assert recency_multiplier(BASE - timedelta(hours=12), BASE) == 1.00


def test_at_24h_still_full():
    assert recency_multiplier(BASE - timedelta(hours=24), BASE) == 1.00


def test_within_72h():
    assert recency_multiplier(BASE - timedelta(hours=48), BASE) == 0.80


def test_within_1wk():
    assert recency_multiplier(BASE - timedelta(days=5), BASE) == 0.60


def test_within_30d():
    assert recency_multiplier(BASE - timedelta(days=20), BASE) == 0.40


def test_beyond_30d_fallback():
    assert recency_multiplier(BASE - timedelta(days=60), BASE) == DEFAULT_FALLBACK
    assert DEFAULT_FALLBACK == 0.20
