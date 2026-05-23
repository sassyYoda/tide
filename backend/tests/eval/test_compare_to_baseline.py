"""Unit tests for ``eval/compare_to_baseline.py`` — L-03 delta-gate semantics.

Exit codes locked by the plan (RESEARCH §Q2 lines 268-289):

    0 — all metrics within threshold (no regression)
    1 — at least one metric dropped > threshold (REGRESSION)
    2 — baseline.json absent (caller must run compute_baseline.py first)

These are pure-logic tests — no docker, no network. They run in the quick suite.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def _write_baseline(path: Path, metrics: dict[str, float]) -> None:
    """Write a baseline.json with the full schema."""
    payload = {
        "computed_at": "2026-05-23T00:00:00Z",
        "corpus_version": "phase2-296docs-2026-04-27",
        "git_sha": "deadbeef",
        "evaluator_model": "gpt-4o",
        "golden_dataset_sha256": "abc123",
        "metrics": metrics,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _write_current(path: Path, metrics: dict[str, float]) -> None:
    """Write a current-run JSON (flat — what ragas_eval --out produces)."""
    path.write_text(json.dumps(metrics, indent=2, sort_keys=True))


def test_exit_code_2_when_baseline_missing(tmp_path: Path) -> None:
    from eval.compare_to_baseline import compare

    baseline = tmp_path / "does_not_exist.json"
    current = tmp_path / "current.json"
    _write_current(current, {m: 0.8 for m in METRICS})

    assert compare(baseline, current, threshold=0.05) == 2


def test_exit_code_0_when_within_threshold(tmp_path: Path) -> None:
    """Identical metrics → no regression → exit 0."""
    from eval.compare_to_baseline import compare

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    metrics = {m: 0.8 for m in METRICS}
    _write_baseline(baseline, metrics)
    _write_current(current, metrics)

    assert compare(baseline, current, threshold=0.05) == 0


def test_exit_code_1_when_regression(tmp_path: Path) -> None:
    """Baseline=0.80, current=0.70 (delta 0.10 > 0.05) → exit 1."""
    from eval.compare_to_baseline import compare

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_baseline(baseline, {m: 0.80 for m in METRICS})
    _write_current(current, {m: 0.70 for m in METRICS})

    assert compare(baseline, current, threshold=0.05) == 1


def test_exit_code_1_when_one_metric_regresses(tmp_path: Path) -> None:
    """Only faithfulness regresses; the other 3 are fine → still exit 1."""
    from eval.compare_to_baseline import compare

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_baseline(baseline, {m: 0.80 for m in METRICS})
    cur = {m: 0.80 for m in METRICS}
    cur["faithfulness"] = 0.65  # delta = 0.15 > 0.05
    _write_current(current, cur)

    assert compare(baseline, current, threshold=0.05) == 1


def test_exit_code_0_when_improvement(tmp_path: Path) -> None:
    """Baseline=0.70, current=0.80 (improvement, negative delta) → exit 0."""
    from eval.compare_to_baseline import compare

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_baseline(baseline, {m: 0.70 for m in METRICS})
    _write_current(current, {m: 0.80 for m in METRICS})

    assert compare(baseline, current, threshold=0.05) == 0


def test_exit_code_0_at_threshold_boundary(tmp_path: Path) -> None:
    """Delta exactly equal to threshold should PASS (delta <= threshold)."""
    from eval.compare_to_baseline import compare

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_baseline(baseline, {m: 0.80 for m in METRICS})
    _write_current(current, {m: 0.75 for m in METRICS})  # exact 0.05 delta

    assert compare(baseline, current, threshold=0.05) == 0
