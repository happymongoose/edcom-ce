#!/usr/bin/env bash
# Run from a Docker CLI driver with this checkout mounted at its host path.
# Destructive only to anonymous, uniquely named fixtures created here.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK="edcom-inbox-tests-$$-$RANDOM"
DB_IMAGE="${DB_IMAGE:-edcom/database-dev}"
API_IMAGE="${API_IMAGE:-edcom/api-dev}"
CACHE_IMAGE="${CACHE_IMAGE:-redis:7.2-alpine@sha256:29e8589c3f9ba699b5f7aa4b3c7733c58852a3626439e619aa0ee78de08c6ca0}"
DB_ID=""; CACHE_ID=""; API_ID=""
cleanup() {
  for id in "$API_ID" "$DB_ID" "$CACHE_ID"; do
    if [[ -n "$id" ]]; then docker rm -fv "$id" >/dev/null; fi
  done
  docker network rm "$NETWORK" >/dev/null
}
docker network create --internal "$NETWORK" >/dev/null
trap cleanup EXIT
DB_ID=$(docker run -d --memory 2g --cpus 2 --network "$NETWORK" --network-alias database \
  -v "$ROOT/schema:/docker-entrypoint-initdb.d:ro" --entrypoint docker-entrypoint.sh "$DB_IMAGE" postgres)
CACHE_ID=$(docker run -d --memory 256m --network "$NETWORK" --network-alias cache "$CACHE_IMAGE")
for attempt in $(seq 1 60); do
  if docker exec "$DB_ID" pg_isready -h 127.0.0.1 -U edcom >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$DB_ID" pg_isready -h 127.0.0.1 -U edcom
API_ID=$(docker create --memory 2g --cpus 2 --network "$NETWORK" \
  -e postgres_conn=postgres://edcom:edcom@database:5432/edcom \
  -e EDCOM_DISPOSABLE_VOLUME_CHECK=1 -e VOLUME_CONTACTS="${VOLUME_CONTACTS:-70000}" \
  -v "$ROOT/api:/api:ro" -v "$ROOT/scripts:/scripts:ro" -v "$ROOT/test:/test:ro" \
  -v "$ROOT/dev:/devtools:ro" -v "$ROOT/data/setup:/setup:ro" \
  -v "$ROOT/config/crontab:/config/crontab:ro" --tmpfs /logs --tmpfs /buckets \
  -e INBOX_FULL_SUITE="${INBOX_FULL_SUITE:-0}" \
  -e TEST_MODULES="${TEST_MODULES:-test_webhook_inbox test_automation_email_events test_automation_subject_tests}" \
  --entrypoint sh "$API_IMAGE" -c '
    set -eu
    mkdir -p /buckets/data /buckets/images /buckets/blocks /buckets/transfer
    python /scripts/run_db_migrations.py
    cd /test
    python setup.py
    if [ "$INBOX_FULL_SUITE" = 1 ]; then
      python -m unittest discover -v
    else
      python -m unittest -v $TEST_MODULES
    fi
  ')
docker start -a "$API_ID"
code=$(docker inspect -f '{{.State.ExitCode}}' "$API_ID")
exit "$code"
