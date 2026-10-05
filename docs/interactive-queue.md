# Reserved capacity for interactive contact queries

## Contract

Opt-in `app.interactive_task_queue: true` in `config/edcom.json` routes exactly `api.lists.list_find_start` and `api.lists.list_find` to `interactive`. Default false preserves the existing queue. All other tasks, including exports, broadcasts, automations, unknown future tasks, retain their current default routing/priorities. Transactional delivery now has its own independent opt-in lane; see [transactional capacity](transactional-queue.md). Explicit queue overrides remain supported.

The allowlist covers both the query fan-out parent and its child SQL/evaluation tasks. A high-priority decorator alone is not a routing rule. Work run with SYNC_TASKS remains synchronous; queue separation does not isolate direct API/database work, cron, incoming feedback or the optional synchronous segment-refresh service. Query computation and database contention still affect response times.

`docker-compose.queues.yml` is an optional production overlay. The bulk worker consumes only `celery`; the reserved worker consumes only `interactive`. Each starts with one process. The overlay also defines a separately opt-in transactional worker, adding a third process if all services are started. Set `EDCOM_BULK_CONCURRENCY` and `EDCOM_INTERACTIVE_CONCURRENCY` through Compose interpolation if measurements justify different limits; both use the existing validated 1–64 concurrency helper. Do not multiply capacity without considering PostgreSQL and the complete 8 GB host memory budget.

The overlay inherits the new worker's base settings from `docker-compose.yml` in the installation directory. Future AMD64/ARM64 installer builds include it. Validate the merged configuration, especially if your base install has custom mounts/environment or uses a different filename. The previously generated release archive is NOT rebuilt by this slice and does not contain these changes.

## Safe activation

1. Deploy rebuilt current images and the overlay, with routing still disabled. No schema change is required. Use a maintenance window and preserve existing queue/storage data.
2. Start the reserved consumer FIRST (the current default worker can remain running):

```sh
docker compose -f docker-compose.yml -f docker-compose.queues.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.queues.yml up -d --no-deps tasks-interactive
```

3. Verify worker ping and subscription from the application container:

```sh
docker compose exec api celery -A api.app.tasks inspect ping
docker compose exec api celery -A api.app.tasks inspect active_queues
```

The reserved worker must report `interactive`. Confirm no unexpected consumer subscribes to both lanes. Ping alone is not sufficient.
4. Merge `"interactive_task_queue": true` into the existing `app` configuration. Restart long-lived producers using the established maintenance procedure so they import the changed configuration. In particular, API producers and workers dispatching child tasks must use the same setting. Cron processes load configuration at invocation. Do not replace the entire configuration file.
5. After current bulk actions finish safely, apply the overlay to the bulk worker too. Do not force-kill in-flight sending to change concurrency. Keep using both `-f` files for subsequent deployment commands; use your site's existing Compose environment file.
6. Verify a contact query, existing queued work, task failures, backlog age, memory and database pressure. Reserved capacity does not provide admission control, per-account fairness, a guaranteed query deadline or infinite sending throughput.

During rolling activation old producers may still place queries on `celery`; that remains consumed. The parent/child combination remains executable in either lane. No old messages are renamed, purged or migrated.

## Safe rollback

Disable the app flag and reload producers first. Keep the interactive consumer running until its pending, active, reserved and scheduled work is finished and all old producers have stopped routing there. Use Celery inspect `active`, `reserved`, `scheduled` and `active_queues` plus broker queue measurements. An empty Redis list alone does not prove no active or delayed work remains.

Only then remove the reserved worker/overlay deliberately. Reverting producer configuration does not move already queued work. Never purge either queue or put uncertain sending tasks back into circulation to simplify rollback.

## Benchmark and tests

`dev/run_queue_baseline.sh` accepts `interactive_task_queue=true` in its Docker-driver environment. Shared mode has one two-process worker; split mode has two one-process workers. Both run the same real audience builder, real send tasks and local fake Velocity sink with two-second request delay per batch. No real delivery occurs. The fake-delivery sink, helper and isolated DB/network boundaries are unchanged.

Both modes test an explicitly default-queued contact-query parent (with its child following configured routing), ordinary queries, occupied bulk worker slots, graceful bulk-worker restart, final drainage, unique recipient counts, held-event retention and pending-template preservation. Samples now include both queues. The real broker test does not change routes midway through a running broadcast or claim a full deployment rehearsal.

`test/test_interactive_queue.py` checks opt-in/default behaviour, the exact allowlist, unknown and bulk task fallback and explicit legacy queue overrides using Celery's router. The production Compose overlay is validated separately. Shared/split benchmark results follow below; isolated timing observations are not production service-level guarantees.

## Recorded equal-capacity comparison

Two total Celery child processes in each mode, 70,000 recipients, same local fake delivery workload:

| Measurement | Shared: 2 bulk/interactive slots | Split: 1 bulk + 1 interactive |
| --- | --- | --- |
| Idle query (s) | 2.997 | 2.591 |
| Busy query (s) | 4.957 | 3.721 |
| Post-drain query (s) | 3.435 | 3.607 |
| Dispatch/fetch including restart (s) | 102.267 | 235.708 |
| Unique fake recipients | 70000 | 70000 |
| Final queue depth | 0 | 0 |

Both runs counted each recipient once, consumed the explicitly legacy-queued query, survived graceful bulk-worker restart and preserved the earlier event/file safety guards. The 2,000-recipient split rehearsal also passed. These are individual latency samples, not p95 or proof of a universal percentage improvement. Shared host variation and database work affect timings. Reserving a process reduced bulk throughput materially; 1+1 is a conservative starting configuration, not the demonstrated optimal sizing for the live server. Increasing to more bulk processes requires measuring total memory, CPU and database pressure.

The first Compose validation found that cross-file extends needed an explicit base filename; the overlay was corrected and validation passed. Python, shell and whitespace checks passed. Production images/release archives were not rebuilt or activated. No real emails were sent or existing data changed.

Full current-source backend discovery: **825 tests passed**, including the new routing checks. All benchmark/test services and their disposable storage were removed after completion. Detailed local logs: `.build/queues-shared-70000.log`, `.build/queues-split-70000.log`, `.build/interactive-smoke.log`, `.build/queues-full-tests.log`.
