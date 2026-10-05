# Incoming provider event retention and conservative recovery

Scope: queued Mailgun, SparkPost and SES events consumed by `api.events.process_webhooks`. Direct tracking endpoints, Velocity feedback handlers, Celery sending tasks and outgoing webhook retries are unchanged.

## Behaviour

- Producers keep the existing `webhooks-pending` format and admission path.
- The consumer atomically moves one raw message to `webhooks-processing` before reading/dispatching it. Cancellation before claim leaves it pending; graceful cancellation finishes the current handler first.
- A PostgreSQL session advisory lock permits one consumer. It survives handler commits and releases when the connection dies. No expiring lease permits a second consumer to steal an active handler.
- Successful processing atomically stores a Redis receipt and removes the processing copy. Receipts last seven days. Identity is SHA-256 of the complete JSON envelope with object keys sorted, preserving array order and field values. This suppresses exact normalised-envelope duplicates, including account context; it is NOT a universal provider-event ID or permanent deduplication guarantee.
- A failed handler or interrupted processing copy is retained in `webhooks-held`. The record includes an ID, timestamp, reason and base64 original payload (encoding, not encryption). The hold marker has no automatic expiry. Repeated identical held input does not execute or create repeated held copies.
- Malformed/unknown envelopes are held rather than blocking later events. Raw payloads and exception messages are not logged by the new transport wrapper; existing handler logging remains unchanged.
- Restart after a successful receipt discards a redundant processing copy. Restart after effects but before receipt holds the event as outcome unknown. This avoids silently replaying side effects.

## Why failure does not automatically retry

Existing handlers perform autocommitted database increments, consume tracking lists in Redis, and may call external customer webhooks synchronously. There is no encompassing atomic transaction. SparkPost's provider marker also precedes later work. Repeating a failed handler can duplicate effects or skip partially completed work.

This slice therefore guarantees retention of the incoming queued envelope, not automatic completion or rollback of all effects. It does not restore subsidiary tracking messages already consumed inside legacy handlers. True automatic retry requires separate transaction/outbox and subsidiary-event ownership work. Do not manually push held messages back into pending without investigating partial effects and deduplication markers.

## Operator visibility

Run in the relevant application container:

```sh
docker compose exec webhooks python /scripts/webhook_queue_status.py
```

The read-only command returns pending/processing/held counts and the ten most recent held IDs, timestamps and reason codes. It never displays payloads or replays/deletes records. Any held count requires investigation. No frontend dashboard or automatic alert delivery is introduced here.

Held payloads remain sensitive customer data in the existing Redis store. They are not automatically deleted; monitor their growth, protect access and backups. Successful receipts consume space proportional to seven days of processed unique envelopes. After expiry, an identical newly submitted envelope can execute again; existing provider-specific deduplication still applies where implemented.

Redis persistence remains the deployment's existing AOF configuration. This does not guarantee survival of Redis disk failure, data reset or an unflushed AOF window. Do not clear queues or use an eviction policy that silently discards receipts/work.

## Deployment and rollback

Deploy current API/script files together. Stop the old webhook processor gracefully before starting the new processor: old code does not take the new coordination lock. Pending messages remain compatible and no database schema migration is required. Only the webhook consumer needs restarting for this change; do not restart active sending workers incidentally.

Rollback must account for nonempty processing/held lists. Old code ignores them. Preserve those lists and investigate them; never flatten uncertain work into pending as an automatic rollback step. Deploying this slice does not permit unrestricted live sending: file-reference safety and queue isolation remain open.

## Verification

`dev/run_webhook_inbox_tests.sh` creates isolated current-source PostgreSQL/Redis services and runs the focused tests. `INBOX_FULL_SUITE=1` additionally selects full backend discovery instead. Run via the Docker CLI driver used by `dev/run_queue_baseline.sh`.

Coverage includes success/receipt expiry, duplicate JSON with reordered object keys, distinct account envelopes, malformed inputs, partial committed effects, failure before acknowledgement, interrupted claims, completed-copy recovery, cancellation, independent-connection consumer exclusion, and real subprocess death releasing the lock. All test data is disposable; no real email or customer webhook is sent.

The platform baseline now requires a failed event to appear in held storage. Its historical event-loss result in `queue-baseline-results.md` describes the pre-fix baseline; the age-based cleanup reproduction remains intentionally unresolved.

Recorded acceptance: final focused suite **51 tests passed** (13 inbox tests plus 38 related event/A/B tests). Full backend discovery **810 passed** before the final late-completion hold guard; that guard and related paths were then covered by the final focused run. A 2,000-contact real-worker/fake-delivery regression passed, counted every recipient once across graceful restart, and retained the injected failed event in held storage. Python/shell syntax and whitespace checks passed. Initial new-test import setup failed and was corrected before these runs. No real mail, provider calls or user-data resets.
