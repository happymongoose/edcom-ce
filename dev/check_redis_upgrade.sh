#!/usr/bin/env bash
# Only a disposable synthetic AOF/RDB; never mount an existing broker volume.
set -euo pipefail
NEW_IMAGE="${CACHE_IMAGE:-redis:7.2-alpine@sha256:29e8589c3f9ba699b5f7aa4b3c7733c58852a3626439e619aa0ee78de08c6ca0}"
FIXTURE="edcom-redis-upgrade-$$-$RANDOM"
OLD=""; NEW=""
cleanup() {
  for id in "$OLD" "$NEW"; do [[ -z "$id" ]] || docker rm -fv "$id" >/dev/null; done
  docker volume rm "$FIXTURE" >/dev/null
}
docker volume create "$FIXTURE" >/dev/null
trap cleanup EXIT
OLD=$(docker run -d --network none -v "$FIXTURE:/data" redis:7.0.8-alpine redis-server --appendonly yes)
ready() {
  for attempt in $(seq 1 60); do
    if docker exec "$1" redis-cli ping | grep -q PONG; then return; fi
    sleep 1
  done
  return 1
}
ready "$OLD"
docker exec "$OLD" redis-cli SET fixture:counter 123 EX 600 >/dev/null
docker exec "$OLD" redis-cli RPUSH fixture:celery '{"task":"one"}' '{"task":"two"}' >/dev/null
docker exec "$OLD" redis-cli HSET fixture:unacked token reserved >/dev/null
docker exec "$OLD" redis-cli ZADD fixture:unacked_index 42 token >/dev/null
docker exec "$OLD" redis-cli SAVE >/dev/null
docker stop "$OLD" >/dev/null
NEW=$(docker run -d --network none -v "$FIXTURE:/data" "$NEW_IMAGE" redis-server --appendonly yes)
ready "$NEW"
verify() {
  [[ $(docker exec "$NEW" redis-cli GET fixture:counter) == 123 ]]
  [[ $(docker exec "$NEW" redis-cli TTL fixture:counter) -gt 0 ]]
  [[ $(docker exec "$NEW" redis-cli HGET fixture:unacked token) == reserved ]]
  [[ $(docker exec "$NEW" redis-cli ZSCORE fixture:unacked_index token) == 42 ]]
  [[ $(docker exec "$NEW" redis-cli LRANGE fixture:celery 0 -1) == $'{"task":"one"}\n{"task":"two"}' ]]
}
verify
docker restart "$NEW" >/dev/null
ready "$NEW"
verify
[[ $(docker exec "$NEW" redis-cli LPOP fixture:celery) == '{"task":"one"}' ]]
[[ $(docker exec "$NEW" redis-cli LPOP fixture:celery) == '{"task":"two"}' ]]
[[ $(docker exec "$NEW" redis-cli LLEN fixture:celery) == 0 ]]
printf '%s\n' 'Redis 7.0 -> 7.2 AOF restore, restart, TTL, counters, pending/unacked data and FIFO checks passed.'
