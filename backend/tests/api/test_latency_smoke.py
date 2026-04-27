"""Phase 3 closing latency smoke test.

Asserts the agent's end-to-end latency budgets (CONTEXT L-09) on a 10-query
spread:
- P-01 / A-11 p50 total ≤ 5s
- P-02 / A-11 p95 total ≤ 8s
- P-03 / A-07 p95 first-byte ≤ 2s
- P-05 p95 RAG leg ≤ 800ms

Skip conditions:
- ANTHROPIC_API_KEY == "test-key" (Wave 0 placeholder, no real LLM)
- SPECIES_MODELS empty (no promoted ML model — real recommendation can't be
  generated)

When all conditions are met, runs against the live test_client (which uses
testcontainers for DB + Redis; ANTHROPIC + OPENAI keys come from
backend/.env via Settings).

W-1: ``rag_latency_ms`` IS now whitelisted on RecommendationPayload (per
03-01 Task 3 schema bump) so this smoke enforces P-05 (≤800ms p95) directly
from the wire. Langfuse trace inspection (Task 3) remains the OPS-02/OPS-03
acceptance for richer per-span observability.
"""
from __future__ import annotations

import os
import time

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


SMOKE_QUERIES = [
    "Where can I catch stripers at Barnegat Inlet on Saturday morning?",
    "Best fluke spots on outgoing tide this evening?",
    "Bluefish action at Manasquan Inlet today?",
    "Sandy Hook tautog on green crab tomorrow afternoon?",
    "Weakfish tides at Island Beach State Park this week?",
    "Schoolies running at the inlet on a NE wind?",
    "Doormat fluke south side jetty?",
    "Cocktail blues at the back bay this evening?",
    "Tog spots on the rocks tomorrow morning?",
    "Linesider season opener Sandy Hook?",
]


def _skip_if_env_incomplete() -> None:
    """Precise skip messages so unmet preconditions are visible.

    Settings() loads ANTHROPIC_API_KEY from backend/.env (NOT os.environ), so
    we read the live value via app.config.settings rather than the shell env.
    """
    try:
        from app.config import settings
    except Exception as e:
        pytest.skip(f"app.config import failed: {e}")
    api_key = (settings.anthropic_api_key or "").strip()
    if api_key in ("", "test-key"):
        pytest.skip(
            "ANTHROPIC_API_KEY not provisioned (still 'test-key' or empty in "
            "Settings). Latency smoke needs a real LLM. Set the key in "
            "backend/.env or run this test only against staging."
        )
    try:
        from ml.model import SPECIES_MODELS
    except Exception as e:
        pytest.skip(f"ml.model import failed: {e}")
    if not SPECIES_MODELS:
        pytest.skip(
            "SPECIES_MODELS empty (no production model promoted). "
            "P-06/P-02 latency cannot be exercised — re-run after Phase 2 "
            "promotion."
        )


def _percentile(samples: list[float], pct: float) -> float:
    """Inclusive percentile, no numpy dep. samples assumed unsorted."""
    if not samples:
        return float("nan")
    s = sorted(samples)
    n = len(s)
    idx = max(0, min(n - 1, int(round(pct * (n - 1)))))
    return s[idx]


@pytest.mark.asyncio
async def test_latency_smoke_p95_under_8s(test_client, lazy_models, lazy_spots):
    """End-to-end smoke against the live agent endpoint.

    Records per-query: first-byte ms, total ms, rag-leg ms.
    Asserts the four latency gates from CONTEXT L-09.
    """
    _skip_if_env_incomplete()

    from tests.api.conftest import parse_sse_stream

    first_byte_samples: list[float] = []
    total_samples: list[float] = []
    rag_leg_samples: list[float] = []

    for q in SMOKE_QUERIES:
        body = {"query": q}
        t0 = time.perf_counter()
        first_byte_ms: float | None = None
        all_chunks: list[bytes] = []

        with test_client["client"].stream(
            "POST", "/api/v1/query", json=body
        ) as resp:
            for chunk in resp.iter_bytes(chunk_size=1024):
                if chunk and first_byte_ms is None:
                    first_byte_ms = (time.perf_counter() - t0) * 1000
                all_chunks.append(chunk)
        total_ms = (time.perf_counter() - t0) * 1000

        first_byte_samples.append(first_byte_ms or total_ms)
        total_samples.append(total_ms)

        # W-1: rag_latency_ms is whitelisted on RecommendationPayload (added
        # in 03-01 Task 3). Read it directly from the wire — strict P-05 gate.
        events = parse_sse_stream(b"".join(all_chunks))
        rag_ms_for_this_query: float | None = None
        for ev_type, payload in events:
            if ev_type == "recommendation" and isinstance(payload, dict):
                rag_ms_for_this_query = payload.get("rag_latency_ms")
                break

        # If the recommendation event was missing rag_latency_ms (e.g. agent
        # short-circuited before rag_retriever ran — out-of-scope path), skip
        # this sample for the rag gate.
        if rag_ms_for_this_query is not None:
            rag_leg_samples.append(float(rag_ms_for_this_query))

    # Compute gates
    p50_total = _percentile(total_samples, 0.50)
    p95_total = _percentile(total_samples, 0.95)
    p95_first = _percentile(first_byte_samples, 0.95)
    p95_rag = _percentile(rag_leg_samples, 0.95)

    print(
        f"\nLatency smoke ({len(SMOKE_QUERIES)} queries):\n"
        f"  total p50={p50_total:.0f}ms p95={p95_total:.0f}ms\n"
        f"  first-byte p95={p95_first:.0f}ms\n"
        f"  rag-leg p95={p95_rag:.0f}ms\n"
        f"  totals: {[round(t) for t in total_samples]}\n"
        f"  first-bytes: {[round(t) for t in first_byte_samples]}\n"
        f"  rag-legs: {[round(t) for t in rag_leg_samples]}\n"
    )

    failures: list[str] = []
    if p50_total > 5000:
        failures.append(f"P-01: p50 total {p50_total:.0f}ms > 5000ms")
    if p95_total > 8000:
        failures.append(f"P-02: p95 total {p95_total:.0f}ms > 8000ms")
    if p95_first > 2000:
        failures.append(f"P-03/A-07: p95 first-byte {p95_first:.0f}ms > 2000ms")
    # W-1: P-05 strict gate — rag_latency_ms is now wire-observable.
    # If no rag samples were captured (all queries short-circuited at
    # planner), skip the gate rather than fail spuriously.
    if rag_leg_samples and p95_rag > 800:
        failures.append(f"P-05: rag-leg p95 {p95_rag:.0f}ms > 800ms")

    assert not failures, "\n".join(failures)
