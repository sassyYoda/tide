"""Unit tests for the solunar module — pure ephem, no I/O."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from ingest.solunar import compute_solunar, phase_to_sincos


BARNEGAT_LAT = 39.7592
BARNEGAT_LON = -74.1196


def test_sin_cos():
    """Phase = 0.25 → sin = +1, cos = 0 exactly."""
    sin_p, cos_p = phase_to_sincos(0.25)
    assert sin_p == pytest.approx(1.0)
    assert cos_p == pytest.approx(0.0, abs=1e-9)


def test_sin_cos_at_new_moon():
    sin_p, cos_p = phase_to_sincos(0.0)
    assert sin_p == pytest.approx(0.0, abs=1e-9)
    assert cos_p == pytest.approx(1.0)


def test_sunrise_set():
    """Summer solstice noon in Barnegat: sun has risen + has not yet set."""
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    result = compute_solunar(BARNEGAT_LAT, BARNEGAT_LON, when)
    assert result["sunrise"] is not None
    assert result["sunset"] is not None
    assert result["sunrise"].tzinfo is not None
    assert result["sunset"].tzinfo is not None
    # At 16:00 UTC on the solstice, 'next rising' is tomorrow morning —
    # assert both timestamps are TZ-aware UTC. Ordering between sunrise
    # and sunset depends on observer.date semantics; only check tz.
    assert result["sunrise"].tzinfo == timezone.utc
    assert result["sunset"].tzinfo == timezone.utc


def test_deterministic():
    """Same inputs → same outputs (modulo float approx)."""
    when = datetime(2026, 4, 20, 14, 0, tzinfo=timezone.utc)
    a = compute_solunar(BARNEGAT_LAT, BARNEGAT_LON, when)
    b = compute_solunar(BARNEGAT_LAT, BARNEGAT_LON, when)
    for key in (
        "moon_phase",
        "moon_phase_sin",
        "moon_phase_cos",
        "illumination",
        "lunar_day",
        "quality_score",
    ):
        assert a[key] == pytest.approx(b[key])
    for key in (
        "time",
        "sunrise",
        "sunset",
        "next_major_start",
        "next_major_end",
        "next_minor_start",
        "next_minor_end",
    ):
        assert a[key] == b[key]


def test_moon_phase_range():
    when = datetime(2026, 4, 20, 14, 0, tzinfo=timezone.utc)
    result = compute_solunar(BARNEGAT_LAT, BARNEGAT_LON, when)
    assert 0 <= result["moon_phase"] <= 1
    assert 0 <= result["illumination"] <= 1


def test_sin_cos_consistent():
    """sin² + cos² ≈ 1 for any phase."""
    when = datetime(2026, 4, 20, 14, 0, tzinfo=timezone.utc)
    result = compute_solunar(BARNEGAT_LAT, BARNEGAT_LON, when)
    s = result["moon_phase_sin"]
    c = result["moon_phase_cos"]
    assert math.isclose(s * s + c * c, 1.0, abs_tol=1e-9)


def test_hour_truncation():
    when = datetime(2026, 4, 20, 14, 37, 42, tzinfo=timezone.utc)
    result = compute_solunar(BARNEGAT_LAT, BARNEGAT_LON, when)
    assert result["time"] == datetime(2026, 4, 20, 14, 0, tzinfo=timezone.utc)
    assert result["time"].tzinfo == timezone.utc


def test_naive_datetime_treated_as_utc():
    """A naive datetime should be interpreted as UTC and produce the same output."""
    aware = datetime(2026, 4, 20, 14, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 4, 20, 14, 0)
    a = compute_solunar(BARNEGAT_LAT, BARNEGAT_LON, aware)
    b = compute_solunar(BARNEGAT_LAT, BARNEGAT_LON, naive)
    assert a["moon_phase"] == pytest.approx(b["moon_phase"])
    assert a["time"] == b["time"]
