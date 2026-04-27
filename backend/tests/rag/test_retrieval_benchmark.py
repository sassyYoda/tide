"""R-05 — benchmark runner + gate assertion."""
from __future__ import annotations

import asyncio

import pytest


def test_recall_runner_raises_when_benchmark_missing(tmp_path, monkeypatch):
    """If curated benchmark file is absent, run() raises FileNotFoundError."""
    from scripts import retrieval_benchmark as rb

    monkeypatch.setattr(rb, "BENCHMARK_PATH", tmp_path / "missing.yaml")
    with pytest.raises(FileNotFoundError):
        asyncio.run(rb.run(assert_gate=False))


def test_recall_gate_constant_is_075():
    from scripts.retrieval_benchmark import RECALL_GATE

    assert RECALL_GATE == 0.75


def test_benchmark_yaml_schema_when_committed():
    """Post-curation: jargon_queries.yaml must have 20 cases with required fields.

    The plan ships a *draft* (LLM-shaped, expected_report_ids empty) under
    `status: draft-pending-curation` at the human-action checkpoint. The
    schema test skips while the file is in draft mode and only enforces the
    full-id requirement once the user removes the draft marker.
    """
    import pathlib

    import yaml

    p = (
        pathlib.Path(__file__).resolve().parents[3]
        / "backend"
        / "rag"
        / "benchmark"
        / "jargon_queries.yaml"
    )
    if not p.exists():
        pytest.skip("Benchmark not yet curated by user")
    doc = yaml.safe_load(p.read_text())
    draft_statuses = {"draft-pending-curation", "llm-drafted-awaiting-human-review"}
    if isinstance(doc, dict) and doc.get("status") in draft_statuses:
        pytest.skip(f"Benchmark in draft state ({doc.get('status')}) — awaiting human curation")
    cases = doc.get("cases") if isinstance(doc, dict) else doc
    assert len(cases) == 20, f"Expected 20 benchmark queries, got {len(cases)}"
    for c in cases:
        assert "query" in c
        assert "expected_report_ids" in c
        assert len(c["expected_report_ids"]) >= 1
