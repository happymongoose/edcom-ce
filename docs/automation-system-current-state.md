# Automation System Current State

This note summarizes the automation system as of the current implementation. It is intended as a development checkpoint before further automation features are added.

## Release Readiness Checkpoint

Current status: automation is suitable for controlled selected-customer testing, not broad rollout.

- Retention cleanup test isolation has been fixed so retention tests no longer depend on global old debug or trigger rows created by other automation suites.
- The broad focused backend automation suite now passes.
- The fresh-install migration registration blocker was fixed in `fe3271d`.
  All automation migrations are now registered in `scripts/run_db_migrations.py`;
  see `docs/automation-controlled-pilot-runbook.md` for the fresh-install
  deployment sequence and verification notes.
- Segment trigger scanning remains selected-test/dev-only until real account performance has been observed.
- Trigger emission and processing remain a deliberate flag-gated rollout.
- The visual workflow preview is read-only and path-based; nested branches are not expanded yet.
- Admin stale-claim recovery exists for automation enrolment claims, trigger event claims, and segment scanner claims. Recovery is dry-run by default and apply mode requires explicit confirmation.

Highest remaining risks before broader production use:

- Segment scanner performance on large or complex customer accounts.
- Route and sender-domain readiness for real automation sends.
- Trigger storms if broader mutation hooks are added without additional throttles and guardrails.
- Lack of per-account and per-automation throttles.
- Full graph editing is not implemented; the editable workflow remains list/card based with a read-only visual preview.

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
- Automation email copy sources for creating automation emails from existing same-account email content.
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
- `if_missing_tag`
- `if_conditions`
- `go_to`
- `send_email`
- `add_to_list`
- `remove_from_list`
- `if_opened_email`
- `if_clicked_email`

`if_clicked_email` supports any-click, exact URL, and conservative URL-prefix
matching for clicks captured from the selected automation email. Engagement
checks are scoped to the current account, automation, enrolment/pass, contact,
selected automation email, and event type. A click from an earlier pass through
the same automation does not count for a later enrolment.

Click match modes:

- `any`: any captured click in the selected automation email.
- `url_exact`: normalized URL equality. Legacy `click_match: "url"` remains
  compatible with this exact-match behavior.
- `url_prefix`: conservative prefix matching for query/hash variants without
  matching sibling paths such as `/somepage-other`.

`if_conditions` supports flat ALL/ANY groups for tag, list membership, opened
email, and clicked email conditions. Nested condition groups are intentionally
deferred.

Flat `if_conditions` item types currently supported:

- `has_tag`
- `missing_tag`
- `opened_email`
- `clicked_email`
- `in_list`
- `not_in_list`

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

### Send Suppression

Automation `send_email` execution checks suppression before calling `send_backend_mail`.
The MVP suppression sources are:

- Contact props: `Unsubscribed`, `Bounced`, and `Complained`.
- `unsublogs`: `unsubscribed`, `complained`, and `bounced`.
- `exclusions`: account-scoped email and domain exclusions.

If the enrolled contact is suppressed, no email is sent and no `debug_email_logs`
row is created. The `send_email` node is recorded as a successful skipped step
with `suppressed: true` and a bounded `suppression_reason`, then the enrolment
advances normally or completes if the send node is final. Retry/backoff is not
applied because suppression is expected contact state, not a provider/runtime
failure.

## Automation Email Creation And Copying

Automation emails can be created blank from a selected editor type or copied
from existing same-account sources. Supported copy sources are:

- Automation emails.
- Broadcasts/campaigns.
- Funnel messages from same-account funnels.
- Transactional templates.

Copying preserves only email authoring fields:

- Editor `type`.
- `subject`.
- `preheader`.
- `rawText`.
- `parts`.
- `bodyStyle`.
- Sender fields: `fromname`, `fromemail`, `replyto`, and `returnpath`.

Copying does not preserve stats, logs, source IDs, send state, targeting, route
configuration, transactional API identity, funnel progression/timing, or
arbitrary source metadata. Listing/search responses for copy sources are
metadata-only and do not expose body/design/raw JSON fields. Ownership checks
are current-account scoped; funnel message sources require both the message and
the referenced funnel to belong to the current account, and the message must be
present in `funnels.data.messages[]`.

Automation email links can be discovered through a read-only, side-effect-free
endpoint for configuring URL-specific click conditions. The extractor returns
metadata only, does not insert rows into tracking/link tables, and does not
return raw body/design JSON. Manual URL entry remains available when discovery
misses a link or when a URL should be matched by prefix.

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

## Workflow Editor And Visual Preview

The workflow editor remains the list/card editing surface and the source of
draft workflow changes. The visual workflow preview is read-only and does not
mutate workflow JSON.

Current preview behavior:

- Shows draft workflow nodes as step cards with type labels, compact summaries,
  and contact counts.
- Uses a path-based layout for the first branch so Yes and No paths render in
  separate lanes instead of falling back to raw array order.
- Shows `go_to` nodes as explicit jumps to their target step and does not imply
  normal next-step continuation.
- Shows `exit` and final nodes as terminal.
- Shows missing/invalid targets as warning states.
- Stops at nested branch nodes with a clear "Nested branch not expanded in this
  preview" message. Full nested branch layout is deferred.
- Protects against loops/repeated targets with visited/max-depth bounds.
- Shows a narrow-screen fallback message for visual preview instead of trying
  to render a misleading phone-sized flowchart. Edit list mode remains
  available on narrow screens.

## Queue Purging And Recovery

Existing broadcast, funnel, and transactional admin queue purge actions delete rows from their queue tables (`campqueue`, `funnelqueue`, and `txnqueue`). Automation does not have a single equivalent queue table: work is represented across enrolments, trigger events, scanner snapshots, claims, retry/backoff metadata, and history tables.

Do not add a broad "Purge automation queue" action. Admin recovery actions
should be narrow and state-preserving.

Currently implemented admin recovery controls live in the admin customer
Automation Operations section:

- Clear stale automation enrolment claims.
- Clear stale trigger event claims.
- Clear stale segment scanner claims.

These controls are admin-only and customer-scoped. They default to dry-run,
return bounded preview/apply results, and require `dry_run: false` plus an exact
confirmation token to apply. They never delete rows and do not remove step-run
history, engagement events, debug logs, trigger events, segment snapshots, or
segment members.

Future recovery actions may include:

- Pause all automations for a customer.
- Cancel selected active enrolments.
- Cancel pending trigger events.
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

- Richer discovered-link selection for specific-link click conditions, such as
  link metadata/discovery improvements beyond the current simple read-only
  extractor.
- Compound condition nodes currently support flat ALL/ANY groups. A future slice
  should add nested grouped logic, such as `(has tag A AND does not have tag B)
  OR (clicked URL prefix X AND opened email Y)`. Existing simple condition
  nodes should remain supported for easy workflows. Compound conditions should
  continue reusing existing condition evaluators where possible. Segment-based
  conditions need extra care because segment evaluation can be expensive.
  Publish validation and execution should continue treating the compound node as
  one branch node with yes/no targets.
- A future visual workflow editor should provide a flowchart-style automation
  view similar in spirit to Mautic/ActiveCampaign, while keeping the current
  list/card editor as a fallback or compact mode. The first safe slice should be
  a read-only visual preview of the draft workflow, not full drag/drop editing.
  The preview should show nodes as boxes with type labels and summaries, linear
  connections, Yes/No-labelled branch connectors, go-to connectors, and
  missing/invalid targets as warning states. Later editing slices can add node
  side-panel editing, inserting nodes on connectors, drag/drop layout,
  reconnecting branch targets, and zoom/minimap support. The persisted data
  model should remain stable: node IDs and yes/no/go-to target IDs stay
  authoritative, and backend publish validation remains the source of truth for
  cycles and invalid references. Do not fold this into compound-condition work.
- General link-click actions should be designed separately from automation
  engagement conditions. Future click actions may apply across broadcasts,
  funnels, transactional emails, and automation emails, and may add/remove tags
  or eventually perform list/automation actions. That design must account for
  idempotency per contact/link/action, bot/replay protection, audit/history,
  account scoping, source metadata, rate limiting, and interaction with
  automation trigger emission when a clicked-link action mutates tags or lists.
- Automation A/B subject-line testing is important after live-server readiness
  and practical editor polish. The first version should be a simple subject-line
  test for automation emails: same email body, different subject/preheader
  variants, variant assigned per enrolment/contact deterministically or
  randomly, selected variant stored in step-run/send metadata, and sends,
  opens, and clicks reported by variant. The first slice should not include
  automatic winner selection. Later versions can add automatic winner
  selection, sending remaining contacts to the winner, body/content variants,
  and multi-arm tests. Suppression and preflight must still apply, variant
  choice must remain stable within an enrolment/pass, copied emails/templates
  must not accidentally copy old test stats, and reporting must stay
  account-scoped and bounded. Do not mix this into preflight/route visibility
  work.
- Broader list/import/API mutation hooks for list triggers.
- Production tuning for segment scanner cadence, caps, and expensive segment definitions.
- Admin throttle/kill-switch UI for automation processing.
- Public API automation enrolment.
- Contact automation status/progress table on contact edit.
- Email history expansion to broadcast and funnel sends after reliable timestamped metadata exists.
- Additional copy sources if a broader reusable template library is introduced.
- Segment scanner retention strategy for snapshot/member tables.
- Operational alerting for stale claims, repeated failures, and segment scanner errors.
