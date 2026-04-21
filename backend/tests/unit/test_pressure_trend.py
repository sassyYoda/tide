"""Unit tests for pressure trend thresholds (D-04)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ingest.pressure import compute_pressure_trend


BASE = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)


def _history(pressures: list[float]) -> list[tuple[datetime, float]]:
    """Build a 7-entry hourly history newest-first from ``pressures[0]`` (now)."""
    out: list[tuple[datetime, float]] = []
    for i, p in enumerate(pressures):
        out.append((BASE - timedelta(hours=i), p))
    return out


def test_rapid_rise():
    # 3-h delta of +5 hPa
    hist = _history([1020.0, 1018.0, 1016.5, 1015.0, 1014.0, 1013.0, 1012.0])
    result = compute_pressure_trend(hist)
    assert result["delta_3h"] == 5.0
    assert result["pressure_trend_label"] == "Rapid Rise"


def test_rising():
    # 3-h delta of +2 hPa
    hist = _history([1015.0, 1014.5, 1014.0, 1013.0, 1012.5, 1012.0, 1011.5])
    result = compute_pressure_trend(hist)
    assert result["delta_3h"] == 2.0
    assert result["pressure_trend_label"] == "Rising"


def test_steady():
    # 3-h delta of 0
    hist = _history([1013.0, 1013.1, 1012.9, 1013.0, 1012.8, 1012.9, 1013.0])
    result = compute_pressure_trend(hist)
    assert abs(result["delta_3h"]) <= 1.0
    assert result["pressure_trend_label"] == "Steady"


def test_falling():
    # 3-h delta of -2
    hist = _history([1011.0, 1011.5, 1012.0, 1013.0, 1013.5, 1014.0, 1014.5])
    result = compute_pressure_trend(hist)
    assert result["delta_3h"] == -2.0
    assert result["pressure_trend_label"] == "Falling"


def test_rapid_fall():
    # 3-h delta of -5
    hist = _history([1008.0, 1010.0, 1011.5, 1013.0, 1014.0, 1015.0, 1016.0])
    result = compute_pressure_trend(hist)
    assert result["delta_3h"] == -5.0
    assert result["pressure_trend_label"] == "Rapid Fall"


def test_deltas_and_labels_all_present():
    hist = _history([1020.0, 1018.0, 1016.5, 1015.0, 1014.0, 1013.0, 1012.0])
    result = compute_pressure_trend(hist)
    assert result["delta_1h"] is not None
    assert result["delta_3h"] is not None
    assert result["delta_6h"] is not None


def test_none_when_window_empty():
    """Only 30 min of history → no entry within ±10 min of -3h / -6h targets."""
    hist = [
        (BASE, 1013.0),
        (BASE - timedelta(minutes=15), 1013.0),
        (BASE - timedelta(minutes=30), 1013.2),
    ]
    result = compute_pressure_trend(hist)
    assert result["delta_3h"] is None
    assert result["delta_6h"] is None
    assert result["pressure_trend_label"] is None
