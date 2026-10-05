# Transactional sending headroom

## Contract

`app.transactional_reserve_percent` in `config/edcom.json` reserves part of each configured account and route/domain sending cap for transactional admission. It is an integer from 0 to 100, default **0** (unchanged behaviour). For example, **20** protects 20% of each configured minute, hour, day and month account limit and each matching minute/hour/day domain throttle. Domain matching and exact-domain overrides retain their existing rules.

For a limit of 100, bulk can bring the shared count up to 80. Only transactional admission can use the remaining allowance up to 100. Transactional usage also counts against the bulk ceiling: if transactions already used 20, bulk can use 60, leaving another 20 available for transactions. This is deliberately conservative static headroom, not a separately replenished allowance. Quiet transactional periods leave capacity unused; bulk cannot borrow it. Fractional reserved counts round up, so a limit of 1 with any nonzero reservation permits no bulk sends. A value of 100 disables bulk admission under finite limits.

Both classes still share the original overall cap. Unconfigured/unlimited caps remain unlimited. Per-dispatch limits, paid credits, expired trials, review, pause and ban checks remain authoritative. **Credits are not reserved**, so an exhausted paid balance can still block transactions. This setting does not raise limits, reset counters, alter warmup, change suppressions or expedite mail already handed to Velocity.

## Concurrency and scope

The existing Redis WATCH/MULTI transaction checks and increments the same account and domain counters for both classes. The bulk ceiling is evaluated inside that transaction; concurrent campaign and transactional schedulers cannot consume reserved headroom through a check/write race. No separate allowance counter or second scheduler is introduced. Existing counter time windows and expirations are unchanged.

Only `check_txns` passes the transactional classification. `check_camps` and existing callers retain bulk/default behaviour. Generic task priority does not bypass this classification. The one-minute cron cadence is unchanged. Automation sends that do not use this scheduler are outside this admission mechanism, as before.

The database-to-Celery handoff and its existing failure semantics are unchanged; no unsafe automatic resend/replay was added.

## Deployment

Deploy this code to **all scheduler producers** before setting the reserve. Mixed old/new campaign schedulers can still consume the full allowance, so consistent deployment is required. Merge, do not replace, the existing `app` config. Example:

```json
{
  "transactional_task_queue": true,
  "transactional_reserve_percent": 20
}
```

The queue flag additionally requires the consumer-first activation procedure in [transactional queue operation](transactional-queue.md). The reservation itself requires no new consumer, schema or database migration. It is not enabled in existing environments by this code change. Twenty percent is an example, not a proven capacity recommendation; choose headroom against expected signup bursts and configured caps.

If the shared allowance was already consumed before activation, transactions must wait for the applicable existing window to renew. Do not clear counters to accelerate rollout. Already queued/in-flight bulk sends cannot be recalled. Invalid reserve values fail closed and appear in scheduler error logs; correct configuration rather than retrying sends. Set the reserve to 0 to restore legacy admission without resetting any counters or queue data.

## Remaining delivery boundary

With reserved admission and the dedicated transactional worker enabled, bulk cannot consume the protected EDCOM allowance or occupy every transactional worker slot. Transactional traffic can still exceed its available capacity, run out of paid credits or encounter provider throttling. The remote Velocity queue and connection capacity still need independently verified separation before claiming prompt end-to-end delivery during a large broadcast.

## Tests

Current-source Docker tests use real Redis counters and independent connections under concurrent calls, plus the real `check_txns` database selection/dequeue path with dispatch intercepted so no email is sent. They cover every bounded window, exact/wildcard domain matching, bulk saturation followed by transactional admission, concurrent requests, rounding, disabled/unlimited settings, account/domain isolation, minute rollover with retained hour caps, invalid configuration and existing safety/credit limits. No existing development data is reset.

### Recorded verification

- Focused reserve and routing suites: **17 passed**, including 11 new reserve tests.
- Full discovery: **839 ran; 758 passed, 81 failed** after the shared test client hit the existing 5,000 HTTP requests/minute limit (`api/app.py:USER_LIMIT`). These were HTTP 429 responses, not sending-allowance failures. This is a rate-window-sensitive suite limitation; the whole run is not reported as green.
- Every affected module was rerun in fresh isolated fixtures: **121 passed**, including all previously failing cases. No rate checks or assertions were disabled.
- Python syntax, shell syntax and `git diff --check` passed. Flake8 is unavailable in the API image; no lint pass is claimed.

Logs: `.build/transactional-reserve-focused.log`, `.build/transactional-reserve-full.log`, `.build/transactional-reserve-rate-limit-recheck.log`. All disposable containers and storage were cleaned up. No external mail, production configuration change or existing-data reset occurred.
