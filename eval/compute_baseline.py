"""Compute the Ragas baseline metrics for the golden dataset.

This module is the Wave 0 SKELETON for Phase 5 OPS-04. Wave 2 (plan 05-03)
fills the body: invokes ``eval.ragas_eval.run_eval``, hashes the golden
dataset, writes ``eval/baseline.json`` with the schema from RESEARCH §Q2
(lines 251-265).

Design constraint — Pitfall P2 (RESEARCH lines 690-692): this script is
ONLY run by an explicit operator command on ``main``. It MUST NOT
auto-commit on PRs; the Ragas CI workflow READS baseline.json but does
not REGENERATE it. Regenerating baseline.json silently masks regressions.

REPO_ROOT pattern follows PATTERNS §"REPO_ROOT path pattern" (eval/ is at
repo root, so ``parents[1]`` resolves correctly).
"""
from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def compute_baseline() -> dict:
    """Compute Ragas baseline for the 20-entry golden dataset.

    Wave 0 skeleton — returns an empty dict. Wave 2 fills the body:
    call ``run_eval``, SHA-256 the golden dataset file, write
    ``eval/baseline.json`` with computed_at + corpus_version + git_sha +
    evaluator_model + golden_dataset_sha256 + metrics.
    """
    print("compute_baseline skeleton — Wave 2 implements")
    _ = REPO_ROOT  # retain for Wave 2 (path construction)
    return {}


def main() -> int:
    compute_baseline()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["compute_baseline", "REPO_ROOT", "main"]
