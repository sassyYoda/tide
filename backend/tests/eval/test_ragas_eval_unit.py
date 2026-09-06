"""Unit tests for ``eval/ragas_eval.py`` — Pitfall 7 / L-02 / OQ-1 invariants.

These tests run in the QUICK suite (no docker-compose, no live HTTP, no
network). They lock the literal constants the runner depends on:

- ENDPOINT default = the live FastAPI route (Pitfall 7).
- EVALUATOR_MODEL = ``gpt-4o`` and contains no ``mini`` substring (L-02 / P9).
- ``_collect_sse`` reassembles ``recommendation_text`` + citation chunk IDs
  from a canned SSE byte stream.

Test invocation::

    cd backend && uv run pytest -x --rootdir=.. tests/eval/test_ragas_eval_unit.py -v

We use ``sys.path.insert(0, REPO_ROOT)`` so the bare ``eval`` package
(which lives at repo root, not under ``backend/``) is importable inside
backend pytest collection.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_evaluator_model_is_gpt4o() -> None:
    """L-02 / Pitfall 9: evaluator LLM MUST be gpt-4o, not -mini."""
    import eval.ragas_eval as r

    assert r.EVALUATOR_MODEL == "gpt-4o", f"Expected gpt-4o, got {r.EVALUATOR_MODEL!r}"
    assert "mini" not in r.EVALUATOR_MODEL, (
        f"Evaluator must not be a -mini variant (got {r.EVALUATOR_MODEL!r})"
    )


def test_endpoint_default_is_local_query_route() -> None:
    """Pitfall 7: Ragas MUST hit the live HTTP /api/v1/query, never build_graph()."""
    import eval.ragas_eval as r

    assert r.ENDPOINT == "http://localhost:8000/api/v1/query", (
        f"Default endpoint must target the live FastAPI route, got {r.ENDPOINT!r}"
    )


def test_sse_collector_parses_event_blocks() -> None:
    """``_collect_sse`` MUST assemble response_text + citation_chunk_ids from a canned SSE stream."""
    import eval.ragas_eval as r

    canned_lines = [
        "event: progress",
        "data: {\"stage\":\"planner\"}",
        "",
        "event: partial_conditions",
        "data: {\"spot_id\":1,\"conditions\":{\"water_temp_c\":12.5}}",
        "",
        "event: recommendation",
        (
            "data: {\"recommendation_text\":\"Stripers love the outgoing tide.\","
            "\"citations\":[{\"source\":\"njfishing\",\"chunk_id\":\"abc123\"},"
            "{\"source\":\"stripersonline\",\"chunk_id\":\"def456\"}],"
            "\"spot_id\":1,\"confidence_label\":\"High\"}"
        ),
        "",
    ]

    # Build a fake httpx async stream with .aiter_lines() yielding canned_lines.
    class _FakeResp:
        async def aiter_lines(self):
            for line in canned_lines:
                yield line

    class _FakeStreamCtx:
        async def __aenter__(self):
            return _FakeResp()

        async def __aexit__(self, *_):
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def stream(self, *_args, **_kwargs):
            return _FakeStreamCtx()

    with patch("httpx.AsyncClient", return_value=_FakeClient()):
        result = asyncio.run(r._collect_sse("test query", r.ENDPOINT))

    assert result["response"] == "Stripers love the outgoing tide."
    assert result["citation_chunk_ids"] == ["abc123", "def456"]
    assert result["spot_id"] == 1
    # partial_conditions appended as a conditions-summary string
    assert any("water_temp_c" in c for c in result["retrieved_contexts"])


def test_fetch_chunk_texts_empty_input_short_circuits() -> None:
    """Empty chunk_ids list must return empty list without opening a Qdrant client."""
    import eval.ragas_eval as r

    result = asyncio.run(r._fetch_chunk_texts([], "http://localhost:6333"))
    assert result == []


def test_fetch_chunk_texts_handles_qdrant_failure() -> None:
    """Qdrant connection failure MUST return empty strings (one per id), not raise."""
    import eval.ragas_eval as r

    fake_client = MagicMock()
    fake_client.retrieve = AsyncMock(side_effect=RuntimeError("connection refused"))
    fake_client.close = AsyncMock()

    with patch(
        "qdrant_client.AsyncQdrantClient", return_value=fake_client
    ):
        result = asyncio.run(
            r._fetch_chunk_texts(["id1", "id2"], "http://localhost:6333")
        )
    assert result == ["", ""]


def test_metric_classes_all_imported() -> None:
    """All 4 Ragas metric classes must be importable from the module."""
    import eval.ragas_eval as r

    # These are imported at module level; spot-check.
    assert hasattr(r, "Faithfulness")
    assert hasattr(r, "AnswerRelevancy")
    assert hasattr(r, "ContextPrecision")
    assert hasattr(r, "ContextRecall")
    assert hasattr(r, "LangchainLLMWrapper")
