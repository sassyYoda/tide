#!/bin/bash
# Cloud Run startup shim — explodes JSON-grouped Secret Manager bundles
# into the flat environment-variable shape the Pydantic Settings model
# expects, then execs whatever command was passed (defaults to uvicorn).
#
# Phase 6 design (Pitfall P11 — Secret Manager free-tier 6 active versions)
# groups related secrets into JSON blobs:
#   tide-db        → {"password": "...", "DATABASE_URL": "...", "DATABASE_SYNC_URL": "..."}
#   tide-langfuse  → {"public_key": "...", "secret_key": "...", "host": "..."}
# Cloud Run injects each as a single env var named DATABASE_BUNDLE / LANGFUSE_BUNDLE.
# This script unpacks them BEFORE the app imports app.config.
#
# Usage:
#   CMD ["/app/start-cloudrun.sh"]                     # backend → uvicorn
#   CMD ["/app/start-cloudrun.sh", "python", "-m", "celery_app.entrypoints.ingest_noaa"]
set -e

py() { python3 -c "import sys, json; d = json.loads(sys.stdin.read()); print(d.get('$1', ''))"; }

if [ -n "$DATABASE_BUNDLE" ]; then
  export DATABASE_URL=$(printf '%s' "$DATABASE_BUNDLE" | py DATABASE_URL)
  export DATABASE_SYNC_URL=$(printf '%s' "$DATABASE_BUNDLE" | py DATABASE_SYNC_URL)
  export DB_PASSWORD=$(printf '%s' "$DATABASE_BUNDLE" | py password)
fi

if [ -n "$LANGFUSE_BUNDLE" ]; then
  export LANGFUSE_PUBLIC_KEY=$(printf '%s' "$LANGFUSE_BUNDLE" | py public_key)
  export LANGFUSE_SECRET_KEY=$(printf '%s' "$LANGFUSE_BUNDLE" | py secret_key)
  export LANGFUSE_HOST=$(printf '%s' "$LANGFUSE_BUNDLE" | py host)
fi

if [ $# -eq 0 ]; then
  exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
else
  # Resolve `python` to the venv's interpreter so `python -m ...` works
  # without `uv run` (which would attempt a network resolve at startup).
  if [ "$1" = "python" ]; then
    shift
    exec /app/.venv/bin/python "$@"
  fi
  exec "$@"
fi
