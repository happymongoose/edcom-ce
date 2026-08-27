# Controlled Automation Pilot Runbook

This runbook is for enabling automations for one selected customer account in a controlled pilot. Automations are suitable for selected-customer testing, not broad rollout.

## Fresh-Install Deployment Notes

This fork is expected to be installed on a fresh server using the normal
EmailDelivery archive flow: unpack `edcom-install-*.tgz`, run `./ez_setup.sh`
as root from the extracted `edcom-install` directory, then access the platform
through the configured DNS hostname. The install still depends on the standard
prerequisites: DNS A record/subdomain pointed at the server, Docker Compose
available, required ports open, and HTTPS configured after first access using
the existing project flow.

The migration registration blocker identified during deployment planning was
fixed in `fe3271d`. All automation migrations are now registered in
`scripts/run_db_migrations.py`, so a fresh database should create the automation
tables through the normal startup path.

Expected fresh-install automation migration order:

1. `add_automations_table`
2. `add_automation_enrolments_table`
3. `add_automation_step_runs_table`
4. `add_automation_emails_table`
5. `add_debug_email_tables`
6. `add_automation_email_events_table`
7. `add_automation_trigger_events_table`
8. `add_automation_segment_trigger_baselines_table`

Fresh install/startup paths call `/scripts/run_db_migrations.py` for the API,
tasks, cron, and webhooks containers. The optional segments service also uses
the same runner if enabled. The archive build path packages the corrected API
image and migration runner; no separate archive script change was found
necessary.

Non-destructive verification after `fe3271d` completed:

- Migration order was checked.
- `/scripts/run_db_migrations.py` was rerun idempotently.
- Expected automation tables existed.
- Expected automation migration rows were present.
- Focused automation execution, trigger, and segment scanner tests passed.
- A destructive clean database rebuild was not run.

Safe defaults remain suitable for first boot: global automation flags are off
unless explicitly set, and customer settings
`companies.data.automation_processing_enabled` and
`companies.data.automation_diagnostics_visible` default to false/missing.

## 1. Preconditions

- A specific customer account has been chosen for the pilot.
- An admin user can access the customer and impersonate or view the customer data context.
- Automation diagnostics are visible for the customer, either through admin/support impersonation or `companies.data.automation_diagnostics_visible = true`.
- Customer automation processing is explicitly enabled with `companies.data.automation_processing_enabled = true` before using background processing.
- Required global flags are known and intentionally set for the pilot:
  - `automation_processing_enabled` for scheduled enrolment processing.
  - `automation_triggers_enabled` for trigger event processing.
  - `automation_trigger_emission_enabled` only when testing automatic tag/list trigger emission.
  - `automation_segment_trigger_baseline_enabled` and `automation_segment_trigger_diff_enabled` only when testing segment trigger scanning.
- The sending route and sender domain are ready for real sends, or the pilot is deliberately using a debug/Drop All route.
- Suppression expectations are understood: unsubscribed, bounced, complained, or excluded contacts are skipped at `send_email`, no email is sent, and the enrolment advances without retry/backoff.

## 2. What To Enable First

1. Enable diagnostics visibility for the selected customer.
2. Enable the customer processing setting.
3. Enable the global `automation_processing_enabled` flag only when ready for background progression.
4. Leave trigger emission, trigger processing, and segment diff scanning off initially unless the pilot is explicitly testing triggers.
5. Leave segment scanning in selected-test/dev mode until real account performance has been observed.

## 3. Preflight Checklist

- The automation is published.
- The automation email preflight panel has been reviewed for draft or published mode as appropriate.
- Sender fields are present: `fromname` and `returnpath`, plus expected sender email/reply-to fields.
- Sender domain and route readiness are verified using existing account sending configuration.
- The route is expected. A debug or Drop All route should only be present when deliberately testing without real delivery.
- Suppression behavior is understood and accepted for the pilot.
- The enrolment source is clear:
  - manual contact enrolment,
  - list/segment bulk enrolment,
  - tag/list trigger event,
  - or segment scanner-generated trigger event.
- Trigger flags are off unless trigger behavior is part of the test.

## 4. Manual Smoke Sequence

1. Enrol one internal or test contact.
2. Run one node using manual `run-next`, or call the manual processor once with a low `limit`.
3. Inspect `/automation-processing-status` for ready, waiting, running, failed, stale, and completed counts.
4. Inspect the contact edit Automation Status table for the contact's current enrolment status and progress.
5. Inspect the automation Debug history for the send/action/condition step-run and any engagement events.
6. Verify no unexpected trigger events, duplicate sends, retries, or stale claims were created.
7. Continue one node at a time until the expected branch/action/completion is observed.

## First Live Deployment Sequence

1. Build/package the fork with the `fe3271d` migration registration fix included
   in the API image.
2. Install on a fresh server using the standard archive flow:
   `edcom-install-*.tgz`, `./ez_setup.sh`, root user, configured DNS hostname,
   and Docker Compose.
3. On first boot, confirm `/scripts/run_db_migrations.py` completed and the
   automation migration rows/tables exist.
4. Leave all automation runtime flags off and all customer automation settings
   false initially.
5. Confirm cron and Celery are running, but automation cron callables report
   disabled/no work while flags are off.
6. Create or select one internal/test customer and enable diagnostics visibility
   only for that account.
7. Configure a debug email route first if possible. Run automation preflight and
   confirm the route is clearly shown as debug/no-live-send.
8. Run the manual debug-route smoke sequence with one internal/test contact.
9. Only after the debug-route smoke passes, configure exactly one assigned
   published real provider route and verify sender/domain readiness through
   preflight.
10. Run one real-route smoke to one internal/test recipient only.
11. Enable customer processing and global scheduled processing only after manual
    smoke passes.
12. Keep trigger emission and segment scanner flags off until separately piloted.

## Completed Debug-Route Pilot Result

The Test Frontend Company pilot completed successfully using the debug email
route. This validated the controlled automation flow without live provider
delivery; it was not live provider validation.

- Preflight was ready with a `debug_route` warning and `suppression_behavior`
  info.
- The one-node processor sequence worked as expected:
  - `send_email`
  - `add_tag`
  - `exit`
- Diagnostics checked:
  - Automation Processing Status.
  - Contact Automation Status.
  - Automation Debug History.
  - Debug Email Logs and source metadata.
- Suppressed contact test passed:
  - unsubscribed contact skipped send,
  - no debug log was created for the suppressed send,
  - step-run was marked succeeded/suppressed,
  - no retry metadata was set,
  - enrolment advanced normally.
- Cleanup verified zero smoke-created automation, email, enrolment, step-run,
  debug log, and contact records remained.
- No product code changes were needed.

## 5. Background Processing Pilot

- Enable scheduled processing only after the manual smoke passes.
- Required settings:
  - global `automation_processing_enabled = true`,
  - customer `automation_processing_enabled = true`.
- Monitor:
  - ready/waiting/running/failed/stale counts,
  - recent failures,
  - stale running claims,
  - contact-level automation progress,
  - automation Debug history.
- Expected retry/backoff behavior:
  - retryable provider/runtime failures back off for 5, 15, then 60 minutes,
  - max retry exhaustion marks the enrolment `failed`,
  - non-retryable configuration failures become `held`,
  - suppressed sends are successful skipped steps and do not retry.
- Use admin stale-claim recovery only for stale claims. Do not use it for fresh active work.

## 6. Trigger Pilot Sequence

Treat trigger testing as separate from core processing.

### Tag/List Triggers

- Start with tag/list triggers before segment triggers.
- Required flags/settings:
  - customer `automation_processing_enabled = true`,
  - `automation_triggers_enabled = true`,
  - `automation_trigger_emission_enabled = true` only when testing automatic emission.
- Inspect:
  - `/automation-trigger-events`,
  - automation Debug history,
  - contact Automation Status,
  - `/automation-processing-status`.
- To turn off safely:
  - disable `automation_trigger_emission_enabled` to stop new automatic events,
  - disable `automation_triggers_enabled` to stop event processing,
  - disable customer processing if enrolment progression should also stop.

### Segment Triggers

- Segment triggers should remain selected-test/dev-only until real account performance is observed.
- Baseline must complete before diff mode can emit events.
- Required flags/settings:
  - customer `automation_processing_enabled = true`,
  - `automation_segment_trigger_baseline_enabled = true` for baseline,
  - `automation_segment_trigger_diff_enabled = true` for diff,
  - `automation_triggers_enabled = true` to process emitted segment events.
- Inspect `/automation-segment-trigger-status` before enabling diff. Confirm baseline status, member count, hashlimit, progress, and stale claim state.
- Keep account, segment, bucket, and event limits conservative.

## 7. Rollback And Emergency Steps

1. Disable customer `automation_processing_enabled`.
2. Disable global env flags as needed:
   - `automation_processing_enabled`,
   - `automation_trigger_emission_enabled`,
   - `automation_triggers_enabled`,
   - `automation_segment_trigger_baseline_enabled`,
   - `automation_segment_trigger_diff_enabled`.
3. Use stale-claim recovery only for confirmed stale enrolment, trigger event, or segment scanner claims.
4. Cancel selected active enrolments if needed; cancellation should preserve history.
5. Do not add or use a broad "Purge automation queue" action.
6. Do not delete step runs, engagement events, trigger events, debug logs, or terminal enrolments except through deliberate retention policies.

## 8. Known Limitations

- Segment scanner performance still needs observation on real accounts before broader use.
- The visual workflow preview is read-only.
- Nested branch preview is not expanded yet.
- Click conditions are scoped to automation emails and the current enrolment/pass.
- There is no per-account or per-automation throttle UI yet.
- Full graph editing is not implemented; the list/card editor remains the editing surface.
