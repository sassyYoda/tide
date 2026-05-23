"""Compare a current Ragas eval run against the committed baseline.

This module is the Wave 0 SKELETON for Phase 5 OPS-04 / L-03. Wave 2
(plan 05-03) fills the body: load baseline + current JSON, compute per-metric
delta, fail (exit 1) if any of the 4 Ragas metrics dropped by more than the
``--threshold`` (default 0.05) vs baseline.

Design constraints:

- L-03: delta-based gate (NOT absolute threshold). Minor prompt tweaks that
  move metrics 0.01-0.02 should NOT fail the PR.
- Pitfall P2 (RESEARCH lines 690-692): a missing baseline file exits 2 with
  a bootstrap instruction; it MUST NOT auto-commit a new baseline. Operator
  has to run ``python -m eval.compute_baseline`` on ``main`` and commit
  manually.
- Exit codes: 0 pass, 1 Δ > threshold on any metric, 2 baseline.json missing.

Usage:
    python eval/compare_to_baseline.py \\
        --baseline eval/baseline.json \\
        --current /tmp/result.json \\
        --threshold 0.05
"""
from __future__ import annotations

import argparse


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Path to eval/baseline.json")
    parser.add_argument("--current", required=True, help="Path to the current eval result JSON")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="Max allowable per-metric drop vs baseline (default 0.05)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    print(
        f"compare_to_baseline skeleton — Wave 2 implements. "
        f"baseline={args.baseline} current={args.current} threshold={args.threshold}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
