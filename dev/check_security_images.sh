#!/usr/bin/env bash
# Run via the Docker CLI driver, with the checkout mounted at its host path.
# Only disposable fixtures; internal network, no host ports, no application data.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_IMAGE="${API_IMAGE:-edcom/api:hardened-amd64}"
DB_IMAGE="${DB_IMAGE:-edcom/database:hardened-amd64}"
PROXY_IMAGE="${PROXY_IMAGE:-edcom/proxy:security-amd64}"
SMTP_IMAGE="${SMTP_IMAGE:-edcom/smtprelay:hardened-amd64}"
FIXTURE="edcom-security-$$-$RANDOM"
IDS=()
cleanup() {
  for id in "${IDS[@]}"; do docker rm -fv "$id" >/dev/null; done
  docker volume rm "$FIXTURE" >/dev/null
  docker network rm "$FIXTURE" >/dev/null
}
docker network create --internal "$FIXTURE" >/dev/null
docker volume create "$FIXTURE" >/dev/null
trap cleanup EXIT
# Copy only public nginx configuration. Never mount the real config directory.
docker run --rm -v "$FIXTURE:/config" -v "$ROOT/config/nginx.server.conf:/source/nginx.server.conf:ro" \
  -v "$ROOT/config/nginx.ssl.server.conf:/source/nginx.ssl.server.conf:ro"   --entrypoint sh "$API_IMAGE" -c 'cp /source/nginx.server.conf /source/nginx.ssl.server.conf /config/'
FAKE=$(docker run -d --network "$FIXTURE" --network-alias api   -v "$FIXTURE:/config" -v "$ROOT/dev/check_security_images.py:/check.py:ro"   --entrypoint python "$API_IMAGE" /check.py serve)
IDS+=("$FAKE")
DB=$(docker run -d --network "$FIXTURE" --network-alias database   --tmpfs /logs/postgres:uid=70,gid=70 "$DB_IMAGE")
IDS+=("$DB")
for attempt in $(seq 1 60); do
  if docker exec "$FAKE" python -c 'import urllib.request; urllib.request.urlopen("http://localhost:8000/")'      >/dev/null 2>&1 && docker exec "$DB" pg_isready -h 127.0.0.1 -U edcom >/dev/null 2>&1; then break; fi
  sleep 1
done
PROXY=$(docker run -d --network "$FIXTURE" --network-alias proxy -v "$FIXTURE:/config:ro" "$PROXY_IMAGE")
IDS+=("$PROXY")
SMTP=$(docker run -d --network "$FIXTURE" --network-alias relay "$SMTP_IMAGE")
IDS+=("$SMTP")
docker exec "$PROXY" nginx -t -c /etc/nginx/nginx.conf
docker exec "$PROXY" nginx -t -c /etc/nginx/nginx.ssl.conf
for attempt in $(seq 1 30); do
  if docker exec "$FAKE" python -c 'import socket; socket.create_connection(("relay",2525),2).close(); socket.create_connection(("proxy",443),2).close()' >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! docker run --rm --network "$FIXTURE" -v "$FIXTURE:/config:ro"   -v "$ROOT/dev/check_security_images.py:/check.py:ro"   --entrypoint python "$API_IMAGE" /check.py -v; then
  for id in "${IDS[@]}"; do docker logs --tail 30 "$id"; done
  exit 1
fi
