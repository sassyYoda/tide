"""INFRA-03 — Cloud Run Jobs single-shot entrypoint for Open-Meteo polling.

Invokes the existing Celery task body inline (no broker round-trip).
Pairs with Cloud Scheduler ``tide-ingest-meteo-trigger`` cron ``*/30 * * * *``.
"""

from __future__ import annotations

import logging
import sys

from celery_app.tasks.meteo import poll_open_meteo


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    result = poll_open_meteo.apply().get()
    logging.info("ingest_meteo: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
