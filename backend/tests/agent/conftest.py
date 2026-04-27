"""Phase 3 agent test fixtures.

Re-exports parent fixtures (db, redis, qdrant, respx_mock, etc.) and adds:
- lazy_models / lazy_spots: env-flag toggles for module-level singletons
- stub_planner_llm / stub_synth_llm: monkeypatch the LangChain ChatModels so
  unit tests never call real APIs.
- jargon_lexicon: parsed YAML for nickname-canary tests.
- migrated_ingest_db: alembic-applied Timescale URL for integration tests
  (mirrors tests/tasks/conftest.py and tests/integration/test_ingest_e2e.py).
- qdrant_container: session-scoped Qdrant testcontainer (mirrors the fixture
  in tests/rag/conftest.py — that one isn't visible here because pytest only
  discovers conftests along the path to the test file, and tests/agent/ is
  a sibling of tests/rag/).
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import yaml
from testcontainers.core.container import DockerContainer

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]  # backend/


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
def migrated_ingest_db(timescale_sync_url, timescale_async_url) -> str:
    """Apply all alembic migrations against the shared Timescale container."""
    _run_alembic_upgrade(timescale_sync_url, timescale_async_url)
    return timescale_sync_url

# Re-export parent fixtures via pytest's plugin-discovery: simply having
# tests/conftest.py at the parent level is sufficient. No re-export here.


def _wait_qdrant_ready(host: str, port: int, timeout: float = 60.0) -> None:
    """Poll Qdrant /readyz until 200 or timeout — matches tests/rag/conftest.py."""
    deadline = time.monotonic() + timeout
    url = f"http://{host}:{port}/readyz"
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return
        except (URLError, ConnectionError, OSError) as e:
            last_err = e
        time.sleep(0.5)
    raise RuntimeError(
        f"Qdrant container did not become ready within {timeout}s: {last_err}"
    )


@pytest.fixture(scope="session")
def qdrant_container():
    """Session-scoped Qdrant container — mirror of tests/rag/conftest.py fixture."""
    ctr = (
        DockerContainer("qdrant/qdrant:v1.17.1")
        .with_exposed_ports(6333)
        .with_env("QDRANT__SERVICE__HTTP_PORT", "6333")
    )
    ctr.start()
    try:
        host = ctr.get_container_host_ip()
        port = int(ctr.get_exposed_port(6333))
        _wait_qdrant_ready(host, port)
        yield ctr
    finally:
        ctr.stop()

LEXICON_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "rag" / "benchmark" / "jargon_lexicon.yaml"
)


@pytest.fixture
def lazy_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip MLflow load at import — mirrors ml.model._maybe_load_at_import opt-out."""
    monkeypatch.setenv("TIDE_LAZY_MODEL_LOAD", "1")


@pytest.fixture
def lazy_spots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip Postgres-driven spot load at import — mirrors module-level singleton opt-out."""
    monkeypatch.setenv("TIDE_LAZY_SPOT_LOAD", "1")


@pytest.fixture
def jargon_lexicon() -> dict[str, Any]:
    """Parsed jargon_lexicon.yaml as a dict; used by nickname-canary tests."""
    if not LEXICON_PATH.exists():
        pytest.skip(f"jargon_lexicon.yaml missing at {LEXICON_PATH}")
    return yaml.safe_load(LEXICON_PATH.read_text())


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
