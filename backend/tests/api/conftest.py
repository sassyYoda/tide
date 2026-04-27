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

    # Phase 3 (SEC-02): rate-limiter state must be reset between tests so the
    # 20-req/hr bucket is fresh. Without this, the cumulative tests in this
    # module quickly exhaust the bucket and earlier tests start receiving
    # rate_limited error events instead of the expected payloads.
    try:
        from api.middleware.rate_limit import limiter

        limiter.reset()
    except Exception:  # noqa: BLE001 — older slowapi may lack reset()
        pass

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

    sse-starlette emits CRLF (``\\r\\n``) line endings, so the event-boundary
    delimiter on the wire is ``\\r\\n\\r\\n`` — not ``\\n\\n``. Normalise to LF
    before splitting so this parser works with both line-ending conventions.
    """
    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
    # Normalise CRLF → LF so the blank-line splitter works for both encodings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
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


# ─── Phase 3 LLM stubs (mirrored from tests/agent/conftest.py) ─────────
# pytest only discovers conftests along the path to the test file; tests/api/
# is a sibling of tests/agent/ so we duplicate the relevant fixtures here.
# A future Phase 5 conftest consolidation should hoist these to tests/conftest.py.


class _StubMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubChatOpenAI:
    """Mimics langchain_openai.ChatOpenAI for unit tests.

    Set ``_StubChatOpenAI.next_response = <PlannerOutput-or-AIMessage>`` before
    calling .invoke / .ainvoke to control the response.
    """

    next_response: Any = None

    def __init__(self, *_a: Any, **_kw: Any) -> None:
        pass

    def with_structured_output(self, _schema: Any) -> "_StubChatOpenAI":
        return self

    async def ainvoke(self, _msgs: Any, **_kw: Any) -> Any:
        return self.next_response

    def invoke(self, _msgs: Any, **_kw: Any) -> Any:
        return self.next_response


class _StubChatAnthropic:
    """Mimics langchain_anthropic.ChatAnthropic for unit tests."""

    next_response: Any = None

    def __init__(self, *_a: Any, **_kw: Any) -> None:
        pass

    async def ainvoke(self, _msgs: Any, **_kw: Any) -> Any:
        return self.next_response or _StubMessage("stub response")

    def invoke(self, _msgs: Any, **_kw: Any) -> Any:
        return self.next_response or _StubMessage("stub response")


@pytest.fixture
def stub_planner_llm(monkeypatch: pytest.MonkeyPatch) -> type[_StubChatOpenAI]:
    monkeypatch.setattr("langchain_openai.ChatOpenAI", _StubChatOpenAI)
    _StubChatOpenAI.next_response = None
    return _StubChatOpenAI


@pytest.fixture
def stub_synth_llm(monkeypatch: pytest.MonkeyPatch) -> type[_StubChatAnthropic]:
    monkeypatch.setattr("langchain_anthropic.ChatAnthropic", _StubChatAnthropic)
    _StubChatAnthropic.next_response = None
    return _StubChatAnthropic


@pytest.fixture
def lazy_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip MLflow load at import — mirrors ml.model._maybe_load_at_import opt-out."""
    monkeypatch.setenv("TIDE_LAZY_MODEL_LOAD", "1")


@pytest.fixture
def lazy_spots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip Postgres-driven spot load at import — mirrors module-level singleton opt-out."""
    monkeypatch.setenv("TIDE_LAZY_SPOT_LOAD", "1")


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
