"""Consolidate subset.jsonl + any additional raw scrapes + FishBrain top-up → corpus.jsonl.

Deduplicates by (source_url + source_name + first 1000 chars of body) hash.
Pitfall #8 — re-runs must not re-embed; Qdrant upsert idempotency depends on
stable point IDs, and re-extracting already-processed records wastes OpenAI
spend.

Flow:
  1. Read existing subset.jsonl (StructuredReport JSONL) → seed dedupe set
  2. Walk data/raw_reports/*.jsonl, filter out anything already represented
  3. Run extract_fields.run() on the new raw records only
  4. Write consolidated corpus.jsonl = subset records + new structured records
"""
from __future__ import annotations

import hashlib
import logging
import os
import pathlib

import structlog

log = structlog.get_logger()

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw_reports"
STRUCT_DIR = REPO_ROOT / "data" / "structured_reports"
SUBSET_PATH = STRUCT_DIR / "subset.jsonl"
CORPUS_PATH = STRUCT_DIR / "corpus.jsonl"


def _content_hash(body: str, source_url: str | None, source_name: str) -> str:
    """Stable dedupe key.

    Uses sha256 over (source_url + source_name + first 1000 chars of body)
    to catch both URL-level dups (same forum thread re-scraped) and
    description-level dups (same FB post transcribed twice). 16 hex chars
    of sha256 → ~64 bits, ample for collision avoidance at corpus scale.
    """
    key = (source_url or "") + "|" + source_name + "|" + body[:1000]
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def main() -> int:
    # Imported here so REPO_ROOT/RAW_DIR/etc. monkeypatching in tests takes
    # effect before the heavy app-config-importing modules are loaded.
    from ingest.reports.schema import RawReport, StructuredReport
    from scripts import extract_fields

    STRUCT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Identify already-extracted records (subset.jsonl) and seed dedupe set
    subset_hashes: set[str] = set()
    subset_records: list[str] = []
    if SUBSET_PATH.exists():
        for line in SUBSET_PATH.read_text().splitlines():
            if not line.strip():
                continue
            rec = StructuredReport.model_validate_json(line)
            h = _content_hash(rec.raw.body, rec.raw.source_url, rec.raw.source_name)
            subset_hashes.add(h)
            subset_records.append(line)

    # 2. Collect raw records from all data/raw_reports/*.jsonl not already
    #    represented in subset.jsonl (or earlier raw files).
    new_raw: list[str] = []
    seen_hashes = set(subset_hashes)
    if RAW_DIR.exists():
        for raw_path in sorted(RAW_DIR.glob("*.jsonl")):
            for line in raw_path.read_text().splitlines():
                if not line.strip():
                    continue
                raw = RawReport.model_validate_json(line)
                h = _content_hash(raw.body, raw.source_url, raw.source_name)
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)
                new_raw.append(line)

    # 3. Extract structured fields for the new raw records (cost-bounded:
    #    only NEW records hit the OpenAI API).
    new_records: list[str] = []
    if new_raw:
        new_raw_path = STRUCT_DIR / ".new_raw.jsonl"
        new_struct_path = STRUCT_DIR / ".new_struct.jsonl"
        new_raw_path.write_text("\n".join(new_raw) + "\n")
        try:
            stats = extract_fields.run(new_raw_path, new_struct_path)
            log.info("corpus-extract-stats", **stats)
            if new_struct_path.exists():
                new_records = [
                    line
                    for line in new_struct_path.read_text().splitlines()
                    if line.strip()
                ]
        finally:
            new_raw_path.unlink(missing_ok=True)
            new_struct_path.unlink(missing_ok=True)

    # 4. Write consolidated corpus.jsonl (subset + newly extracted)
    all_lines = subset_records + new_records
    CORPUS_PATH.write_text("\n".join(all_lines) + ("\n" if all_lines else ""))
    log.info(
        "corpus-written",
        path=str(CORPUS_PATH),
        count=len(all_lines),
        subset_count=len(subset_records),
        new_count=len(new_records),
    )
    return len(all_lines)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    main()
