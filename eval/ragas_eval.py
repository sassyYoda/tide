"""Ragas evaluation runner — drives the live FastAPI /api/v1/query surface.

This module powers OPS-05: the 4 Ragas metrics (faithfulness, answer_relevancy,
context_precision, context_recall) computed against the 20-entry hand-reviewed
golden dataset.

Design constraints (verified by grep + unit tests in
``backend/tests/eval/test_ragas_eval_unit.py``):

- **Pitfall 7 / RESEARCH §Q8** — Ragas evaluator MUST hit the production HTTP
  surface at ``ENDPOINT`` (POST /api/v1/query over SSE). It MUST NOT
  instantiate ``compiled_graph`` directly — that bypasses middleware, the
  rate-limit decorator, and the post-graph result cache. The grep gate
  in the CI workflow enforces that no compiled-graph builder is imported
  here — the only graph access is over HTTP.
- **L-02 / Pitfall 9 / P1** — the evaluator LLM is
  ``ChatOpenAI(model="gpt-4o")``, NEVER ``-mini``. ``-mini`` hallucinates
  context_precision / context_recall labels on jargon-heavy NJ saltwater
  text. A module-level assert enforces this so a typo at code-review time
  surfaces at import.
- **L-03** — Ragas CI uses a delta-based gate (``compare_to_baseline.py``);
  ``run_eval`` only emits raw per-metric scores. The threshold lives in
  the comparison script, not here.
- **OQ-1 resolution** — the SSE wire only carries citation IDs, not chunk
  text. ``_fetch_chunk_texts`` makes a side-channel call to Qdrant to
  resolve each ``chunk_id`` to its payload's ``metadata_summary`` (the
  text-shaped key actually written by ``backend/scripts/seed_reports.py``).
  No change to the SSE payload schema. The current payload schema lives
  under ``backend/agent/sse_protocol.py``; if ``text`` / ``body`` keys are
  added there in the future, the fallback chain below catches them.

CLI::

    python -m eval.ragas_eval [--strict] [--out PATH]

``--strict`` exits non-zero if any of the 4 expected metrics is missing.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from langchain_openai import ChatOpenAI
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)

ENDPOINT = os.environ.get("RAGAS_ENDPOINT", "http://localhost:8000/api/v1/query")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "fishing_reports"
EVALUATOR_MODEL = "gpt-4o"  # NEVER "-mini" per L-02 / Pitfall 9 / P1
assert "mini" not in EVALUATOR_MODEL, (
    "Pitfall 9 / L-02: evaluator MUST be gpt-4o, not -mini"
)

log = logging.getLogger(__name__)


# ─── SSE collector ──────────────────────────────────────────────────────


async def _collect_sse(query: str, endpoint: str = ENDPOINT) -> dict[str, Any]:
    """POST one query to the live SSE endpoint and assemble a Ragas-shaped row.

    Returns ``{"response": str, "retrieved_contexts": list[str],
    "citation_chunk_ids": list[str], "spot_id": int|None}``.

    On ``event: recommendation`` → extract ``recommendation_text`` + each
    citation's ``chunk_id``. On ``event: partial_conditions`` → append a
    conditions summary string to ``retrieved_contexts`` (per RESEARCH §Q1).
    On ``event: error`` → set ``response`` to the error code so Ragas can
    still score the row as a degraded answer (instead of crashing the
    whole eval).
    """
    response_text = ""
    retrieved_contexts: list[str] = []
    citation_chunk_ids: list[str] = []
    spot_id: int | None = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            endpoint,
            json={"query": query},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            event_name: str | None = None
            async for raw_line in resp.aiter_lines():
                if not raw_line:
                    event_name = None
                    continue
                if raw_line.startswith("event:"):
                    event_name = raw_line.removeprefix("event:").strip()
                elif raw_line.startswith("data:") and event_name:
                    try:
                        payload = json.loads(raw_line.removeprefix("data:").strip())
                    except json.JSONDecodeError:
                        log.warning("ragas_eval: malformed SSE data line: %s", raw_line[:80])
                        continue
                    if event_name == "recommendation":
                        response_text = payload.get("recommendation_text", "")
                        for c in payload.get("citations", []) or []:
                            cid = c.get("chunk_id")
                            if cid:
                                citation_chunk_ids.append(str(cid))
                        spot_id = payload.get("spot_id")
                    elif event_name == "partial_conditions":
                        cond = payload.get("conditions") or {}
                        if cond:
                            retrieved_contexts.append(
                                f"Conditions for spot_id={payload.get('spot_id')}: "
                                f"{json.dumps(cond, sort_keys=True)}"
                            )
                    elif event_name == "error":
                        # Degraded row — surface the code as the response so Ragas
                        # scores it (low) rather than crashing the whole eval.
                        code = payload.get("code", "internal")
                        response_text = response_text or f"[error:{code}]"

    return {
        "response": response_text,
        "retrieved_contexts": retrieved_contexts,
        "citation_chunk_ids": citation_chunk_ids,
        "spot_id": spot_id,
    }


# ─── Side-channel Qdrant chunk fetch (OQ-1) ─────────────────────────────


async def _fetch_chunk_texts(chunk_ids: list[str], qdrant_url: str = QDRANT_URL) -> list[str]:
    """Resolve each ``chunk_id`` to its payload text via a side-channel Qdrant call.

    OQ-1 resolution: the SSE payload (``backend/agent/sse_protocol.py``) only
    whitelists ``chunk_id`` on citations, not the chunk text. Ragas needs the
    actual text for ``Faithfulness`` + ``ContextPrecision`` + ``ContextRecall``
    to be meaningful. We fetch from the ``fishing_reports`` collection by id
    and read the text-shaped payload key.

    Fallback chain: ``metadata_summary`` (what
    ``backend/scripts/seed_reports.py`` actually writes today) → ``text`` →
    ``body``. Returns ``""`` for any id that fails to resolve so the eval
    proceeds with a degraded row instead of crashing.
    """
    if not chunk_ids:
        return []
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(url=qdrant_url, timeout=10.0)
    try:
        points = await client.retrieve(
            collection_name=COLLECTION,
            ids=chunk_ids,  # type: ignore[arg-type]
            with_payload=True,
        )
        id_to_text: dict[str, str] = {}
        for p in points:
            payload = p.payload or {}
            txt = (
                payload.get("metadata_summary")
                or payload.get("text")
                or payload.get("body")
                or ""
            )
            id_to_text[str(p.id)] = txt
        return [id_to_text.get(str(cid), "") for cid in chunk_ids]
    except Exception as e:  # noqa: BLE001 — side-channel must not crash eval
        log.warning("ragas_eval: side-channel Qdrant fetch failed: %s", e)
        return [""] * len(chunk_ids)
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


# ─── Dataset builder ────────────────────────────────────────────────────


async def _build_dataset(golden_path: Path) -> EvaluationDataset:
    """Iterate golden entries, drive SSE + Qdrant side-channel, assemble samples."""
    golden = json.loads(golden_path.read_text())
    samples: list[SingleTurnSample] = []
    for entry in golden:
        collected = await _collect_sse(entry["query"], ENDPOINT)
        chunk_texts = await _fetch_chunk_texts(
            collected["citation_chunk_ids"], QDRANT_URL
        )
        # Compose retrieved_contexts: resolved chunk text (non-empty) + the
        # conditions-summary string captured from partial_conditions.
        contexts = [t for t in chunk_texts if t] + collected["retrieved_contexts"]
        if not contexts:
            # Ragas requires at least one context for ContextPrecision /
            # ContextRecall to score. Use a placeholder when retrieval was empty
            # so the row scores low (degraded) instead of erroring.
            contexts = ["[no_context_retrieved]"]
        samples.append(
            SingleTurnSample(
                user_input=entry["query"],
                response=collected["response"] or "[no_response]",
                retrieved_contexts=contexts,
                reference=entry["expected_answer"],
            )
        )
    return EvaluationDataset(samples=samples)


# ─── Top-level eval driver ──────────────────────────────────────────────


def run_eval(golden_path: Path = Path("eval/golden_dataset.json")) -> dict[str, float]:
    """Run Ragas against ENDPOINT for every golden entry; return 4 mean scores."""
    dataset = asyncio.run(_build_dataset(golden_path))
    evaluator_llm = LangchainLLMWrapper(ChatOpenAI(model=EVALUATOR_MODEL))
    metrics = [
        Faithfulness(llm=evaluator_llm),
        AnswerRelevancy(llm=evaluator_llm),
        ContextPrecision(llm=evaluator_llm),
        ContextRecall(llm=evaluator_llm),
    ]
    result = evaluate(dataset=dataset, metrics=metrics)
    return {
        "faithfulness": float(result["faithfulness"]),
        "answer_relevancy": float(result["answer_relevancy"]),
        "context_precision": float(result["context_precision"]),
        "context_recall": float(result["context_recall"]),
    }


# ─── CLI ────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Ragas eval against the live /api/v1/query surface."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any of the 4 expected metrics is missing.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path to write the resulting metrics JSON.",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=Path("eval/golden_dataset.json"),
        help="Path to the golden dataset JSON (default eval/golden_dataset.json).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    result = run_eval(args.golden)

    expected = {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}
    missing = expected - set(result.keys())
    if missing:
        log.error("ragas_eval: missing metrics: %s", sorted(missing))
        if args.strict:
            return 2

    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ENDPOINT",
    "QDRANT_URL",
    "COLLECTION",
    "EVALUATOR_MODEL",
    "Faithfulness",
    "AnswerRelevancy",
    "ContextPrecision",
    "ContextRecall",
    "LangchainLLMWrapper",
    "run_eval",
    "_collect_sse",
    "_fetch_chunk_texts",
    "_build_dataset",
    "main",
]
