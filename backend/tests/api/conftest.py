"""Phase 3 FastAPI / SSE test fixtures."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# NOTE: ``migrated_api_db`` is duplicated from
# backend/tests/integration/test_conditions_endpoint.py:60-65 (where it is
# file-local). A future Phase 5 conftest consolidation should hoist it to
# tests/conftest.py and remove this duplicate.
BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/


def _run_alembic_upgrade(sync_url: str, async_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_SYNC_URL"] = sync_url
    env["DATABASE_URL"] = async_url
    env.setdefault("REDIS_URL", "redis://localhost:6379/0")
    subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
    )


@pytest.fixture(scope="module")
def migrated_api_db(timescale_sync_url, timescale_async_url) -> str:
    _run_alembic_upgrade(timescale_sync_url, timescale_async_url)
    return timescale_sync_url


@pytest.fixture
def test_client(migrated_api_db, timescale_async_url, redis_container):
    """FastAPI TestClient with overridden db + redis Depends.

    Copies the working pattern from
    backend/tests/integration/test_conditions_endpoint.py:65-108.
    """
    from app.deps.db import get_session
    from app.deps.redis import get_redis
    from app.main import create_app

    host = redis_container.get_container_host_ip()
    port = int(redis_container.get_exposed_port(6379))
    redis_url = f"redis://{host}:{port}/0"

    engine = create_async_engine(timescale_async_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _session_override():
        async with factory() as s:
            yield s

    async def _redis_override():
        r = Redis.from_url(redis_url, decode_responses=False)
        try:
            yield r
        finally:
            await r.aclose()

    app = create_app()
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_redis] = _redis_override
    client = TestClient(app)
    try:
        yield {
            "client": client,
            "app": app,
            "sync_url": migrated_api_db,
            "async_url": timescale_async_url,
            "redis_url": redis_url,
            "factory": factory,
        }
    finally:
        app.dependency_overrides.clear()


def parse_sse_stream(raw: bytes | str) -> list[tuple[str, dict[str, Any] | None]]:
    """Parse an SSE event stream body into ``[(event_type, json_payload), ...]``.

    Accepts either ``bytes`` or ``str``. Per W3C: events are blank-line separated;
    each event has lines like ``event: <name>`` and ``data: <json>``.
    """
    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
    events: list[tuple[str, dict[str, Any] | None]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev_type = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith(":"):  # comment / keep-alive
                continue
            if line.startswith("event:"):
                ev_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if data_lines:
            joined = "\n".join(data_lines)
            try:
                payload: dict[str, Any] | None = json.loads(joined)
            except json.JSONDecodeError:
                payload = {"_raw": joined}
        else:
            payload = None
        events.append((ev_type, payload))
    return events


@pytest.fixture
def sse_events():
    """Helper: post a body to a route and parse the resulting SSE stream.

    Usage::

        events = sse_events(test_client["client"], "/api/v1/query", {"query": "..."})
        assert events[0][0] == "progress"
    """

    def _call(
        client: TestClient,
        path: str,
        body: dict[str, Any],
    ) -> list[tuple[str, dict[str, Any] | None]]:
        with client.stream("POST", path, json=body) as resp:
            chunks = list(resp.iter_bytes())
        full = b"".join(chunks)
        return parse_sse_stream(full)

    return _call
