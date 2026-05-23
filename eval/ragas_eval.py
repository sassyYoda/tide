"""Ragas evaluation runner — drives the live FastAPI /api/v1/query surface.

This module is the Wave 0 SKELETON for Phase 5 OPS-04 (Ragas CI gate). Wave 2
(plan 05-03) fills the body: SSE collector → Ragas SingleTurnSample → metrics
aggregation. The Wave 0 contract here is just that the module imports cleanly,
exports the public surface, and the CLI exits 0 when invoked.

Design constraints (DO NOT relitigate in Wave 2):

- Pitfall 7 (RESEARCH §Q8): Ragas evaluator MUST hit the production HTTP
  surface at ENDPOINT (POST /api/v1/query over SSE). It MUST NOT instantiate
  ``compiled_graph`` directly — that bypasses middleware, rate-limit, and the
  result cache.
- L-02 / Pitfall 9: the evaluator LLM is ``ChatOpenAI(model="gpt-4o")``,
  NEVER ``-mini``. ``-mini`` hallucinates context_precision / context_recall
  labels on jargon-heavy NJ saltwater text.
- L-03: Ragas CI uses a delta-based gate (``compare_to_baseline.py``);
  ``run_eval`` only emits raw per-metric scores.

Recipe source: ``.planning/phases/05-llmops-evaluation/05-RESEARCH.md`` §Q1
(lines 114-224).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

ENDPOINT = "http://localhost:8000/api/v1/query"


def run_eval(golden_path: Path = Path("eval/golden_dataset.json")) -> dict:
    """Run the Ragas eval against ENDPOINT.

    Wave 0 skeleton — returns an empty dict. Wave 2 fills the body per
    RESEARCH §Q1: load golden_path, drive SSE collector against ENDPOINT
    for each entry, build SingleTurnSamples, evaluate with the 4 Ragas
    metrics (Faithfulness, AnswerRelevancy, ContextPrecision,
    ContextRecall), aggregate, return as dict.
    """
    print("ragas_eval skeleton — Wave 2 implements")
    _ = asyncio  # retain import for Wave 2 (async SSE collector)
    _ = json     # retain import for Wave 2 (golden_path parsing)
    _ = httpx    # retain import for Wave 2 (httpx.AsyncClient streaming)
    _ = golden_path
    return {}


def main() -> int:
    run_eval()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_eval", "ENDPOINT", "main"]
