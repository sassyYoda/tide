"""OPS-06 baseline generator — runs Ragas eval and writes ``eval/baseline.json``.

Per Pitfall P2 / L-03, this script is NEVER auto-invoked in CI. It runs ONCE
on ``main`` per intentional corpus / prompt change; the resulting
``baseline.json`` is committed alongside the change. The PR CI workflow
reads the committed baseline but never rewrites it.

Assumption A1 sanity check (RESEARCH §Q2 line 624 / line 285): the script
runs Ragas TWICE and aborts with exit 3 if |Δ| > 0.05 on any metric between
the two runs. This guards against evaluator-LLM noise being mistaken for
the gate's signal floor. The COMMITTED baseline uses run #1; run #2 is
purely the sanity check.

Run::

    python -m eval.compute_baseline

The script intentionally does NOT call ``git add`` or ``git commit``; it
prints a one-line instruction for the human operator to commit by hand.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

from eval.ragas_eval import run_eval

# Local-baseline ergonomics: when run against a long-lived local docker-compose
# stack, slowapi's 20/IP/hour limiter on /api/v1/query trips after the first
# run's 20 queries — so run #2 of the Assumption A1 sanity check would silently
# eval against [error:rate_limited] rows and emit all-zero metrics. Clearing
# the slowapi keys before each run keeps the baseline truthful. In CI the
# compose stack is fresh, so the helper is a no-op (Redis empty already).
# slowapi (verified locally 2026-05-23) writes keys as `LIMITS:LIMITER/<ip>//<route>/<count>/<n>/<window>`.
# Match against the literal prefix; the trailing wildcard catches the full key.
_RATE_LIMIT_KEY_PREFIX = "LIMITS:LIMITER/"

log = logging.getLogger(__name__)

# parents[0]=eval, parents[1]=repo root  (eval/ is at repo root, not under backend/)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "eval" / "baseline.json"
GOLDEN_PATH = REPO_ROOT / "eval" / "golden_dataset.json"
SANITY_THRESHOLD = 0.05  # Assumption A1 — abort if |run1 - run2| > 0.05 on any metric


def _git_sha() -> str:
    """Return the current HEAD short SHA; 'unknown' if git fails."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _golden_sha256() -> str:
    """Return the SHA-256 of the golden dataset file content."""
    return hashlib.sha256(GOLDEN_PATH.read_bytes()).hexdigest()


def _corpus_version() -> str:
    """Read corpus version from backend/rag/corpus_metadata.json if present, else CONTEXT.md anchor."""
    metadata = REPO_ROOT / "backend" / "rag" / "corpus_metadata.json"
    if metadata.exists():
        try:
            return json.loads(metadata.read_text()).get("version", "unknown")
        except Exception:  # noqa: BLE001
            pass
    return "phase2-296docs-2026-04-27"  # CONTEXT.md anchor (RESEARCH §Q2 line 254)


def _clear_rate_limit_counters() -> None:
    """Best-effort: delete slowapi LIMITER/* keys so two back-to-back runs don't 429.

    Reads REDIS_URL from the environment (the same value the FastAPI backend
    uses), connects synchronously, scans for ``LIMITER/*`` keys, and deletes
    them. Any failure is logged and ignored — the backend may not even be
    reachable from this script's host in non-local environments.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis  # sync client — script-time only, not on the request path

        client = redis.from_url(redis_url, decode_responses=True)
        keys = list(client.scan_iter(match=f"{_RATE_LIMIT_KEY_PREFIX}*"))
        if keys:
            client.delete(*keys)
            log.info("compute_baseline: cleared %d slowapi limiter keys", len(keys))
        client.close()
    except Exception as e:  # noqa: BLE001
        log.warning("compute_baseline: could not clear limiter keys: %s", e)


def compute_baseline() -> int:
    """Compute baseline.json (with Assumption A1 sanity check). Returns exit code."""
    _clear_rate_limit_counters()
    log.info("compute_baseline: run #1 (committed baseline)")
    run1 = run_eval(GOLDEN_PATH)
    log.info("compute_baseline: run #1 result: %s", run1)

    _clear_rate_limit_counters()
    log.info("compute_baseline: run #2 (Assumption A1 noise check)")
    run2 = run_eval(GOLDEN_PATH)
    log.info("compute_baseline: run #2 result: %s", run2)

    noise_failures: list[str] = []
    for m in run1:
        delta = abs(run1[m] - run2.get(m, 0.0))
        if delta > SANITY_THRESHOLD:
            noise_failures.append(
                f"{m}: |run1 - run2| = {delta:.3f} > {SANITY_THRESHOLD}"
            )
    if noise_failures:
        log.error(
            "Ragas evaluator noise exceeds the 0.05 gate signal floor — "
            "baseline is unreliable. Investigate before committing:"
        )
        for f in noise_failures:
            log.error("  - %s", f)
        return 3

    payload = {
        "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "corpus_version": _corpus_version(),
        "git_sha": _git_sha(),
        "evaluator_model": "gpt-4o",
        "golden_dataset_sha256": _golden_sha256(),
        "metrics": run1,
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    log.info("compute_baseline: wrote %s", BASELINE_PATH)
    # Pitfall P2 — DO NOT auto-commit. Print the instruction for the operator.
    rel = BASELINE_PATH.relative_to(REPO_ROOT)
    print(
        f"now commit eval/baseline.json on main: "
        f"`git add {rel} && git commit -m 'chore(05-03): regenerate Ragas baseline'`"
    )
    return 0


def main() -> int:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return compute_baseline()


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "REPO_ROOT",
    "BASELINE_PATH",
    "GOLDEN_PATH",
    "SANITY_THRESHOLD",
    "compute_baseline",
    "main",
]
