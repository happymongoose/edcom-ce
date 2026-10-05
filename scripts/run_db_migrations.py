#!/usr/bin/env python

import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

INIT_LOCK = 605599291

from api.shared.db import DB
from api.shared import contacts
from api.migrations import fix_funnel_indexes, create_sp_event_table, add_monthly_limit, fix_templates_for_outlook, \
    remove_limit_incr, add_txnsends_msgid, webhooks_to_resthooks, add_resthooks_created, add_txnsettings_table, \
    add_list_stats, add_list_unsubscribe_post, add_signupsettings_table, add_beefree_templates, add_savedrows_table, \
    add_automations_table, add_automation_enrolments_table, add_automation_step_runs_table, \
    add_automation_emails_table, add_debug_email_tables, add_automation_email_events_table, \
    add_automation_trigger_events_table, add_automation_segment_trigger_baselines_table
from api.migrations import add_automation_subject_tests
from api.shared.log import get_logger

log = get_logger()

migration_list = [
    ('fix_funnel_indexes', fix_funnel_indexes),
    ('create_sp_event_table', create_sp_event_table),
    ('add_monthly_limit', add_monthly_limit),
    ('fix_templates_for_outlook', fix_templates_for_outlook),
    ('remove_limit_incr', remove_limit_incr),
    ('add_txnsends_msgid', add_txnsends_msgid),
    ('webhooks_to_resthooks', webhooks_to_resthooks),
    ('add_resthooks_created', add_resthooks_created),
    ('add_txnsettings_table', add_txnsettings_table),
    ('add_list_stats', add_list_stats),
    ('add_list_unsubscribe_post', add_list_unsubscribe_post),
    ('add_signupsettings_table', add_signupsettings_table),
    ('add_beefree_templates', add_beefree_templates),
    ('add_savedrows_table', add_savedrows_table),
    ('add_automations_table', add_automations_table),
    ('add_automation_enrolments_table', add_automation_enrolments_table),
    ('add_automation_step_runs_table', add_automation_step_runs_table),
    ('add_automation_emails_table', add_automation_emails_table),
    ('add_debug_email_tables', add_debug_email_tables),
    ('add_automation_email_events_table', add_automation_email_events_table),
    ('add_automation_trigger_events_table', add_automation_trigger_events_table),
    ('add_automation_segment_trigger_baselines_table', add_automation_segment_trigger_baselines_table),
    ('add_automation_subject_tests', add_automation_subject_tests),
]

def run():
    try:
        db = DB()

        log.info("Waiting for database migrations to complete...")

        with db.transaction():
            db.execute(f"select pg_advisory_xact_lock({INIT_LOCK})")

            contacts.initialize(db)

            if not db.single("select exists (select from pg_tables where tablename = 'migrations')"):
                db.execute("create table migrations (name text, ran_at timestamptz)")

            for name, module in migration_list:
                if not db.single("select ran_at from migrations where name = %s", name):
                    log.info(f"  Running %s...", name)
                    module.run(db)
                    db.execute("insert into migrations (name, ran_at) values (%s, now())", name)
                    log.info(f"  ...complete")

        log.info("...finished")
    except:
        log.exception("Error running database migrations")
        raise

run()
