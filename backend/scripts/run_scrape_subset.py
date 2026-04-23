"""D-10 step 1 — scrape + extract the ~150-200-report subset for week-4 demo.

Pipeline:
  1. Run scrape_forum.main() (NJFishing + SurfTalk HTML)
  2. Run ingest_fb_manual.main() (reads data/fb_transcriptions.csv if present)
  3. Concatenate all raw JSONL → run extract_fields.run() → subset.jsonl

Reddit is deferred per CONTEXT.md D-06.1 — no Reddit scraper in this plan.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib

import structlog

log = structlog.get_logger()

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw_reports"
STRUCT_DIR = REPO_ROOT / "data" / "structured_reports"


async def main() -> dict:
    from scripts import extract_fields, ingest_fb_manual, scrape_forum
    stats: dict = {}

    # 1. Forum (manifest-driven)
    manifest_path = REPO_ROOT / "data" / "forum_manifest.json"
    if manifest_path.exists():
        paths = json.loads(manifest_path.read_text())
        stats["forum"] = await scrape_forum.main(paths)
    else:
        log.warning("No data/forum_manifest.json — skipping forum scrape")
        stats["forum"] = 0

    # 2. FB manual
    stats["fb_manual"] = ingest_fb_manual.main()

    # 3. Extract structured fields across all raw JSONL in RAW_DIR
    STRUCT_DIR.mkdir(parents=True, exist_ok=True)
    subset_path = STRUCT_DIR / "subset.jsonl"
    combined_raw = STRUCT_DIR / ".combined_raw.jsonl"
    with combined_raw.open("w") as fout:
        for p in sorted(RAW_DIR.glob("*.jsonl")):
            fout.write(p.read_text())
    stats["extract"] = extract_fields.run(combined_raw, subset_path)
    combined_raw.unlink(missing_ok=True)
    log.info("subset pipeline complete", **stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(main())
