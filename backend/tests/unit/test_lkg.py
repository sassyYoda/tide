"""Unit tests for Redis LKG + per-station circuit breaker."""

from __future__ import annotations

import orjson
import pytest

from ingest.lkg import (
    BREAKER_THRESHOLD,
    increment_breaker,
    read_lkg,
    reset_breaker,
    write_lkg,
)
from ingest.metrics import noaa_breaker_tripped_total


@pytest.mark.asyncio
async def test_write_read_roundtrip(redis_client):
    payload = {"time": "2026-04-20T15:00Z", "value": 0.845}
    await write_lkg(redis_client, "lkg:noaa:8534720:water_level", payload, ttl=60)
    got = await read_lkg(redis_client, "lkg:noaa:8534720:water_level")
    assert got == payload
    ttl = await redis_client.ttl("lkg:noaa:8534720:water_level")
    assert 0 < ttl <= 60


@pytest.mark.asyncio
async def test_read_lkg_missing(redis_client):
    assert await read_lkg(redis_client, "lkg:noaa:missing:x") is None


@pytest.mark.asyncio
async def test_breaker_increments_counter_once(redis_client):
    # Reset counter (the prom_client in-process counter persists across tests in
    # the same process; record the baseline and compare deltas).
    station = "8534720"
    counter = noaa_breaker_tripped_total.labels(station_id=station)
    baseline = counter._value.get()

    count1 = await increment_breaker(redis_client, station)
    count2 = await increment_breaker(redis_client, station)
    count3 = await increment_breaker(redis_client, station)
    count4 = await increment_breaker(redis_client, station)

    assert count1 == 1
    assert count2 == 2
    assert count3 == BREAKER_THRESHOLD
    assert count4 == 4

    # Exactly one trip emitted, on count==3.
    assert counter._value.get() - baseline == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_reset_breaker_clears_counter(redis_client):
    station = "8536110"
    await increment_breaker(redis_client, station)
    await increment_breaker(redis_client, station)
    await reset_breaker(redis_client, station)
    count = await increment_breaker(redis_client, station)
    assert count == 1
