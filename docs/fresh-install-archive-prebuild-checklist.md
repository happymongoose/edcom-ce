# Fresh-Install Archive Pre-Build Checklist

Use this checklist before cutting a fresh-install `edcom-install-*.tgz`
archive from this fork.

## Branch / Commit State

```bash
git branch --show-current
git log --oneline -5
```

Expected:

- Correct release branch.
- Includes `fe3271d Register automation migrations` or a later commit
  containing that migration registration fix.

## Worktree Cleanliness

```bash
git status --short
```

Expected:

- No product, docs, or code changes pending.
- No unexpected untracked files.
- Local runtime files are clean or intentionally ignored.

Note: `config/logrotate.status` is a local runtime file. Clean or ignore it
manually before release if it appears dirty.

## Pre-Build Tests

```bash
docker exec -e PYTHONPATH=/test:/ -w /test edcom-api pytest \
  test_automation_execution.py \
  test_automation_triggers.py \
  test_automation_segment_trigger_baselines.py \
  test_automation_emails.py \
  -q --tb=short
```

```bash
docker exec -w /client edcom-client npm test -- \
  --runInBand --watchAll=false src/containers/Automation.test.js
```

```bash
docker exec -w /client edcom-client npm run build
```

Expected:

- Backend automation suites pass.
- Frontend Automation tests pass.
- Frontend production build succeeds.

## Archive Build Commands

For Intel/AMD:

```bash
./dev/build_amd64.sh
```

For ARM/AArch64:

```bash
./dev/build_arm64.sh
```

## Post-Build Checks

Confirm the archive and API image bundle exist:

```bash
ls -lh .build/edcom-install*.tgz
ls -lh .build/edcom-install/images/edcom-api.tgz
```

Confirm the migration runner includes the automation migrations:

```bash
rg -n \
  "add_automation_step_runs_table|add_automation_trigger_events_table|add_automation_segment_trigger_baselines_table" \
  scripts/run_db_migrations.py
```

Confirm automation cron entries are present:

```bash
rg -n \
  "check_automation_enrolments|check_automation_segment_triggers|check_automation_retention_cleanup" \
  config/crontab
```

Confirm no automation env flags are enabled by default:

```bash
rg -n \
  "automation_processing_enabled|automation_triggers_enabled|automation_trigger_emission_enabled|automation_trigger_manual_events_enabled|automation_segment_trigger_baseline_enabled|automation_segment_trigger_diff_enabled|automation_retention_cleanup_enabled" \
  .env config/edcom.defaults.json docker-compose.prod.yml docker-compose.yml
```

Expected:

- No default-enabled automation flags in checked config.

Confirm the frontend build exists before the proxy image is built:

```bash
test -d client/build && ls -lh client/build/static/js | tail
```

## First Boot Checks

After installing the archive on a fresh server:

```bash
docker ps
docker logs edcom-api --tail=100
docker logs edcom-cron --tail=100
```

Expected:

- API healthy.
- Cron running.
- Migration runner completed without errors.

Verify automation tables:

```sql
select tablename
from pg_tables
where schemaname = 'public'
and tablename in (
  'automations',
  'automation_enrolments',
  'automation_step_runs',
  'automation_emails',
  'automation_email_events',
  'automation_trigger_events',
  'automation_segment_trigger_snapshots',
  'automation_segment_trigger_members',
  'debug_email_logs'
)
order by tablename;
```

Verify automation migration rows:

```sql
select name
from migrations
where name in (
  'add_automations_table',
  'add_automation_enrolments_table',
  'add_automation_step_runs_table',
  'add_automation_emails_table',
  'add_debug_email_tables',
  'add_automation_email_events_table',
  'add_automation_trigger_events_table',
  'add_automation_segment_trigger_baselines_table'
)
order by ran_at, name;
```

Expected:

- All expected automation/debug tables are present.
- All expected automation migration rows are present.

## First Smoke Checks

1. Enable diagnostics for one internal/test customer only.
2. Configure a Debug email route first.
3. Create a simple automation:
   - `send_email`
   - `add_tag`
   - `exit`
4. Run automation email preflight.
5. Manually enrol one internal/test contact.
6. Run one-node manual/processor smoke.
7. Check:
   - Automation Processing Status.
   - Contact Automation Status.
   - Automation Debug History.
   - Debug Email Logs.
8. Keep trigger emission, trigger processing, and segment scanner flags off
   unless that smoke is explicitly testing them.
9. Only after debug-route smoke passes, test one live-route internal recipient.

## Automation Flags / Settings Safety Notes

Global automation flags should stay absent or false for first boot:

- `automation_processing_enabled`
- `automation_triggers_enabled`
- `automation_trigger_emission_enabled`
- `automation_trigger_manual_events_enabled`
- `automation_segment_trigger_baseline_enabled`
- `automation_segment_trigger_diff_enabled`
- `automation_retention_cleanup_enabled`

Customer settings in `companies.data` default to false/missing:

- `automation_processing_enabled`
- `automation_diagnostics_visible`

Cron and Celery can run from first boot. Automation jobs should do no work while
global flags are off and customer processing settings are false.
