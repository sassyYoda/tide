"""SSE protocol — closed event-type enum, error-code enum, payload models, encoder.

WHY THIS FILE: Pitfall 7 — the SSE generator MUST NOT echo raw LangGraph
state. Every event passes through one of the `make_*_payload(state)` builders
defined here, which extract a fixed whitelist of fields. New fields require
explicit whitelisting.

WIRE FORMAT (per W3C SSE):
    event: <type>
    data: <json>
    \\n
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.state import ConfidenceLabel, TideAgentState


SSEEventType = Literal["progress", "partial_conditions", "recommendation", "error"]
SSEErrorCode = Literal[
    "rate_limited",
    "planner_timeout",
    "planner_out_of_scope",
    "llm_unavailable",
    "internal",
]
ProgressStage = Literal["planner", "data_fetcher", "rag_retriever", "synthesizer"]


# ─── Payload models (extra="forbid" = no accidental field leakage) ──────


class ProgressPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: ProgressStage


class PartialConditionsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spot_id: int | None = None
    spot_name: str | None = None
    conditions: dict[str, Any] | None = None
    ml_score: float | None = None
    shap_top3: list[str] | None = None
    data_age_seconds: float | None = None
    conditions_stale: bool = False


class CitationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    date: str | None = None
    chunk_id: str | None = None
    source_url: str | None = None


class RecommendationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation_text: str
    citations: list[CitationOut] = Field(default_factory=list)
    confidence_label: ConfidenceLabel
    retrieval_ok: bool = True
    ml_score_available: bool = True
    conditions_stale: bool = False
    data_age_seconds: float | None = None
    spot_id: int | None = None
    spot_name: str | None = None
    ml_score: float | None = None
    shap_top3: list[str] | None = None
    rag_latency_ms: float | None = None  # W-1: enables direct P-05 assertion in 03-06 smoke test
    # HR-01 (Phase 3 code-review): canonical fields surfaced so the route can
    # build a complete cache key without a planner-only-subgraph rewiring.
    # Not secrets — species_canonical is a normalized echo of the user's
    # nickname; time_window_label is the planner's parsed string ("Saturday
    # morning"). Cross-species cache collisions in Phase 4 read path are the
    # blast radius if these are absent — see query.py docstring.
    species_canonical: str | None = None
    time_window_label: str | None = None


class ErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: SSEErrorCode
    message: str
    partial_state: dict[str, Any] | None = None


# ─── Encoder ────────────────────────────────────────────────────────────


def encode_sse(event_type: SSEEventType, payload: BaseModel) -> str:
    """Return the W3C SSE wire format for one event."""
    body = payload.model_dump_json()
    return f"event: {event_type}\ndata: {body}\n\n"


# ─── State → payload builders (whitelist-only, Pitfall 7) ──────────────


def make_progress_payload(stage: ProgressStage) -> ProgressPayload:
    return ProgressPayload(stage=stage)


def make_partial_conditions_payload(state: TideAgentState) -> PartialConditionsPayload:
    return PartialConditionsPayload(
        spot_id=state.get("spot_id"),
        spot_name=state.get("spot_name"),
        conditions=state.get("conditions"),
        ml_score=state.get("ml_score"),
        shap_top3=state.get("shap_top3"),
        data_age_seconds=state.get("data_age_seconds"),
        conditions_stale=bool(state.get("conditions_stale", False)),
    )


def make_recommendation_payload(state: TideAgentState) -> RecommendationPayload:
    cits_in = state.get("citations") or []
    cits_out: list[CitationOut] = [
        CitationOut(
            source=c.get("source", "unknown"),
            date=c.get("date"),
            chunk_id=c.get("chunk_id"),
            source_url=c.get("source_url") or None,
        )
        for c in cits_in
    ]
    return RecommendationPayload(
        recommendation_text=state.get("recommendation_text", ""),
        citations=cits_out,
        confidence_label=state.get("confidence_label", "Low"),
        retrieval_ok=bool(state.get("retrieval_ok", True)),
        ml_score_available=bool(state.get("ml_score_available", True)),
        conditions_stale=bool(state.get("conditions_stale", False)),
        data_age_seconds=state.get("data_age_seconds"),
        spot_id=state.get("spot_id"),
        spot_name=state.get("spot_name"),
        ml_score=state.get("ml_score"),
        shap_top3=state.get("shap_top3"),
        rag_latency_ms=state.get("rag_latency_ms"),  # W-1: surfaced for P-05 smoke gate
        species_canonical=state.get("species_canonical"),  # HR-01: complete cache key
        time_window_label=state.get("time_window_label"),  # HR-01: complete cache key
    )


def make_error_payload(
    code: SSEErrorCode,
    message: str,
    state: TideAgentState | None = None,
) -> ErrorPayload:
    """Whitelist-extract partial_state from current TideAgentState (D-03.3)."""
    partial: dict[str, Any] | None = None
    if state is not None:
        partial = {
            k: v
            for k, v in {
                "species_canonical": state.get("species_canonical"),
                "spot_id": state.get("spot_id"),
                "spot_name": state.get("spot_name"),
                "intent": state.get("intent"),
                "reject_reason": state.get("reject_reason"),
                "retrieval_ok": state.get("retrieval_ok"),
                "ml_score_available": state.get("ml_score_available"),
            }.items()
            if v is not None
        }
    return ErrorPayload(code=code, message=message, partial_state=partial)
