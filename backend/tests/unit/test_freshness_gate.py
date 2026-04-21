"""Unit tests for the ``require_fresh_conditions`` FastAPI dependency.

Uses the shared ``redis_client`` testcontainer fixture for a real Redis
backend (so micro-cache semantics are exercised) and a hand-rolled mock
``AsyncSession`` whose single ``execute`` return value is controlled per
test. This isolates gate logic from the database without sacrificing
fidelity on the Redis side.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.deps.freshness import (
    FRESHNESS_THRESHOLD,
    MICRO_CACHE_TTL_SECONDS,
    require_fresh_conditions,
)
from ingest.metrics import data_age_seconds, freshness_gate_503_total


STATION = "8534720"
CACHE_KEY = f"cache:freshness:{STATION}"


def _mock_session(latest_bucket: datetime | None) -> MagicMock:
    """Build an AsyncSession-like mock whose ``execute`` returns one row."""
    row = MagicMock()
    row.latest_bucket = latest_bucket

    result = MagicMock()
    result.first = MagicMock(return_value=row if latest_bucket is not None else row)
    if latest_bucket is None:
        # Return a row whose .latest_bucket is None (what the real query yields
        # when there are no matching rows — aggregate returns one row with NULL).
        row.latest_bucket = None

    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_micro_cache_hit(redis_client):
    """When Redis has a fresh ISO timestamp, session is NEVER queried."""
    cached_bucket = datetime.now(timezone.utc) - timedelta(minutes=1)
    await redis_client.setex(
        CACHE_KEY, MICRO_CACHE_TTL_SECONDS, cached_bucket.isoformat()
    )

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=AssertionError("session.execute must not be called on cache hit")
    )

    result = await require_fresh_conditions(STATION, session, redis_client)

    assert result == cached_bucket or abs(
        (result - cached_bucket).total_seconds()
    ) < 1.0
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_stale_returns_503(redis_client):
    """latest_bucket > 35min old → HTTPException 503 conditions_stale."""
    await redis_client.delete(CACHE_KEY)
    stale_bucket = datetime.now(timezone.utc) - timedelta(minutes=40)
    session = _mock_session(stale_bucket)

    counter = freshness_gate_503_total.labels(station_id=STATION, reason="stale")
    baseline = counter._value.get()

    with pytest.raises(HTTPException) as exc_info:
        await require_fresh_conditions(STATION, session, redis_client)

    err = exc_info.value
    assert err.status_code == 503
    assert isinstance(err.detail, dict)
    assert err.detail["code"] == "conditions_stale"
    assert "latest_bucket" in err.detail
    # latest_bucket should be ISO-formatted
    assert isinstance(err.detail["latest_bucket"], str)

    assert counter._value.get() - baseline == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_no_data_returns_503(redis_client):
    """latest_bucket is None (no rows) → 503 conditions_unavailable."""
    await redis_client.delete(CACHE_KEY)
    session = _mock_session(None)

    counter = freshness_gate_503_total.labels(station_id=STATION, reason="no_data")
    baseline = counter._value.get()

    with pytest.raises(HTTPException) as exc_info:
        await require_fresh_conditions(STATION, session, redis_client)

    err = exc_info.value
    assert err.status_code == 503
    assert err.detail["code"] == "conditions_unavailable"

    assert counter._value.get() - baseline == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_fresh_returns_timestamp(redis_client):
    """Fresh bucket → returns tz-aware UTC datetime; no exception."""
    await redis_client.delete(CACHE_KEY)
    fresh_bucket = datetime.now(timezone.utc) - timedelta(minutes=10)
    session = _mock_session(fresh_bucket)

    gauge = data_age_seconds.labels(station_id=STATION, source="cagg")
    # We just need to verify the gauge was touched with a sensible value.

    result = await require_fresh_conditions(STATION, session, redis_client)

    assert isinstance(result, datetime)
    assert result.tzinfo is not None
    # Within a second of what we passed in.
    assert abs((result - fresh_bucket).total_seconds()) < 1.0
    # Gauge should now report ~600 seconds (10 minutes).
    assert 540 < gauge._value.get() < 660


@pytest.mark.asyncio
async def test_cache_populated_after_miss(redis_client):
    """After a cache-miss DB read, the latest bucket is stored with a TTL."""
    await redis_client.delete(CACHE_KEY)
    bucket = datetime.now(timezone.utc) - timedelta(minutes=5)
    session = _mock_session(bucket)

    await require_fresh_conditions(STATION, session, redis_client)

    cached = await redis_client.get(CACHE_KEY)
    assert cached is not None
    ttl = await redis_client.ttl(CACHE_KEY)
    # Should be <= the configured TTL and > 0.
    assert 0 < ttl <= MICRO_CACHE_TTL_SECONDS


@pytest.mark.asyncio
async def test_cache_ttl_respected(redis_client, monkeypatch):
    """The cache write must use MICRO_CACHE_TTL_SECONDS as the TTL argument."""
    await redis_client.delete(CACHE_KEY)
    bucket = datetime.now(timezone.utc) - timedelta(minutes=5)
    session = _mock_session(bucket)

    calls: list[tuple] = []
    original_setex = redis_client.setex

    async def spy_setex(name, time, value):
        calls.append((name, time, value))
        return await original_setex(name, time, value)

    monkeypatch.setattr(redis_client, "setex", spy_setex)

    await require_fresh_conditions(STATION, session, redis_client)

    assert any(
        name == CACHE_KEY and time == MICRO_CACHE_TTL_SECONDS
        for (name, time, _value) in calls
    ), f"Expected setex({CACHE_KEY!r}, {MICRO_CACHE_TTL_SECONDS}, ...); got {calls}"
