"""Shared pytest fixtures for Tide backend tests.

This conftest is the Nyquist-sampling harness for Wave 0 — every Phase 1 plan
(and Phase 2+ when reusing these fixtures) inherits from here without re-wiring
infra. The six core fixtures below are the contract:

    timescale_container  — session-scoped Timescale testcontainer
    async_session        — function-scoped AsyncSession bound to the container
    redis_client         — function-scoped async Redis client bound to a container
    respx_mock           — function-scoped httpx mock router
    frozen_utc           — function-scoped frozen clock (2026-04-20T12:00:00Z)
    celery_eager         — function-scoped Celery always-eager mode

The `os.environ.setdefault(...)` calls at module top ensure `app.config.settings`
can instantiate during pytest collection even when no `.env` is present. These
are sentinel values — actual integration tests use the real URLs yielded by the
testcontainer fixtures below.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import AsyncIterator, Iterator

# Set env defaults BEFORE any import that pulls app.config (which validates env).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://tide:tide@localhost:5432/tide")
os.environ.setdefault(
    "DATABASE_SYNC_URL", "postgresql+psycopg2://tide:tide@localhost:5432/tide"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# Phase 2 env defaults — keep app.config.Settings instantiable during collection.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("MLFLOW_TRACKING_URI", "./mlruns")
os.environ.setdefault("MLFLOW_ARTIFACT_ROOT", "./mlartifacts")
os.environ.setdefault("REDDIT_CLIENT_ID", "")
os.environ.setdefault("REDDIT_CLIENT_SECRET", "")
os.environ.setdefault("REDDIT_USER_AGENT", "Tide/0.1 (test)")
os.environ.setdefault("FISHBRAIN_USER_AGENT", "Tide/0.1 (test)")
# Phase 3 additions — never block unit imports on real keys
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "")
os.environ.setdefault("LANGFUSE_HOST", "https://cloud.langfuse.com")
os.environ.setdefault("RAPIDFUZZ_THRESHOLD", "65")

import pytest
import pytest_asyncio
import respx
from freezegun import freeze_time
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def timescale_container() -> Iterator[PostgresContainer]:
    """Session-scoped TimescaleDB container. First run pulls the image."""
    ctr = PostgresContainer(
        image="timescale/timescaledb:latest-pg17",
        username="tide",
        password="tide",
        dbname="tide",
    )
    ctr.start()
    try:
        yield ctr
    finally:
        ctr.stop()


@pytest.fixture(scope="session")
def timescale_sync_url(timescale_container) -> str:
    """Sync (psycopg2) URL for the Timescale container — used by Alembic tests."""
    # testcontainers-python returns a psycopg2 URL by default
    return timescale_container.get_connection_url()


@pytest.fixture(scope="session")
def timescale_async_url(timescale_container) -> str:
    """Async (asyncpg) URL for the Timescale container — used by app/runtime tests."""
    url = timescale_container.get_connection_url()
    return url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest_asyncio.fixture
async def async_session(timescale_async_url) -> AsyncIterator[AsyncSession]:
    """Function-scoped AsyncSession. Engine is disposed after each test."""
    engine = create_async_engine(timescale_async_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    """Session-scoped Redis container."""
    ctr = RedisContainer(image="redis:7-alpine")
    ctr.start()
    try:
        yield ctr
    finally:
        ctr.stop()


@pytest_asyncio.fixture
async def redis_client(redis_container):
    """Function-scoped async Redis client. Flushes DB before each test."""
    from redis.asyncio import Redis

    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    client = Redis(host=host, port=port, decode_responses=False)
    try:
        await client.flushdb()
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    """httpx mock router. `assert_all_called=False` so optional routes don't fail tests."""
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def frozen_utc() -> Iterator[datetime]:
    """Deterministic clock for solunar/time-dependent tests."""
    fixed = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    with freeze_time(fixed):
        yield fixed


@pytest.fixture
def celery_eager(monkeypatch):
    """Run Celery tasks synchronously in-process so apply_async() returns a result."""
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    from celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
