# Reserved transactional sending capacity

## What this slice guarantees

An opt-in `app.transactional_task_queue: true` routes exactly `api.transactional.send_txn` to the `transactional` queue. A dedicated consumer allows an admitted transactional message to run while broadcast tasks occupy the bulk worker. It does not interrupt a send already running. It does not promote automation emails, campaigns, test emails or generic provider adapters. Provider calls made synchronously inside `send_txn` stay in that worker. The flag defaults off and is independent of `interactive_task_queue`.

This is **worker capacity isolation, not an immediate-delivery guarantee**. A signup application must use the existing transactional API for this lane. Calling a broadcast or automation API does not make its emails transactional automatically.

## Remaining delays outside this lane

1. The API writes to `txnqueue`. `check_txns` runs once per minute and applies existing account/domain/route send limits before dispatching `send_txn`. Broadcasts share those limits. This slice neither reserves quota nor bypasses warmup, suppression or throttling.
2. Real transactional emails sent through Velocity use `/send-lists`, just like bulk delivery. The locally available Velocity code has no per-message transactional-priority field. `/send-addr` is a test-send path with different behaviour and must not be used as a priority workaround.
3. Remote Velocity spool capacity, connection limits, recipient-server throttles, temporary failures and inbox placement remain outside Celery. Shared CPU, PostgreSQL and memory can also delay either lane.

For end-to-end separation, next agree and test transactional admission/reserved quota plus a dedicated delivery route with actual independent downstream capacity. Two EDCOM workers pointing to the same constrained MTA do not create that capacity. No remote Velocity configuration or sending limits were changed here.

Existing transactional body-file consumption and database-to-broker handoff are unchanged. No automatic replay was added: an uncertain external send must not be blindly retried.

## Activation and rollback

Use the existing optional `docker-compose.queues.yml` overlay. It now defines bulk, interactive and transactional consumers. Each defaults to one child process; the new process increases the default overlay total from two to three. Review the entire host memory budget before activation. `EDCOM_TRANSACTIONAL_CONCURRENCY` uses the existing validated concurrency helper (1–64); do not raise it without measurements.

1. Rebuild/deploy the current API image and overlay with producer routing still disabled. Existing release archives have not been rebuilt by this slice.
2. Start the consumer first:

```sh
docker compose -f docker-compose.yml -f docker-compose.queues.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.queues.yml up -d --no-deps tasks-transactional
docker compose exec api celery -A api.app.tasks inspect ping
docker compose exec api celery -A api.app.tasks inspect active_queues
```

3. Verify the new worker consumes only `transactional`. Then merge `"transactional_task_queue": true` into `app` in `config/edcom.json`. Reload long-lived producers through the established maintenance procedure; cron loads configuration on invocation. Do not replace the whole config file or force-kill in-flight sends.
4. Keep the existing `celery` consumer. Old queued messages and old producers still use it; no messages are renamed or migrated. Explicit queue overrides remain supported.
5. Monitor both `txnqueue` age and Celery pending/active/reserved/scheduled work, provider acceptance, downstream delivery events and failures. HTTP acceptance is not delivery.

To roll back, disable producer routing and reload producers first. Keep the transactional consumer until all pending, active, reserved and scheduled work has finished and all producers have stopped routing there. An empty Redis list is insufficient. Never purge queues or replay uncertain sends to simplify rollback.

## Verification

`test/test_transactional_queue.py` covers opt-in/default routing, independence from interactive routing, the exact task boundary and explicit default-queue overrides.

`dev/run_transactional_queue_check.sh` runs those tests and the existing interactive routing tests, then uses fresh isolated PostgreSQL/Redis services, real prefork Celery workers and current source. The internal-only Docker network has no external delivery access. A local HTTP sink handles the real bulk and transactional Velocity request formats, including inline recipient data. Every address is under `example.invalid`.

The workload queues eight 100-recipient bulk tasks, holds each bulk HTTP request for two seconds, and injects a login-style transactional task after bulk work begins. A separate fake FIFO delivery thread takes 40 ms per recipient. It intentionally offers no downstream priority, so a quick transactional handoff can still have a measurable simulated delivery wait. This is a controlled slow-service model, not a simulation of Velocity's exact scheduling algorithm or a real inbox test.

Run with `transactional_task_queue=false` for one shared worker and `true` for one bulk plus one reserved worker. This comparison adds one process; it is not an equal-resource benchmark. It starts after scheduler admission and does not test the once-minute cron wait, reserved sending quota, provider errors/retries or long-duration soak. Existing 70,000-contact tests cover bulk preparation/dispatch separately; this smaller test targets real transactional routing and the slow downstream boundary.

### Recorded results

| Measurement | Shared worker | Bulk + reserved transactional worker |
| --- | ---: | ---: |
| Transaction handoff to fake service | 26.364 s | 0.021 s |
| Transaction simulated delivery from task submission | 33.285 s | 4.122 s |
| Bulk recipients handed off before transaction | 800 | 100 |
| Unique fake recipients delivered | 801 | 801 |

Both runs passed, with each recipient handled once, no campaign/transactional error records and drained broker queues. These are single observations on a shared development host, not latency guarantees, p95 measurements or a claim about the remote Velocity server. The independent full test suite was also running during parts of these checks. The reserved configuration adds capacity; it is not an equal-process throughput comparison.

Six focused routing tests passed in each mode. Full current-source backend discovery passed **828 tests**. Compose validation, shell syntax, Python syntax and whitespace checks passed. The initial integration attempt failed because the disposable sending-policy fixture omitted `iplist`/`allips`; the fixture was corrected without changing production sending behaviour, then both modes passed. All fixture containers/storage were removed. No real emails were sent, no existing data was reset and no production routing was activated.

Local detailed logs: `.build/transactional-shared.log`, `.build/transactional-split-verified.log`, `.build/transactional-full-tests.log`. The failed fixture attempt is retained in `.build/transactional-split.log` for diagnosis.

The next admission slice is now available: [transactional sending headroom](transactional-admission.md). Its independent opt-in reserve prevents bulk from exhausting configured sending caps. The scheduler cadence and remote Velocity boundary described above still apply.
