#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${SCREENSHOT_IMAGE:-edcom/screenshot:hardened-amd64}"
ID=$(docker run -d --network none \
  -v "$ROOT/screenshot/browser-ready.test.js:/src/screenshot/browser-ready.test.js:ro" \
  -v "$ROOT/screenshot/smoke-test.js:/src/screenshot/smoke-test.js:ro" "$IMAGE")
trap 'docker rm -fv "$ID" >/dev/null' EXIT
[[ $(docker exec "$ID" id -u) != 0 ]]
docker exec "$ID" node /src/screenshot/browser-ready.test.js
for attempt in $(seq 1 30); do
  if docker exec "$ID" node -e 'const s=require("net").connect(4000,"127.0.0.1",()=>s.end());s.on("error",()=>process.exit(1))' >/dev/null 2>&1; then break; fi
  if [[ $(docker inspect -f '{{.State.Running}}' "$ID") != true ]]; then
    docker logs --tail 50 "$ID"
    exit 1
  fi
  sleep 1
done
if ! docker exec "$ID" node /src/screenshot/smoke-test.js; then
  docker logs --tail 50 "$ID"
  exit 1
fi
docker exec "$ID" chromium-browser --version
