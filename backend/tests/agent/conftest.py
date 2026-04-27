"""Phase 3 agent test fixtures.

Re-exports parent fixtures (db, redis, qdrant, respx_mock, etc.) and adds:
- lazy_models / lazy_spots: env-flag toggles for module-level singletons
- stub_planner_llm / stub_synth_llm: monkeypatch the LangChain ChatModels so
  unit tests never call real APIs.
- jargon_lexicon: parsed YAML for nickname-canary tests.
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml

# Re-export parent fixtures via pytest's plugin-discovery: simply having
# tests/conftest.py at the parent level is sufficient. No re-export here.

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
