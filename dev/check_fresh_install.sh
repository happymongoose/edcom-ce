#!/usr/bin/env bash
# Disposable, network-isolated base-schema + current-source migration rehearsal.
# Does not attach the application database, config, queues or customer buckets.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NETWORK="edcom-fresh-check-$$"
DB_IMAGE="${DB_IMAGE:-edcom/database}"
API_IMAGE="${API_IMAGE:-edcom/api}"
DB_ID=""
cleanup() {
  if [[ -n "$DB_ID" ]]; then docker rm -fv "$DB_ID" >/dev/null; fi
  docker network rm "$NETWORK" >/dev/null
}
docker network create --internal "$NETWORK" >/dev/null
trap cleanup EXIT
DB_ID=$(docker run -d --network "$NETWORK" --network-alias database \
  -v "$ROOT/schema:/docker-entrypoint-initdb.d:ro" \
  --entrypoint docker-entrypoint.sh "$DB_IMAGE" postgres)
for attempt in $(seq 1 60); do
  # TCP readiness excludes PostgreSQL's temporary socket-only init server.
  if docker exec "$DB_ID" pg_isready -h 127.0.0.1 -U edcom >/dev/null 2>&1; then break; fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$DB_ID")" != true ]]; then
    docker logs "$DB_ID"; exit 1
  fi
  sleep 1
done
docker exec "$DB_ID" pg_isready -h 127.0.0.1 -U edcom
docker run --rm --network "$NETWORK" \
  -e postgres_conn=postgres://edcom:edcom@database:5432/edcom \
  -v "$ROOT/api:/api:ro" -v "$ROOT/scripts:/scripts:ro" \
  -v "$ROOT/data/setup:/setup:ro" --tmpfs /buckets --tmpfs /logs \
  --entrypoint sh "$API_IMAGE" -c '
    mkdir -p /buckets/data /buckets/images /buckets/blocks /buckets/transfer
    python /scripts/run_db_migrations.py && python /scripts/run_db_migrations.py
  '
docker exec -i "$DB_ID" psql -v ON_ERROR_STOP=1 -U edcom -d edcom <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM migrations WHERE name='add_automation_subject_tests') THEN
    RAISE EXCEPTION 'Subject-test migration missing';
  END IF;
  IF to_regclass('public.automations') IS NULL
     OR to_regclass('public.automation_subject_tests') IS NULL
     OR to_regclass('public.automation_subject_sends') IS NULL THEN
    RAISE EXCEPTION 'Automation tables missing';
  END IF;
  IF (SELECT count(*) FROM pg_constraint WHERE conname IN
      ('subject_tests_automation_fk','subject_tests_email_fk','subject_sends_test_fk')) <> 3 THEN
    RAISE EXCEPTION 'Subject-test foreign keys missing';
  END IF;
  IF EXISTS (SELECT name FROM migrations GROUP BY name HAVING count(*) > 1) THEN
    RAISE EXCEPTION 'Repeated migration records';
  END IF;
END $$;
SQL
printf '%s\n' 'Fresh base schema and repeatable automation migrations passed.'
