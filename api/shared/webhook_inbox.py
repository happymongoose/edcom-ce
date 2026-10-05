"""Recoverable Redis transport for legacy, non-transactional event handlers.

An interrupted handler is held, never blindly replayed: it may already have
committed database or external effects. Caller serialises consumers with a
PostgreSQL session advisory lock, not an expiring Redis lease.
"""
import base64
import hashlib
import json
import time

PENDING = "webhooks-pending"
PROCESSING = "webhooks-processing"
HELD = "webhooks-held"
STATE_PREFIX = "webhooks-state:"
RECEIPT_SECONDS = 7 * 86400
LOCK = (1162101583, 1464353355)


def identity(raw):
    try:
        value = json.loads(raw)
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    except (ValueError, UnicodeError):
        canonical = raw
    return hashlib.sha256(canonical).hexdigest()


def state_key(raw):
    return STATE_PREFIX + identity(raw)


def acknowledge(rdb, raw):
    # Receipt and removal are one Redis operation. A restart after handler return
    # but before this operation must hold the event, not repeat its effects.
    rdb.eval("""
        if redis.call('GET', KEYS[1]) ~= 'held' then
            redis.call('SET', KEYS[1], 'done', 'EX', ARGV[2])
        end
        redis.call('LREM', KEYS[2], 1, ARGV[1])
        return 1
    """, 2, state_key(raw), PROCESSING, raw, RECEIPT_SECONDS)


def hold(rdb, raw, reason):
    record = json.dumps({"id": identity(raw), "held_at": int(time.time()),
                         "reason": reason, "payload_base64": base64.b64encode(raw).decode()})
    rdb.eval("""
        local state = redis.call('GET', KEYS[1])
        if state ~= 'held' and state ~= 'done' then
            redis.call('LPUSH', KEYS[3], ARGV[2])
            redis.call('SET', KEYS[1], 'held')
        end
        redis.call('LREM', KEYS[2], 1, ARGV[1])
        return 1
    """, 3, state_key(raw), PROCESSING, HELD, raw, record)


def recover(rdb):
    # Caller holds the consumer lock, so these belong to an interrupted worker.
    while True:
        raw = rdb.lindex(PROCESSING, -1)
        if raw is None:
            return
        if rdb.get(state_key(raw)) == b'done':
            rdb.lrem(PROCESSING, 1, raw)
        else:
            hold(rdb, raw, 'interrupted_outcome_unknown')


def consume(rdb, dispatch, checkcancel, logger):
    recover(rdb)
    while not checkcancel():
        raw = rdb.rpoplpush(PENDING, PROCESSING)
        if raw is None:
            return
        event_id = identity(raw)
        state = rdb.get(state_key(raw))
        if state in (b'done', b'held'):
            rdb.lrem(PROCESSING, 1, raw)
            continue
        # No automatic retries: partial effects are possible even on exception.
        try:
            obj = json.loads(raw)
            if not isinstance(obj, dict) or obj.get('type') not in ('mg', 'sp', 'ses'):
                raise ValueError('Unsupported event envelope')
        except (ValueError, UnicodeError):
            hold(rdb, raw, 'invalid_envelope')
            logger.error('Incoming event %s held: invalid envelope', event_id)
            continue
        try:
            dispatch(obj)
        except Exception as exc:
            hold(rdb, raw, 'handler_failed_outcome_unknown')
            logger.error('Incoming event %s held after %s; review required', event_id, type(exc).__name__)
            continue
        acknowledge(rdb, raw)
