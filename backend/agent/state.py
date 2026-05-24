"""Shared agent state for the LangGraph 4-node pipeline.

TypedDict with `total=False` — every node populates a subset of keys; missing
keys are EXPLICITLY ALLOWED. This makes the D-03.3 `partial_state` payload
trivial: just dump the dict.

Graceful-degradation flags (`retrieval_ok`, `ml_score_available`,
`conditions_stale`) default to True (i.e. "all good") if the producing node
ran successfully; nodes that catch their own failures MUST flip the relevant
flag to False BEFORE returning.

Read order:
- Planner WRITES: query, intent, species_canonical, location_hint_raw,
  time_window_label, time_window_start, time_window_end, reject_reason
- Data Fetcher READS: species_canonical, location_hint_raw, time_window_*
- Data Fetcher WRITES: spot_id, spot_name, conditions, ml_score, shap_top3,
  conditions_stale, ml_score_available, data_age_seconds
- RAG Retriever READS: species_canonical, query, spot_name (for location_region)
- RAG Retriever WRITES: chunks, retrieval_ok
- Synthesizer READS: everything above
- Synthesizer WRITES: recommendation_text, citations, confidence_label

The `error` key is set ONLY by the FastAPI SSE generator when a node raises;
nodes themselves never set `error` directly.
"""
from __future__ import annotations
from typing import TypedDict, Any, Literal
from datetime import datetime

ConfidenceLabel = Literal["High", "Moderate", "Low"]
RejectReason = Literal[
    "non_mvp_species", "non_nj_geo", "non_fishing", "none"
]
SpeciesCanonical = Literal[
    "striper", "fluke", "bluefish", "weakfish", "tautog"
]
Intent = Literal[
    "fishing-recommendation",
    "comparison",
    "best-of-all",
    "definition",
    "out-of-scope",
]


class RAGChunk(TypedDict, total=False):
    chunk_id: str
    text: str
    source_name: str
    source_url: str
    title: str
    date: str  # ISO date string
    author: str
    score: float


class Citation(TypedDict, total=False):
    source: str
    date: str
    chunk_id: str
    source_url: str


class TideAgentState(TypedDict, total=False):
    # ─── Inputs (from QueryBody) ───────────────────────────────────────
    query: str
    location_hint: dict[str, Any] | None  # {lat, lon, spot_name?}

    # ─── Planner output ────────────────────────────────────────────────
    intent: Intent
    species_canonical: SpeciesCanonical | None
    location_hint_raw: str | None
    # Verbatim multi-location strings when the user asks a comparison
    # ("manasquan or sandy hook"). Only set when intent='comparison'.
    compare_locations_raw: list[str] | None
    time_window_label: str | None
    time_window_start: datetime | None
    time_window_end: datetime | None
    reject_reason: RejectReason
    planner_latency_ms: float

    # ─── Data Fetcher output ───────────────────────────────────────────
    spot_id: int | None
    spot_name: str | None
    spot_lat: float | None
    spot_lon: float | None
    spot_resolution_strategy: Literal["fuzzy_name", "haversine", "no_pin", "none"]
    conditions: dict[str, Any] | None  # tide / wind / pressure / temp summary
    ml_score: float | None
    shap_top3: list[str] | None
    conditions_stale: bool  # default False; set True if data_age_seconds > 35min
    ml_score_available: bool  # default True; set False if species not in SPECIES_MODELS
    data_age_seconds: float | None
    # Multi-spot context for comparison + best-of-all intents. Each entry:
    # {spot_id, spot_name, lat, lon, station_id, conditions, data_age_seconds}.
    # ``spot_id``/``spot_name`` on the top level is the synthesizer's
    # primary recommendation (heuristic pick — see data_fetcher).
    candidate_spots: list[dict[str, Any]] | None
    data_fetcher_latency_ms: float

    # ─── RAG Retriever output ──────────────────────────────────────────
    chunks: list[RAGChunk]
    retrieval_ok: bool  # default True; set False on Qdrant failure
    rag_latency_ms: float

    # ─── Synthesizer output ────────────────────────────────────────────
    recommendation_text: str
    citations: list[Citation]
    confidence_label: ConfidenceLabel
    synth_latency_ms: float

    # ─── Cross-cutting ─────────────────────────────────────────────────
    request_id: str  # for tracing correlation
