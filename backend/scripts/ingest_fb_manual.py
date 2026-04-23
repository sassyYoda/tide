"""Ingest manual Facebook transcription CSV (D-07 amendment).

User transcribes FB-group posts into data/fb_transcriptions.csv (column
whitelist below). This script reads it, builds RawReport records with FB
attribution (source_description, redacted handle), and emits JSONL.
"""
from __future__ import annotations

import csv
import logging
import os
import pathlib
from datetime import date, datetime, timezone

from ingest.reports.schema import RawReport

log = logging.getLogger(__name__)

CSV_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "fb_transcriptions.csv"
OUTPUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "raw_reports"

ALLOWED_COLUMNS = (
    "post_date",       # YYYY-MM-DD
    "group_name",      # "NJ Striper Zone"
    "author_handle_redacted",  # "[redacted]" or first name only per privacy
    "body",            # transcribed text
    "water_body_hint",
    "species_hints",
)


def load_rows() -> list[RawReport]:
    if not CSV_PATH.exists():
        log.info("No FB CSV at %s — skipping", CSV_PATH)
        return []
    out: list[RawReport] = []
    with CSV_PATH.open() as f:
        reader = csv.DictReader(f)
        missing = set(ALLOWED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"fb_transcriptions.csv missing columns: {missing}")
        for row in reader:
            filtered = {k: row.get(k, "").strip() for k in ALLOWED_COLUMNS}
            if not filtered["body"]:
                continue
            try:
                pdate = date.fromisoformat(filtered["post_date"]) if filtered["post_date"] else None
            except ValueError:
                pdate = None
            description = (
                f"FB group '{filtered['group_name']}' — "
                f"post by {filtered['author_handle_redacted'] or '[redacted]'} — "
                f"{pdate.isoformat() if pdate else 'date unknown'}"
            )
            out.append(
                RawReport(
                    source_name="facebook_manual",
                    source_url=None,
                    source_description=description,
                    original_author_handle=filtered["author_handle_redacted"] or None,
                    scrape_date=datetime.now(timezone.utc),
                    post_date=pdate,
                    body=filtered["body"][:8000],
                    ingest_notes={
                        "water_body_hint": filtered["water_body_hint"],
                        "species_hints": filtered["species_hints"],
                    },
                )
            )
    return out


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"fb_manual_{ts}.jsonl"
    with out_path.open("w") as fout:
        for r in rows:
            fout.write(r.model_dump_json() + "\n")
    log.info("Wrote %d FB records → %s", len(rows), out_path)
    return len(rows)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    main()
