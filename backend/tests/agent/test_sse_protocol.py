"""Whitelist + encoding tests for the SSE protocol."""
from __future__ import annotations

import json

import pytest


def test_event_type_enum_exactly_four():
    import typing

    from agent.sse_protocol import SSEEventType

    assert set(typing.get_args(SSEEventType)) == {
        "progress",
        "partial_conditions",
        "recommendation",
        "error",
    }


def test_error_code_enum_matches_d031():
    import typing

    from agent.sse_protocol import SSEErrorCode

    assert set(typing.get_args(SSEErrorCode)) == {
        "rate_limited",
        "planner_timeout",
        "planner_out_of_scope",
        "llm_unavailable",
        "internal",
    }


def test_progress_payload_rejects_extra():
    from pydantic import ValidationError

    from agent.sse_protocol import ProgressPayload

    with pytest.raises(ValidationError):
        ProgressPayload(stage="planner", leaked="hi")


def test_make_recommendation_payload_strips_chunks():
    from agent.sse_protocol import make_recommendation_payload

    state = {
        "recommendation_text": "Try Barnegat at sunrise.",
        "citations": [{"source": "NJF", "date": "2026-04-20", "chunk_id": "c1"}],
        "confidence_label": "Moderate",
        "chunks": [
            {"chunk_id": "c1", "text": "raw chunk text", "score": 0.9}
        ],  # MUST NOT leak
        "query": "where to fish?",  # MUST NOT leak
    }
    p = make_recommendation_payload(state)
    body = p.model_dump()
    assert "chunks" not in body
    assert "query" not in body
    assert body["recommendation_text"] == "Try Barnegat at sunrise."
    assert body["citations"][0]["source"] == "NJF"
    assert body["confidence_label"] == "Moderate"


def test_make_partial_conditions_payload_strips_chunks():
    from agent.sse_protocol import make_partial_conditions_payload

    state = {
        "spot_id": 7,
        "spot_name": "Barnegat Inlet",
        "conditions": {"tide": "incoming"},
        "chunks": [{"text": "raw"}],
        "recommendation_text": "leak?",
    }
    p = make_partial_conditions_payload(state)
    body = p.model_dump()
    assert "chunks" not in body
    assert "recommendation_text" not in body
    assert body["spot_id"] == 7


def test_encode_sse_wire_format():
    from agent.sse_protocol import encode_sse, make_progress_payload

    wire = encode_sse("progress", make_progress_payload("planner"))
    lines = wire.splitlines()
    assert lines[0] == "event: progress"
    assert lines[1].startswith("data: ")
    payload = json.loads(lines[1].removeprefix("data: "))
    assert payload == {"stage": "planner"}
    assert wire.endswith("\n\n")


def test_make_error_payload_partial_state_whitelist():
    from agent.sse_protocol import make_error_payload

    state = {
        "species_canonical": "striper",
        "spot_id": 7,
        "intent": "fishing-recommendation",
        "query": "should not leak",
        "chunks": [{"text": "should not leak"}],
        "recommendation_text": "should not leak",
    }
    p = make_error_payload("planner_timeout", "Planner exceeded 2s", state)
    assert p.code == "planner_timeout"
    assert p.message == "Planner exceeded 2s"
    assert p.partial_state == {
        "species_canonical": "striper",
        "spot_id": 7,
        "intent": "fishing-recommendation",
    }
    body = p.model_dump_json()
    assert "should not leak" not in body


def test_make_error_payload_invalid_code_rejected():
    from pydantic import ValidationError

    from agent.sse_protocol import make_error_payload

    with pytest.raises(ValidationError):
        make_error_payload("not_in_enum", "x", None)  # type: ignore[arg-type]


def test_recommendation_payload_includes_rag_latency_ms():
    """W-1: rag_latency_ms surfaced on the wire so 03-06 smoke can assert P-05 directly."""
    from agent.sse_protocol import make_recommendation_payload

    state = {
        "recommendation_text": "x",
        "confidence_label": "High",
        "rag_latency_ms": 412.5,
    }
    p = make_recommendation_payload(state)
    body = p.model_dump()
    assert body["rag_latency_ms"] == 412.5
