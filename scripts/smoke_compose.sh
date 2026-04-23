#!/usr/bin/env bash
# INFRA-09 smoke: boot the compose stack, dispatch a one-shot NOAA poll,
# confirm that tidal_observations is populated within 2 min (i.e. the full
# pipeline migrator -> worker -> NOAA -> DB round-trips cleanly).
#
# Beat normally waits for its cron alignment (poll_noaa_stations fires at
# :00/:15/:30/:45), so a "wait for beat" smoke can idle up to ~15 min on a
# cold boot. This script dispatches the poll task directly once the worker
# is ready, which verifies the same code path without that delay.
#
# Requires live internet (NOAA CO-OPS must be reachable).
# Manual-verification artefact per 01-VALIDATION.md; not run by CI.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[smoke] bringing up compose stack…"
docker compose up -d --build

cleanup() {
  echo "[smoke] tearing down compose stack…"
  docker compose down -v
}
trap cleanup EXIT

echo "[smoke] waiting for worker to become ready…"
WORKER_READY_DEADLINE=$(( $(date +%s) + 60 ))
while [ "$(date +%s)" -lt "$WORKER_READY_DEADLINE" ]; do
  if docker compose logs worker 2>/dev/null | grep -q "celery@.* ready"; then
    echo "[smoke] worker ready"
    break
  fi
  sleep 2
done

echo "[smoke] dispatching one-shot poll_noaa_stations…"
docker compose exec -T worker uv run celery -A celery_app call \
  celery_app.tasks.noaa.poll_noaa_stations >/dev/null

DEADLINE=$(( $(date +%s) + 120 ))
START=$(date +%s)

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  COUNT=$(docker compose exec -T db psql -U tide -d tide -tAc \
    "SELECT count(*) FROM tidal_observations;" 2>/dev/null || echo 0)
  COUNT="${COUNT//[[:space:]]/}"
  if [ -n "$COUNT" ] && [ "$COUNT" -gt 0 ] 2>/dev/null; then
    ELAPSED=$(( $(date +%s) - START ))
    echo "[smoke] PASS (tidal_observations rows = $COUNT after ${ELAPSED}s)"
    exit 0
  fi
  sleep 5
done

echo "[smoke] FAIL: no tidal_observations rows after 120s"
docker compose logs --tail=50 worker beat
exit 1
