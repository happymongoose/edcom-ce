# Automation System Current State

This note summarizes the automation system as of the current implementation. It is intended as a development checkpoint before further automation features are added.

## Core Tables

- `automations`: automation draft configuration, published snapshots, entry triggers, status, and revisions.
- `automation_emails`: automation-owned email library and editor-compatible email data.
- `automation_enrolments`: contact enrolment/pass state, current node, status, source, retry/backoff data, and execution claim metadata.
- `automation_step_runs`: node execution/debug history.
- `automation_email_events`: automation-specific open/click engagement events.
- `automation_trigger_events`: pending/processed/suppressed trigger events.
- `automation_segment_trigger_snapshots`: segment scanner baseline/diff progress and claim state.
- `automation_segment_trigger_members`: durable segment membership snapshot.
- `debug_email_logs`: local debug email backend send records.

## Main API Areas

- Automation CRUD/publish/pause/resume.
- Automation email CRUD, duplicate, editor route support, and send-test.
- Manual enrolment for one contact, contact lists, and segments.
- Manual `run-next` execution for one enrolment.
- Manual account-scoped automation enrolment processor.
- Trigger event insertion/process/debug endpoints.
- Segment trigger baseline/diff scanner endpoint.
- Diagnostics/status endpoints.
- Retention cleanup callable.

## Node Types

Draft/publish and manual execution:

- `add_tag`
- `remove_tag`
- `wait_duration`
- `exit`
- `if_has_tag`
- `go_to`
- `send_email`
- `add_to_list`
- `remove_from_list`
- `if_opened_email`
- `if_clicked_email`

`if_clicked_email` currently means any click in the selected automation email. Specific-link click conditions are not implemented yet.

## Entry Trigger Types

Supported in automation entry configuration:

- `manual`
- `tag_added`
- `tag_removed`
- `list_joined`
- `list_left`
- `segment_entered`
- `segment_left`

Entry config supports the existing single-trigger shape and a multi-trigger shape:

```json
{ "type": "tag_added", "tag": "vip" }
```

```json
{
  "type": "multi",
  "triggers": [
    { "type": "tag_added", "tag": "vip" },
    { "type": "segment_entered", "segment_id": "segment-id" }
  ]
}
```

Manual enrolment remains a permanent supported explicit action regardless of entry trigger configuration.

## Execution Model

- Execution uses the published workflow snapshot only. Draft node data must not drive runtime behavior.
- `run-next` executes one node per request and does not execute the next/target node in the same request.
- Automatic/batch processing also processes at most one node per enrolment per run.
- Enrolments are atomically claimed with `running`, `running_status`, `claim_token`, `claimed_at`, `claimed_node_id`, and `claimed_published_revision` in `automation_enrolments.data`.
- Final enrolment updates require the matching claim token.
- Stale running claims older than the configured threshold can be recovered conservatively.
- Retry/backoff state is stored in `automation_enrolments.data`.
- Retryable runtime/provider failures back off at 5, 15, then 60 minutes. Exhaustion marks the enrolment `failed`.
- Non-retryable configuration/validation failures move the enrolment to `held` with bounded error metadata.
- `failed` is terminal for `reentry: multiple`, but still blocks `reentry: once`.

## Schedulers And Processors

- Automation enrolment processor:
  - `POST /api/automation-enrolments/process`
  - Celery task: `process_automation_enrolments_task`
  - Scheduler callable: `check_automation_enrolments`
  - Cron registered, but gated by flags/settings.

- Trigger processor:
  - `POST /api/automation-trigger-events/process`
  - Processes pending trigger events and applies suppression/re-entry rules.

- Segment trigger scanner:
  - Baseline/diff endpoint: `POST /api/automation-segment-trigger-baselines`
  - Celery task: `process_automation_segment_triggers_task`
  - Scheduler callable: `check_automation_segment_triggers`
  - Cron registered every 5 minutes, but disabled unless scanner flags and customer processing are enabled.
  - Baseline emits zero events. Diff emits pending `segment_entered` / `segment_left` events only after a completed baseline exists.

- Retention cleanup:
  - Callable: `check_automation_retention_cleanup`
  - Cron registered, disabled by default.
  - Currently cleans old `debug_email_logs` and finished `automation_trigger_events` only when enabled.

## Flags And Customer Settings

Global environment flags:

- `automation_processing_enabled`: enables scheduled automation enrolment processing.
- `automation_triggers_enabled`: enables trigger event processing.
- `automation_trigger_emission_enabled`: enables automatic trigger event emission from supported mutation paths.
- `automation_trigger_manual_events_enabled`: enables manual/debug trigger event insertion.
- `automation_segment_trigger_baseline_enabled`: enables segment baseline scanning.
- `automation_segment_trigger_diff_enabled`: enables segment diff scanning.
- `automation_retention_cleanup_enabled`: enables retention cleanup.

Customer settings in `companies.data`:

- `automation_processing_enabled`: required for scheduled/manual batch processing and segment scanner scheduler dispatch for that customer.
- `automation_diagnostics_visible`: allows normal customer users to view automation diagnostics.

Admin/support impersonation can view automation diagnostics regardless of `automation_diagnostics_visible`, but data remains scoped to the impersonated customer.

## Debug And Diagnostic Pages

- `/automation-processing-status`: enrolment status counts, stale running claims, recent failures, and flag booleans.
- `/automation-trigger-events`: recent trigger events with bounded result/error projection.
- `/automation-segment-trigger-status`: referenced segment triggers, snapshot progress, claims, member counts, recent event counts, and scanner flags.
- `/debug-email-logs`: recent debug email backend logs.
- Automation detail debug history: enrolment/step-run/engagement history and copy-friendly plain-text logs when diagnostics are visible.

Diagnostic endpoints are backend-gated by automation diagnostics visibility. Frontend menu hiding is convenience only.

## Queue Purging And Recovery

Existing broadcast, funnel, and transactional admin queue purge actions delete rows from their queue tables (`campqueue`, `funnelqueue`, and `txnqueue`). Automation does not have a single equivalent queue table: work is represented across enrolments, trigger events, scanner snapshots, claims, retry/backoff metadata, and history tables.

Do not add a broad "Purge automation queue" action. Future admin recovery actions should be narrow and state-preserving, such as:

- Pause all automations for a customer.
- Clear stale automation execution claims.
- Cancel selected active enrolments.
- Cancel pending trigger events.
- Clear stale trigger/scanner claims.
- Rebuild a selected segment trigger baseline.

Recovery actions should preserve audit/history where possible. `automation_step_runs`, `automation_email_events`, `debug_email_logs`, and terminal `automation_enrolments` should not be purged except through deliberate retention policies. Any future recovery action must be admin-only, customer-scoped, explicit, and should preferably preview/report what it will change before applying.

## Safety Rules

- All automation data access and processing is account-scoped.
- Manual, list, and segment enrolment paths share published checks, paused behavior, re-entry rules, and active-pass blocking.
- `reentry: once`: any prior enrolment blocks future enrolment.
- `reentry: multiple`: terminal prior enrolments allow re-entry, but an active/non-terminal pass blocks a new pass.
- Trigger processing suppresses same-automation source events by default.
- Trigger processing suppresses active-pass events and does not queue reruns after completion.
- Trigger processing applies cooldown and depth guards.
- Automatic trigger emission only happens on real mutations, not no-ops.
- Segment diff requires completed baseline first.
- Segment diff processes buckets atomically and does not partially update membership if the event cap would be exceeded.
- Segment snapshot membership is the primary duplicate-event guard.
- Raw diagnostic payloads are bounded/projected; raw JSONB payloads are not exposed wholesale.

## Known Gaps And Future Work

- Specific-link click conditions for `if_clicked_email`.
- Broader list/import/API mutation hooks for list triggers.
- Production tuning for segment scanner cadence, caps, and expensive segment definitions.
- Admin throttle/kill-switch UI for automation processing.
- Public API automation enrolment.
- Contact automation status/progress table on contact edit.
- Email history expansion to broadcast and funnel sends after reliable timestamped metadata exists.
- Creating automation emails from existing emails/templates.
- Segment scanner retention strategy for snapshot/member tables.
- Operational alerting for stale claims, repeated failures, and segment scanner errors.
