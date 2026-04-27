"""A-10 LLM retry: tenacity stop_after_attempt(2) — 1 retry total, then raise.

The retry policy is captured at module import time via the
``TIDE_TEST_NO_LLM_BACKOFF`` env flag (mirrors the pattern in
backend/ingest/noaa_client.py — ``NOAA_TEST_NO_JITTER``). We set the env and
reload the module so the wait policy is effectively no-op for tests.
"""
from __future__ import annotations

import os

import anthropic
import httpx
import pytest

# Disable backoff so the test runs fast; this MUST be set BEFORE the
# synthesizer module is imported (decorator captures the flag at module load).
os.environ["TIDE_TEST_NO_LLM_BACKOFF"] = "1"


def _make_anthropic_503() -> anthropic.APIStatusError:
    """anthropic 0.40+ requires a real httpx.Response to construct APIStatusError.

    Build a minimal 503 response so the retry policy treats it as transient.
    """
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status_code=503, request=req, content=b"")
    return anthropic.APIStatusError("transient", response=resp, body=None)


@pytest.mark.asyncio
async def test_synthesizer_retries_once_then_raises(monkeypatch):
    """ChatAnthropic stub whose ainvoke always raises → 2 attempts, then raise."""
    import importlib

    import agent.nodes.synthesizer as synth_mod
    importlib.reload(synth_mod)

    call_count = {"n": 0}

    class _AlwaysFails:
        async def ainvoke(self, _msgs, **_kw):
            call_count["n"] += 1
            raise _make_anthropic_503()

    monkeypatch.setattr(synth_mod, "_get_synth_llm", lambda: _AlwaysFails())

    state = {
        "query": "x",
        "chunks": [],
        "retrieval_ok": True,
        "conditions_stale": False,
        "ml_score_available": False,
    }
    with pytest.raises(anthropic.APIStatusError):
        await synth_mod.synthesizer_node(state)

    assert call_count["n"] == 2, (
        f"Expected exactly 2 attempts (1 retry per A-10), got {call_count['n']}"
    )


@pytest.mark.asyncio
async def test_synthesizer_succeeds_on_second_try(monkeypatch):
    """First attempt 5xx → second attempt OK → final response returned."""
    import importlib

    import agent.nodes.synthesizer as synth_mod
    importlib.reload(synth_mod)

    call_count = {"n": 0}

    class _RecoverOnSecond:
        async def ainvoke(self, _msgs, **_kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _make_anthropic_503()

            class _R:
                content = "Fish at Barnegat. Confidence: Low"

            return _R()

    monkeypatch.setattr(synth_mod, "_get_synth_llm", lambda: _RecoverOnSecond())

    out = await synth_mod.synthesizer_node(
        {
            "query": "x",
            "chunks": [],
            "retrieval_ok": True,
            "conditions_stale": False,
            "ml_score_available": False,
        }
    )
    assert "Barnegat" in out["recommendation_text"]
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_synthesizer_succeeds_on_first_try(monkeypatch):
    """No transient — exactly 1 invocation, 0 retries."""
    import importlib

    import agent.nodes.synthesizer as synth_mod
    importlib.reload(synth_mod)

    call_count = {"n": 0}

    class _OK:
        async def ainvoke(self, _msgs, **_kw):
            call_count["n"] += 1

            class _R:
                content = "Try Barnegat Inlet at dawn. Confidence: Moderate"

            return _R()

    monkeypatch.setattr(synth_mod, "_get_synth_llm", lambda: _OK())

    out = await synth_mod.synthesizer_node(
        {
            "query": "stripers?",
            "chunks": [],
            "retrieval_ok": True,
            "conditions_stale": False,
            "ml_score_available": False,
        }
    )
    assert "Barnegat" in out["recommendation_text"]
    assert call_count["n"] == 1
