"""OPS-03 — Pin showcase Langfuse traces public + verify accessibility.

Per CONTEXT D-03 / L-09: Langfuse Hobby tier has no project-level public dashboard,
so we pin 5 individual traces via the per-trace public-share API. Each trace
represents a curated scenario (happy path, out-of-scope, rate-limit, cache hit,
partial-conditions).

PER PITFALL P7: traces pinned here are PRODUCTION traces (not CI artifacts).
The trace IDs are deterministic across re-runs ONLY when the underlying scenario
is replayed against the production backend.

PER ASSUMPTION A2 (RESEARCH §Q7 line 625) — VERIFIED 2026-05-23: the
candidate ``httpx.patch`` against ``/api/public/traces/{id}`` returns
HTTP 405 Method Not Allowed. The canonical workaround used by the Phase 3
seed pinning (2026-05-02 — see ``cdaa58b7e3d0207b8e15660a404df7c0`` in
PROJECT.md) is ``POST /api/public/ingestion`` with a ``trace-create``
event whose body carries ``{id, public: true}``. The ingestion endpoint
is asynchronous (returns 207), so the script polls the public URL
HEAD-200 for up to 45 s after ingestion.

PER OPS-03 ACCEPTANCE: each pin operation MUST HEAD-check the resulting public
URL WITHOUT auth and confirm HTTP 200 before declaring success.

Usage:
    # Pin one trace:
    LANGFUSE_PUBLIC_KEY=pk-... LANGFUSE_SECRET_KEY=sk-... \\
      python scripts/pin_showcase_traces.py pin <trace_id> \\
        --scenario happy_path_striper \\
        --description "Happy path: striper recommendation at Barnegat Inlet"

    # Verify all pinned traces still public + reachable:
    python scripts/pin_showcase_traces.py verify
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
PROJECT_ID = os.environ.get("LANGFUSE_PROJECT_ID", "cmon6k8aa015mad07jxqayowr")
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOWCASE_PATH = REPO_ROOT / "data" / "showcase_traces.json"

ALLOWED_SCENARIOS = (
    "happy_path_striper",
    "out_of_scope",
    "rate_limit",
    "cache_hit",
    "partial_conditions",
)


def _load_showcase() -> list[dict]:
    if SHOWCASE_PATH.exists():
        return json.loads(SHOWCASE_PATH.read_text())
    return []


def _save_showcase(entries: list[dict]) -> None:
    SHOWCASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SHOWCASE_PATH.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")


def _public_url(trace_id: str) -> str:
    return f"{LANGFUSE_HOST}/project/{PROJECT_ID}/traces/{trace_id}"


def _verify_public(public_url: str) -> tuple[bool, int]:
    """HEAD the public trace URL without auth; fall back to GET if HEAD unsupported.

    Returns (ok, status_code). Some Langfuse versions don't support HEAD so we
    GET on non-200 HEAD responses before declaring failure.
    """
    try:
        head = httpx.head(public_url, timeout=10.0, follow_redirects=True)
        if head.status_code == 200:
            return True, head.status_code
    except Exception as e:  # noqa: BLE001
        log.warning("HEAD %s failed: %s — falling back to GET", public_url, e)
    try:
        get = httpx.get(public_url, timeout=10.0, follow_redirects=True)
        return get.status_code == 200, get.status_code
    except Exception as e:  # noqa: BLE001
        log.error("GET %s failed: %s", public_url, e)
        return False, -1


def pin_trace(trace_id: str, scenario: str, description: str) -> int:
    """Pin one trace public via Langfuse PATCH + HEAD-verify + upsert JSON record."""
    assert scenario in ALLOWED_SCENARIOS, f"scenario must be one of {ALLOWED_SCENARIOS}"
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        log.error("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY must be set")
        return 2

    # Per Assumption A2 (verified 2026-05-23): direct PATCH /api/public/traces/{id}
    # returns 405. The canonical approach is POST /api/public/ingestion with a
    # trace-create event whose body has {id: trace_id, public: true} — this is
    # the same flow used to seed the Phase 3 showcase trace on 2026-05-02.
    # The endpoint returns 207 (queued); the public flag becomes visible after
    # asynchronous ingestion (~5-30 s).
    ingestion_url = f"{LANGFUSE_HOST}/api/public/ingestion"
    body = {
        "batch": [
            {
                "id": str(uuid.uuid4()),
                "type": "trace-create",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "body": {"id": trace_id, "public": True},
            }
        ]
    }
    try:
        r = httpx.post(ingestion_url, auth=(pk, sk), json=body, timeout=10.0)
    except Exception as e:  # noqa: BLE001
        log.error("POST %s failed: %s", ingestion_url, e)
        return 1

    if r.status_code in (404, 400):
        log.error(
            "POST ingestion returned %d — Langfuse API shape may have changed. Inspect %s",
            r.status_code,
            "https://api.reference.langfuse.com/",
        )
        log.error("Response body: %s", r.text)
        return 2
    if r.status_code >= 300:
        log.error("POST ingestion returned %d: %s", r.status_code, r.text)
        return 1

    # Asynchronous ingestion: poll the public URL until it returns 200 (max 45s).
    public_url = _public_url(trace_id)
    log.info("Ingestion accepted; polling public URL for HEAD-200 (max 45s)...")
    ok = False
    status = -1
    import time
    for _ in range(15):
        ok, status = _verify_public(public_url)
        if ok:
            break
        time.sleep(3)
    if not ok:
        log.error(
            "Public URL %s returned %d after pin — trace may not be public",
            public_url,
            status,
        )
        return 1

    # Upsert in data/showcase_traces.json
    entries = _load_showcase()
    entries = [e for e in entries if e["trace_id"] != trace_id]
    entries.append(
        {
            "scenario": scenario,
            "trace_id": trace_id,
            "url": public_url,
            "description": description,
            "pinned_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    entries.sort(key=lambda e: e["scenario"])
    _save_showcase(entries)
    log.info("Pinned %s as %s — %s", trace_id, scenario, public_url)
    return 0


def verify_traces() -> int:
    """Re-check all pinned traces; HTTP 200 without auth required for each."""
    entries = _load_showcase()
    if not entries:
        log.error("No traces in %s — pin some first", SHOWCASE_PATH)
        return 2
    failures = []
    for e in entries:
        ok, status = _verify_public(e["url"])
        if not ok:
            failures.append(f"{e['scenario']}: {e['url']} -> {status}")
        else:
            log.info("OK %s: %s", e["scenario"], e["url"])
    if failures:
        for f in failures:
            log.error(f)
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="pin_showcase_traces.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    pin = sub.add_parser("pin", help="Pin one trace public + verify URL HEAD-200")
    pin.add_argument("trace_id")
    pin.add_argument("--scenario", required=True, choices=ALLOWED_SCENARIOS)
    pin.add_argument("--description", required=True)
    sub.add_parser("verify", help="Re-check all pinned traces still return 200 anon")
    args = p.parse_args()
    if args.cmd == "pin":
        sys.exit(pin_trace(args.trace_id, args.scenario, args.description))
    elif args.cmd == "verify":
        sys.exit(verify_traces())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()


__all__ = [
    "pin_trace",
    "verify_traces",
    "main",
    "ALLOWED_SCENARIOS",
    "LANGFUSE_HOST",
    "PROJECT_ID",
    "SHOWCASE_PATH",
]
