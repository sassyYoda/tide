"""OPS-06 delta-gate — fails CI if any Ragas metric dropped > threshold vs baseline.

Exit codes (locked by L-03 / RESEARCH §Q2 lines 268-289):

    0 — all metrics within threshold (no regression)
    1 — at least one metric dropped > threshold (REGRESSION)
    2 — baseline.json absent (caller must run compute_baseline.py first)

Per Pitfall P2 — this script NEVER rewrites ``eval/baseline.json``. The
baseline is updated ONLY via explicit ``python -m eval.compute_baseline``
on ``main``, then committed by hand. Automatic baseline rewrites would
silently mask regressions (the gate would always pass because every run
becomes its own baseline).

CLI::

    python eval/compare_to_baseline.py \\
        --baseline eval/baseline.json \\
        --current /tmp/result.json \\
        --threshold 0.05

Pattern source — gate logic mirrors
``backend/scripts/promote_production.py::_evaluate_gates`` (threshold
comparison + failures list + structured exit).
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

log = logging.getLogger(__name__)

METRICS: tuple[str, ...] = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)


def _load_metrics(path: pathlib.Path) -> dict[str, float]:
    """Read a baseline.json or a flat current-run JSON; return the metrics dict."""
    raw = json.loads(path.read_text())
    # baseline.json has metrics under a 'metrics' key; ragas_eval --out is flat.
    if isinstance(raw, dict) and "metrics" in raw and isinstance(raw["metrics"], dict):
        return {k: float(v) for k, v in raw["metrics"].items()}
    return {k: float(v) for k, v in raw.items()}


def compare(
    baseline_path: pathlib.Path,
    current_path: pathlib.Path,
    threshold: float,
) -> int:
    """Return the exit code per the L-03 matrix; print a per-metric table."""
    if not baseline_path.exists():
        log.error(
            "compare_to_baseline: %s missing. Run `python -m eval.compute_baseline` "
            "on main first, then commit the result.",
            baseline_path,
        )
        return 2

    baseline = _load_metrics(baseline_path)
    current = _load_metrics(current_path)

    # Float epsilon (~1e-9) absorbs IEEE 754 rounding at the exact-boundary case
    # (e.g. 0.80 - 0.75 = 0.050000000000000044). Without it, a deliberately
    # boundary-tuned delta would FAIL spuriously.
    _FP_EPSILON = 1e-9
    rows: list[tuple[str, float, float, float, str]] = []
    failures: list[str] = []
    for m in METRICS:
        b = baseline.get(m, 0.0)
        c = current.get(m, 0.0)
        delta = b - c  # positive = regression (current is lower than baseline)
        passed = delta <= threshold + _FP_EPSILON
        rows.append((m, b, c, delta, "PASS" if passed else "FAIL"))
        if not passed:
            failures.append(
                f"{m}: baseline={b:.3f} current={c:.3f} delta={delta:.3f} > {threshold}"
            )

    # Pretty-print table for the CI log.
    print(f"{'metric':<25} {'baseline':>10} {'current':>10} {'delta':>10}  status")
    print("-" * 70)
    for m, b, c, d, s in rows:
        print(f"{m:<25} {b:>10.3f} {c:>10.3f} {d:>10.3f}  {s}")

    if failures:
        print("\nFAILURES (exit code 1):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll metrics within threshold; gate PASSED (exit code 0).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=pathlib.Path,
        required=True,
        help="Path to eval/baseline.json (the committed baseline).",
    )
    parser.add_argument(
        "--current",
        type=pathlib.Path,
        required=True,
        help="Path to the current eval result JSON (e.g. ragas_eval --out).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="Max allowable per-metric drop vs baseline (default 0.05 per L-03).",
    )
    args = parser.parse_args()
    logging.basicConfig(level="INFO")
    return compare(args.baseline, args.current, args.threshold)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["compare", "METRICS", "main"]
