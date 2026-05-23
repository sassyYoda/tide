"""Phase 6 INFRA-03 — Cloud Run Jobs single-shot entrypoints.

Each submodule (ingest_noaa, ingest_meteo, compute_solunar) is a thin wrapper
around the corresponding Celery task body that runs inline via .apply().get()
— no broker round-trip, no worker process. Cloud Run Jobs invoke the relevant
``python -m celery_app.entrypoints.<name>`` via container ``command`` override.
"""
