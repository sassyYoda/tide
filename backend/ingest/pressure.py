"""Pressure trend deltas + categorical label (D-04).

Given a history of ``(datetime, pressure_hpa)`` tuples ordered newest-first,
:func:`compute_pressure_trend` returns:

- ``delta_1h``, ``delta_3h``, ``delta_6h``: float deltas in hPa over the last
  N hours, or ``None`` if no historical sample is within ±10 min of the
  target timestamp.
- ``label``: pressure_trend_label ∈ {"Rapid Rise", "Rising", "Steady",
  "Falling", "Rapid Fall"} derived from ``delta_3h``. ``None`` when
  ``delta_3h`` is unknown.

Thresholds (hPa over a 3-hour window):

    delta_3h > +3          → "Rapid Rise"
    +1 < delta_3h ≤ +3     → "Rising"
    -1 ≤ delta_3h ≤ +1     → "Steady"
    -3 ≤ delta_3h < -1     → "Falling"
    delta_3h < -3          → "Rapid Fall"

These bands match the fishing-adjacent pressure_trend_label contract in
the schema (see ``db/models.py::WeatherObservation``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable


WINDOW_MINUTES = 10


def _find_closest(
    history: list[tuple[datetime, float]], target: datetime
) -> float | None:
    """Return pressure from history within ±WINDOW_MINUTES of target, or None."""
    best: tuple[float, float] | None = None  # (abs_delta_seconds, value)
    window = timedelta(minutes=WINDOW_MINUTES)
    for ts, val in history:
        if ts is None or val is None:
            continue
        diff = abs((ts - target).total_seconds())
        if diff > window.total_seconds():
            continue
        if best is None or diff < best[0]:
            best = (diff, val)
    return best[1] if best is not None else None


def compute_pressure_trend(
    history: Iterable[tuple[datetime, float]],
) -> dict[str, float | str | None]:
    """Compute 1h/3h/6h pressure deltas and a categorical trend label.

    ``history`` is an iterable of ``(timestamp, pressure_hpa)`` pairs; order
    does not matter, but the newest entry anchors the "now" reference. If
    no entry is within ±10 min of the (now - N hours) target, that delta is
    ``None``.
    """
    samples = [
        (ts, val)
        for ts, val in history
        if ts is not None and val is not None
    ]
    if not samples:
        return {
            "delta_1h": None,
            "delta_3h": None,
            "delta_6h": None,
            "pressure_trend_label": None,
        }

    samples.sort(key=lambda x: x[0], reverse=True)
    now_ts, now_val = samples[0]

    def _delta(hours: int) -> float | None:
        target = now_ts - timedelta(hours=hours)
        past = _find_closest(samples, target)
        if past is None:
            return None
        return round(now_val - past, 4)

    delta_1h = _delta(1)
    delta_3h = _delta(3)
    delta_6h = _delta(6)

    label: str | None
    if delta_3h is None:
        label = None
    elif delta_3h > 3:
        label = "Rapid Rise"
    elif delta_3h > 1:
        label = "Rising"
    elif delta_3h >= -1:
        label = "Steady"
    elif delta_3h >= -3:
        label = "Falling"
    else:
        label = "Rapid Fall"

    return {
        "delta_1h": delta_1h,
        "delta_3h": delta_3h,
        "delta_6h": delta_6h,
        "pressure_trend_label": label,
    }


__all__ = ["compute_pressure_trend", "WINDOW_MINUTES"]
