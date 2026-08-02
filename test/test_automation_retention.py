import os
import shortuuid
from datetime import datetime, timedelta

import test_base
from api import automations
from api.migrations import (
    add_automation_email_events_table,
    add_automation_enrolments_table,
    add_automation_step_runs_table,
    add_automation_trigger_events_table,
    add_debug_email_tables,
)


class TestAutomationRetentionCleanup(test_base.TestBase):

    def setUp(self):
        super(TestAutomationRetentionCleanup, self).setUp()
        add_debug_email_tables.run(self.db)
        add_automation_trigger_events_table.run(self.db)
        add_automation_email_events_table.run(self.db)
        add_automation_step_runs_table.run(self.db)
        add_automation_enrolments_table.run(self.db)
        self.test_id = "automation_retention_%s" % shortuuid.uuid().lower()
        self.created_debug_log_ids = []
        self.created_trigger_event_ids = []
        self.created_email_event_ids = []
        self.created_step_run_ids = []
        self.created_enrolment_ids = []
        self.original_env = {
            "automation_retention_cleanup_enabled": os.environ.get("automation_retention_cleanup_enabled"),
            "automation_retention_debug_email_log_days": os.environ.get("automation_retention_debug_email_log_days"),
            "automation_retention_trigger_event_days": os.environ.get("automation_retention_trigger_event_days"),
            "automation_retention_delete_limit": os.environ.get("automation_retention_delete_limit"),
            "automation_retention_account_limit": os.environ.get("automation_retention_account_limit"),
        }
        for key in self.original_env:
            os.environ.pop(key, None)

    def tearDown(self):
        if self.created_debug_log_ids:
            self.db.execute("delete from debug_email_logs where id = any(%s)", self.created_debug_log_ids)
        if self.created_trigger_event_ids:
            self.db.execute("delete from automation_trigger_events where id = any(%s)", self.created_trigger_event_ids)
        if self.created_email_event_ids:
            self.db.execute("delete from automation_email_events where id = any(%s)", self.created_email_event_ids)
        if self.created_step_run_ids:
            self.db.execute("delete from automation_step_runs where id = any(%s)", self.created_step_run_ids)
        if self.created_enrolment_ids:
            self.db.execute("delete from automation_enrolments where id = any(%s)", self.created_enrolment_ids)
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        super(TestAutomationRetentionCleanup, self).tearDown()

    def enable_cleanup(self):
        os.environ["automation_retention_cleanup_enabled"] = "true"

    def cid(self):
        return self.user_cookie["cid"]

    def insert_debug_log(self, cid=None, ts=None):
        id = shortuuid.uuid()
        self.created_debug_log_ids.append(id)
        self.db.execute(
            "insert into debug_email_logs (id, cid, ts, data) values (%s, %s, %s, %s)",
            id,
            cid or self.cid(),
            ts or datetime.utcnow(),
            {"metadata": {"test_id": self.test_id}},
        )
        return id

    def insert_trigger_event(self, status, cid=None, ts=None):
        id = shortuuid.uuid()
        self.created_trigger_event_ids.append(id)
        self.db.execute(
            """
            insert into automation_trigger_events
                (id, cid, contact_id, contact_email, event_type, ts, data)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            id,
            cid or self.cid(),
            123456,
            "%s@example.com" % self.test_id,
            "tag_added",
            ts or datetime.utcnow(),
            {
                "status": status,
                "correlation_id": self.test_id,
            },
        )
        return id

    def count_rows(self, table, ids):
        return int(self.db.single("select count(*) from %s where id = any(%%s)" % table, ids) or 0)

    def test_flag_off_does_nothing(self):
        old_ts = datetime.utcnow() - timedelta(days=60)
        debug_id = self.insert_debug_log(ts=old_ts)
        trigger_id = self.insert_trigger_event("processed", ts=old_ts)

        result = automations.check_automation_retention_cleanup()

        self.assertEqual(result["enabled"], False)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(self.count_rows("debug_email_logs", [debug_id]), 1)
        self.assertEqual(self.count_rows("automation_trigger_events", [trigger_id]), 1)

    def test_old_debug_logs_deleted_and_recent_kept(self):
        self.enable_cleanup()
        old_id = self.insert_debug_log(ts=datetime.utcnow() - timedelta(days=15))
        recent_id = self.insert_debug_log(ts=datetime.utcnow() - timedelta(days=1))

        result = automations.check_automation_retention_cleanup()

        self.assertEqual(result["debug_email_logs_deleted"], 1)
        self.assertEqual(self.count_rows("debug_email_logs", [old_id]), 0)
        self.assertEqual(self.count_rows("debug_email_logs", [recent_id]), 1)

    def test_old_finished_trigger_events_deleted_and_recent_or_live_kept(self):
        self.enable_cleanup()
        old_ts = datetime.utcnow() - timedelta(days=31)
        recent_ts = datetime.utcnow() - timedelta(days=1)
        old_processed = self.insert_trigger_event("processed", ts=old_ts)
        old_failed = self.insert_trigger_event("failed", ts=old_ts)
        old_suppressed = self.insert_trigger_event("suppressed", ts=old_ts)
        old_enrolled = self.insert_trigger_event("enrolled", ts=old_ts)
        recent_processed = self.insert_trigger_event("processed", ts=recent_ts)
        old_pending = self.insert_trigger_event("pending", ts=old_ts)
        fresh_processing = self.insert_trigger_event("processing", ts=recent_ts)

        result = automations.check_automation_retention_cleanup()

        self.assertEqual(result["automation_trigger_events_deleted"], 4)
        self.assertEqual(
            self.count_rows(
                "automation_trigger_events",
                [old_processed, old_failed, old_suppressed, old_enrolled],
            ),
            0,
        )
        self.assertEqual(
            self.count_rows(
                "automation_trigger_events",
                [recent_processed, old_pending, fresh_processing],
            ),
            3,
        )

    def test_row_limit_is_enforced(self):
        self.enable_cleanup()
        os.environ["automation_retention_delete_limit"] = "2"
        old_ts = datetime.utcnow() - timedelta(days=60)
        ids = [self.insert_debug_log(ts=old_ts) for _ in range(3)]

        result = automations.check_automation_retention_cleanup()

        self.assertEqual(result["debug_email_logs_deleted"], 2)
        self.assertEqual(self.count_rows("debug_email_logs", ids), 1)

    def test_account_cap_limits_number_of_accounts_cleaned(self):
        self.enable_cleanup()
        os.environ["automation_retention_account_limit"] = "1"
        old_ts = datetime.utcnow() - timedelta(days=60)
        other_cid = "%s_other" % self.test_id
        first_id = self.insert_debug_log(cid=self.cid(), ts=old_ts)
        second_id = self.insert_debug_log(cid=other_cid, ts=old_ts)

        result = automations.check_automation_retention_cleanup()

        self.assertEqual(result["accounts"], 1)
        self.assertEqual(result["debug_email_logs_deleted"], 1)
        self.assertEqual(self.count_rows("debug_email_logs", [first_id, second_id]), 1)

    def test_cleanup_does_not_delete_engagement_step_runs_or_enrolments(self):
        self.enable_cleanup()
        old_ts = datetime.utcnow() - timedelta(days=200)
        email_event_id = shortuuid.uuid()
        step_run_id = shortuuid.uuid()
        enrolment_id = shortuuid.uuid()
        self.created_email_event_ids.append(email_event_id)
        self.created_step_run_ids.append(step_run_id)
        self.created_enrolment_ids.append(enrolment_id)
        self.db.execute(
            """
            insert into automation_email_events (
                id, cid, contact_id, contact_email, automation_id, automation_email_id,
                enrolment_id, send_node_id, send_step_run_id, event_type, ts, data
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            email_event_id,
            self.cid(),
            123456,
            "%s@example.com" % self.test_id,
            "%s_automation" % self.test_id,
            "%s_email" % self.test_id,
            enrolment_id,
            "%s_node" % self.test_id,
            step_run_id,
            "open",
            old_ts,
            {"test_id": self.test_id},
        )
        self.db.execute(
            """
            insert into automation_step_runs
                (id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            step_run_id,
            self.cid(),
            "%s_automation" % self.test_id,
            enrolment_id,
            123456,
            "%s_node" % self.test_id,
            "send_email",
            {"test_id": self.test_id, "created": old_ts.isoformat() + "Z"},
        )
        self.db.execute(
            """
            insert into automation_enrolments
                (id, cid, automation_id, contact_id, contact_email, data)
            values (%s, %s, %s, %s, %s, %s)
            """,
            enrolment_id,
            self.cid(),
            "%s_automation" % self.test_id,
            123456,
            "%s@example.com" % self.test_id,
            {"test_id": self.test_id, "status": "completed", "created": old_ts.isoformat() + "Z"},
        )

        result = automations.check_automation_retention_cleanup()

        self.assertEqual(result["deleted"], 0)
        self.assertEqual(self.count_rows("automation_email_events", [email_event_id]), 1)
        self.assertEqual(self.count_rows("automation_step_runs", [step_run_id]), 1)
        self.assertEqual(self.count_rows("automation_enrolments", [enrolment_id]), 1)
