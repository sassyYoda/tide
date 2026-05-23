"""INFRA-03 — Cloud Run Jobs single-shot entrypoint for NOAA polling.

Invokes the existing Celery task body inline (no broker round-trip).
Pairs with Cloud Scheduler ``tide-ingest-noaa-trigger`` cron ``*/15 * * * *``.
"""

from __future__ import annotations

import logging
import sys

from celery_app.tasks.noaa import poll_noaa_stations


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    result = poll_noaa_stations.apply().get()
    logging.info("ingest_noaa: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
