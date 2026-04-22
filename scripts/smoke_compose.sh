#!/usr/bin/env bash
# INFRA-09 smoke: boot the compose stack, wait up to 2 min, confirm that
# tidal_observations has been populated (i.e. the full pipeline migrator ->
# worker -> beat -> NOAA reached the DB).
#
# Requires live internet (NOAA CO-OPS + Open-Meteo must be reachable).
# This is a manual-verification artefact per 01-VALIDATION.md "Manual-Only
# Verifications"; it is not executed by CI.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[smoke] bringing up compose stack…"
docker compose up -d --build

cleanup() {
  echo "[smoke] tearing down compose stack…"
  docker compose down -v
}
trap cleanup EXIT

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
