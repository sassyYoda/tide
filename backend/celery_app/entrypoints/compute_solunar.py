"""INFRA-03 — Cloud Run Jobs single-shot entrypoint for solunar compute.

Invokes the existing Celery task body inline (no broker round-trip).
Pairs with Cloud Scheduler ``tide-compute-solunar-trigger`` cron ``0 * * * *``.
"""

from __future__ import annotations

import logging
import sys

from celery_app.tasks.solunar import compute_solunar_task


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    result = compute_solunar_task.apply().get()
    logging.info("compute_solunar: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
