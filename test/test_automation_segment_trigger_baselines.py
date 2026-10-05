import os
import psycopg2
import shortuuid
from datetime import datetime, timedelta

import test_base
from api import automations
from api.migrations import (
    add_automation_segment_trigger_baselines_table,
    add_automation_trigger_events_table,
)


class TestAutomationSegmentTriggerBaselines(test_base.TestBase):

    def setUp(self):
        super(TestAutomationSegmentTriggerBaselines, self).setUp()
        add_automation_trigger_events_table.run(self.db)
        add_automation_segment_trigger_baselines_table.run(self.db)
        self.test_id = "automation_segment_baseline_%s" % shortuuid.uuid().lower()
        self.created_automation_ids = []
        self.created_list_ids = []
        self.created_segment_ids = []
        self.created_emails = []
        self.created_other_cids = []
        self.created_admin_user_ids = []
        self.created_admin_cookie_ids = []
        self.original_env = {
            "automation_segment_trigger_baseline_enabled": os.environ.get("automation_segment_trigger_baseline_enabled"),
            "automation_segment_trigger_diff_enabled": os.environ.get("automation_segment_trigger_diff_enabled"),
            "automation_triggers_enabled": os.environ.get("automation_triggers_enabled"),
        }
        company = self.db.companies.get(self.user_cookie["cid"])
        self.original_company_automation_settings = {
            "automation_processing_enabled": company.get("automation_processing_enabled"),
            "automation_diagnostics_visible": company.get("automation_diagnostics_visible"),
        }
        self.original_hashlimit = self.db.single(
            "select hashlimit from contacts.contacts_hashlimit where cid = %s",
            self.user_cookie["cid"],
        )
        os.environ.pop("automation_segment_trigger_baseline_enabled", None)
        os.environ.pop("automation_segment_trigger_diff_enabled", None)
        os.environ.pop("automation_triggers_enabled", None)

    def tearDown(self):
        cid = self.user_cookie["cid"]
        if self.created_segment_ids:
            self.db.execute(
                "delete from automation_trigger_events where cid = %s and data->>'segment_id' = any(%s)",
                cid,
                self.created_segment_ids,
            )
            self.db.execute(
                "delete from automation_segment_trigger_members where cid = %s and segment_id = any(%s)",
                cid,
                self.created_segment_ids,
            )
            self.db.execute(
                "delete from automation_segment_trigger_snapshots where cid = %s and segment_id = any(%s)",
                cid,
                self.created_segment_ids,
            )
        if self.created_other_cids:
            self.db.execute(
                "delete from automation_trigger_events where cid = any(%s)",
                self.created_other_cids,
            )
            self.db.execute(
                "delete from automation_segment_trigger_members where cid = any(%s)",
                self.created_other_cids,
            )
            self.db.execute(
                "delete from automation_segment_trigger_snapshots where cid = any(%s)",
                self.created_other_cids,
            )
            self.db.execute(
                "delete from automations where cid = any(%s)",
                self.created_other_cids,
            )
            self.db.execute(
                "delete from segments where cid = any(%s)",
                self.created_other_cids,
            )
            self.db.execute(
                "delete from companies where id = any(%s)",
                self.created_other_cids,
            )
        if self.created_automation_ids:
            self.db.execute(
                "delete from automation_enrolments where automation_id = any(%s)",
                self.created_automation_ids,
            )
            self.db.execute(
                "delete from automations where id = any(%s) and cid = %s",
                self.created_automation_ids,
                cid,
            )
        if self.created_emails:
            contact_ids = [
                row[0]
                for row in self.db.execute(
                    f"""select contact_id from contacts."contacts_{cid}" where email = any(%s)""",
                    self.created_emails,
                )
            ]
            if contact_ids:
                self.db.execute(
                    f"""delete from contacts."contact_values_{cid}" where contact_id = any(%s)""",
                    contact_ids,
                )
                self.db.execute(
                    f"""delete from contacts."contact_lists_{cid}" where contact_id = any(%s)""",
                    contact_ids,
                )
            self.db.execute(
                f"""delete from contacts."contacts_{cid}" where email = any(%s)""",
                self.created_emails,
            )
        if self.created_segment_ids:
            self.db.execute(
                "delete from segments where id = any(%s) and cid = %s",
                self.created_segment_ids,
                cid,
            )
        if self.created_list_ids:
            self.db.execute(
                f"""delete from contacts."contact_lists_{cid}" where list_id = any(%s)""",
                self.created_list_ids,
            )
            self.db.execute(
                "delete from lists where id = any(%s) and cid = %s",
                self.created_list_ids,
                cid,
            )
        if self.original_hashlimit is None:
            self.db.execute(
                "delete from contacts.contacts_hashlimit where cid = %s",
                cid,
            )
        else:
            self.db.execute(
                """
                insert into contacts.contacts_hashlimit (cid, hashlimit)
                values (%s, %s)
                on conflict (cid) do update set hashlimit = excluded.hashlimit
                """,
                cid,
                self.original_hashlimit,
            )
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.db.execute(
            """
            update companies
            set data = data - 'automation_processing_enabled' - 'automation_diagnostics_visible'
            where id = %s
            """,
            self.user_cookie["cid"],
        )
        company_patch = {
            key: value
            for key, value in self.original_company_automation_settings.items()
            if value is not None
        }
        if company_patch:
            self.db.execute(
                "update companies set data = data || %s where id = %s",
                company_patch,
                self.user_cookie["cid"],
            )
        if self.created_admin_cookie_ids:
            self.db.execute(
                "delete from cookies where id = any(%s)",
                self.created_admin_cookie_ids,
            )
        if self.created_admin_user_ids:
            self.db.execute(
                "delete from users where id = any(%s)",
                self.created_admin_user_ids,
            )
        super(TestAutomationSegmentTriggerBaselines, self).tearDown()

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def backend_cid(self):
        company = self.db.companies.get(self.user_cookie["cid"])
        return company["cid"]

    def create_admin_cookie(self):
        backend_cid = self.backend_cid()
        oldcid = self.db.get_cid()
        self.db.set_cid(backend_cid)
        try:
            admin_uid = self.db.users.add(
                {
                    "username": "automation-segment-admin-%s@example.com" % self.unique(),
                    "fullname": "Automation Segment Admin",
                    "companyname": "Automation Segment Admin Company",
                    "admin": True,
                    "created": datetime.utcnow().isoformat() + "Z",
                }
            )
            cookie_id = self.db.cookies.add(
                {
                    "lastused": datetime.utcnow().isoformat() + "Z",
                    "uid": admin_uid,
                    "admin": True,
                }
            )
        finally:
            self.db.set_cid(oldcid)
        self.created_admin_user_ids.append(admin_uid)
        self.created_admin_cookie_ids.append(cookie_id)
        self.admin_cookie = self.db.cookies.get(cookie_id)

    def admin_headers(self):
        if not self.created_admin_cookie_ids:
            self.create_admin_cookie()
        return {
            "X-Auth-UID": self.admin_cookie["uid"],
            "X-Auth-Cookie": self.admin_cookie["id"],
        }

    def admin_impersonation_headers(self):
        headers = self.admin_headers()
        headers["X-Auth-Impersonate"] = self.user_cookie["cid"]
        return headers

    def enable_baseline(self):
        os.environ["automation_segment_trigger_baseline_enabled"] = "true"

    def enable_diff(self):
        os.environ["automation_segment_trigger_diff_enabled"] = "true"

    def enable_trigger_processing(self):
        os.environ["automation_triggers_enabled"] = "true"

    def set_customer_automation_processing(self, enabled):
        self.db.execute(
            "update companies set data = data || %s where id = %s",
            {"automation_processing_enabled": enabled},
            self.user_cookie["cid"],
        )

    def set_customer_automation_diagnostics(self, visible):
        self.db.execute(
            "update companies set data = data || %s where id = %s",
            {"automation_diagnostics_visible": visible},
            self.user_cookie["cid"],
        )

    def clear_customer_automation_diagnostics(self):
        self.db.execute(
            "update companies set data = data - 'automation_diagnostics_visible' where id = %s",
            self.user_cookie["cid"],
        )

    def create_contact_list(self, name=None):
        lst = self.user_post(
            "/api/lists",
            json={"name": name or "%s_list_%s" % (self.test_id, self.unique())},
        )
        self.created_list_ids.append(lst["id"])
        return lst

    def add_contact(self, list_id, email=None):
        email = email or "%s-%s@example.com" % (self.test_id, self.unique())
        self.created_emails.append(email)
        self.user_post(
            "/api/lists/%s/feed" % list_id,
            json={
                "email": email,
                "data": {
                    "First Name": "Automation",
                },
            },
        )
        contact_id = self.db.single(
            f"""select contact_id from contacts."contacts_{self.user_cookie['cid']}" where email = %s""",
            email,
        )
        return email, contact_id

    def create_segment(self, prefix=None, empty=False):
        prefix = prefix or self.test_id
        doc = {
            "name": "%s_segment_%s" % (self.test_id, self.unique()),
            "parts": [],
        }
        if not empty:
            doc.update({
                "operator": "and",
                "parts": [{
                    "type": "Info",
                    "prop": "Email",
                    "operator": "contains",
                    "value": prefix,
                }],
                "subset": False,
                "subsettype": "percent",
                "subsetpct": 10,
                "subsetnum": 2000,
            })
        segment = self.user_post("/api/segments", json=doc)
        self.created_segment_ids.append(segment["id"])
        return segment

    def create_tag_segment(self, tag):
        segment = self.user_post(
            "/api/segments",
            json={
                "name": "%s_tag_segment_%s" % (self.test_id, self.unique()),
                "operator": "and",
                "parts": [{
                    "type": "Info",
                    "test": "tag",
                    "tag": tag,
                }],
                "subset": False,
                "subsettype": "percent",
                "subsetpct": 10,
                "subsetnum": 2000,
            },
        )
        self.created_segment_ids.append(segment["id"])
        return segment

    def add_tag_value(self, contact_id, tag):
        self.db.execute(
            f"""insert into contacts."contact_values_{self.user_cookie['cid']}" (contact_id, type, value)
                values (%s, 'tag', %s)
                on conflict (contact_id, type, value) do nothing""",
            contact_id,
            tag,
        )

    def remove_tag_value(self, contact_id, tag):
        self.db.execute(
            f"""delete from contacts."contact_values_{self.user_cookie['cid']}"
                where contact_id = %s and type = 'tag' and value = %s""",
            contact_id,
            tag,
        )

    def create_automation(self, entry, publish=True, paused=False):
        automation = self.user_post(
            "/api/automations",
            json={"name": "%s_automation_%s" % (self.test_id, self.unique())},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json={
                "entry": entry,
                "reentry": "once",
                "draft": {
                    "nodes": [
                        {
                            "id": "node_exit_1",
                            "type": "exit",
                            "label": "Exit automation",
                        },
                    ],
                },
            },
        )
        if not publish:
            return automation
        published = self.user_post("/api/automations/%s/publish" % automation["id"])
        if paused:
            return self.user_post("/api/automations/%s/pause" % automation["id"])
        return published

    def create_scheduler_account(self, entry=None, automation_processing_enabled=True, published=True, paused=False, baseline_complete=None):
        cid = "%s_scheduler_%s" % (self.test_id, self.unique())
        segment_id = "%s_segment" % cid
        automation_id = "%s_automation" % cid
        self.created_other_cids.append(cid)
        if entry is None:
            entry = {"type": "segment_entered", "segment_id": segment_id}
        elif callable(entry):
            entry = entry(segment_id)
        self.db.execute(
            "insert into companies (id, cid, data) values (%s, %s, %s)",
            cid,
            cid,
            {
                "admin": False,
                "name": "Automation segment scheduler test",
                "automation_processing_enabled": automation_processing_enabled,
            },
        )
        self.db.execute(
            "insert into segments (id, cid, data) values (%s, %s, %s)",
            segment_id,
            cid,
            {
                "name": "Scheduler segment",
                "operator": "and",
                "parts": [{
                    "type": "Info",
                    "prop": "Email",
                    "operator": "contains",
                    "value": self.test_id,
                }],
            },
        )
        status = "draft"
        data = {
            "name": "Scheduler automation",
            "status": status,
            "entry": entry,
            "draft": {
                "nodes": [{"id": "node_exit_1", "type": "exit", "label": "Exit"}],
            },
        }
        if published:
            status = "paused" if paused else "published"
            data["status"] = status
            data["published"] = {
                "entry": entry,
                "nodes": [{"id": "node_exit_1", "type": "exit", "label": "Exit"}],
            }
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            automation_id,
            cid,
            data,
        )
        if baseline_complete is not None:
            self.db.execute(
                """
                insert into automation_segment_trigger_snapshots
                    (id, cid, segment_id, status, hashlimit, last_hashval, data)
                values (%s, %s, %s, 'completed', 1, null, %s)
                """,
                "%s:%s" % (cid, segment_id),
                cid,
                segment_id,
                {
                    "baseline_complete": baseline_complete,
                    "hashlimit_initialized": True,
                },
            )
        return cid, segment_id, automation_id

    def baseline(self, **doc):
        return self.user_post("/api/automation-segment-trigger-baselines", json=doc)

    def diff(self, **doc):
        doc["mode"] = "diff"
        return self.user_post("/api/automation-segment-trigger-baselines", json=doc)

    def scan_task(self, mode="baseline", segment_id=None, limit_segments=None, limit_buckets=None, limit_events=None):
        return automations.process_automation_segment_triggers_task(
            self.user_cookie["cid"],
            mode,
            segment_id,
            limit_segments,
            limit_buckets,
            limit_events,
        )

    def run_segment_scheduler_with_task_patch(self):
        original_run_task = automations.run_task
        dispatched = []

        def fake_run_task(task, cid, mode, segment_id, limit_segments, limit_buckets, limit_events):
            dispatched.append({
                "task": task,
                "cid": cid,
                "mode": mode,
                "segment_id": segment_id,
                "limit_segments": limit_segments,
                "limit_buckets": limit_buckets,
                "limit_events": limit_events,
            })
            return "segment-task-%s" % len(dispatched)

        automations.run_task = fake_run_task
        try:
            result = automations.check_automation_segment_triggers()
        finally:
            automations.run_task = original_run_task
        return result, dispatched

    def snapshot(self, segment_id):
        return self.db.row(
            """
            select status, hashlimit, last_hashval, data
            from automation_segment_trigger_snapshots
            where cid = %s and segment_id = %s
            """,
            self.user_cookie["cid"],
            segment_id,
        )

    def member_count(self, segment_id):
        return self.db.single(
            """
            select count(*) from automation_segment_trigger_members
            where cid = %s and segment_id = %s
            """,
            self.user_cookie["cid"],
            segment_id,
        )

    def snapshot_segment_ids(self):
        return [
            row[0]
            for row in self.db.execute(
                """
                select segment_id
                from automation_segment_trigger_snapshots
                where cid = %s and segment_id = any(%s)
                order by segment_id
                """,
                self.user_cookie["cid"],
                self.created_segment_ids,
            )
        ]

    def trigger_event_count(self):
        return self.db.single(
            "select count(*) from automation_trigger_events where cid = %s",
            self.user_cookie["cid"],
        )

    def segment_trigger_events(self, segment_id):
        return [
            {
                "id": row[0],
                "event_type": row[1],
                "contact_email": row[2],
                "data": row[3],
            }
            for row in self.db.execute(
                """
                select id, event_type, contact_email, data
                from automation_trigger_events
                where cid = %s and data->>'segment_id' = %s
                order by ts, id
                """,
                self.user_cookie["cid"],
                segment_id,
            )
        ]

    def segment_trigger_status(self, limit=None):
        self.set_customer_automation_diagnostics(True)
        path = "/api/automation-segment-trigger-status"
        if limit is not None:
            path += "?limit=%s" % limit
        return self.user_get(path)

    def insert_segment_trigger_event(self, segment_id, event_type="segment_entered", contact_id=1, cid=None):
        cid = cid or self.user_cookie["cid"]
        event_id = "%s_event_%s" % (self.test_id, self.unique())
        self.db.execute(
            """
            insert into automation_trigger_events
                (id, cid, contact_id, contact_email, event_type, ts, data)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            event_id,
            cid,
            contact_id,
            "%s-event@example.com" % self.test_id,
            event_type,
            datetime.utcnow(),
            {
                "status": "pending",
                "segment_id": segment_id,
                "metadata": {"secret": "not returned"},
            },
        )
        return event_id

    def force_hashlimit(self, list_id, hashlimit):
        self.db.execute(
            "update lists set data = data || %s where id = %s and cid = %s",
            {"count": 10001},
            list_id,
            self.user_cookie["cid"],
        )
        self.db.execute(
            """
            insert into contacts.contacts_hashlimit (cid, hashlimit)
            values (%s, %s)
            on conflict (cid) do update set hashlimit = excluded.hashlimit
            """,
            self.user_cookie["cid"],
            hashlimit,
        )

    def test_flag_off_does_nothing(self):
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})

        result = self.baseline()

        self.assertFalse(result["enabled"])
        self.assertEqual(result["events_created"], 0)
        self.assertIsNone(self.snapshot(segment["id"]))

    def test_single_entry_referenced_segment_baselines_matching_members(self):
        self.enable_baseline()
        lst = self.create_contact_list()
        email, contact_id = self.add_contact(lst["id"])
        segment = self.create_segment(prefix=email)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        before_events = self.trigger_event_count()

        result = self.baseline(segment_id=segment["id"])

        self.assertTrue(result["enabled"])
        self.assertEqual(result["segments_seen"], 1)
        self.assertEqual(result["segments_claimed"], 1)
        self.assertEqual(result["buckets_processed"], 1)
        self.assertEqual(result["members_upserted"], 1)
        self.assertEqual(result["events_created"], 0)
        self.assertEqual(self.trigger_event_count(), before_events)
        self.assertEqual(self.member_count(segment["id"]), 1)
        member_email = self.db.single(
            """
            select contact_email from automation_segment_trigger_members
            where cid = %s and segment_id = %s and contact_id = %s
            """,
            self.user_cookie["cid"],
            segment["id"],
            contact_id,
        )
        self.assertEqual(member_email, email)
        status, _, last_hashval, data = self.snapshot(segment["id"])
        self.assertEqual(status, "completed")
        self.assertIsNone(last_hashval)
        self.assertTrue(data["baseline_complete"])

    def test_multi_entry_non_first_referenced_segment_baselines(self):
        self.enable_baseline()
        segment = self.create_segment()
        self.create_automation({
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "%s_tag" % self.test_id},
                {"type": "segment_left", "segment_id": segment["id"]},
            ],
        })

        result = self.baseline()

        self.assertEqual(result["segments_seen"], 1)
        self.assertEqual(result["segments_claimed"], 1)
        self.assertIsNotNone(self.snapshot(segment["id"]))

    def test_unreferenced_draft_and_unpublished_segments_are_ignored(self):
        self.enable_baseline()
        unreferenced = self.create_segment()
        draft_only = self.create_segment()
        unpublished = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": draft_only["id"]}, publish=False)
        automation = self.create_automation({"type": "manual"}, publish=False)
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json={
                "entry": {"type": "segment_left", "segment_id": unpublished["id"]},
                "draft": {
                    "nodes": [
                        {
                            "id": "node_exit_1",
                            "type": "exit",
                            "label": "Exit automation",
                        },
                    ],
                },
            },
        )

        result = self.baseline()

        self.assertEqual(result["segments_seen"], 0)
        self.assertIsNone(self.snapshot(unreferenced["id"]))
        self.assertIsNone(self.snapshot(draft_only["id"]))
        self.assertIsNone(self.snapshot(unpublished["id"]))

    def test_paused_published_automation_is_included(self):
        self.enable_baseline()
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]}, paused=True)

        result = self.baseline()

        self.assertEqual(result["segments_seen"], 1)
        self.assertEqual(result["segments_claimed"], 1)

    def test_empty_segment_is_skipped_cleanly(self):
        self.enable_baseline()
        segment = self.create_segment(empty=True)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})

        result = self.baseline()

        self.assertEqual(result["segments_seen"], 1)
        self.assertEqual(result["segments_claimed"], 1)
        self.assertEqual(result["events_created"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "invalid_segment")
        status, _, _, data = self.snapshot(segment["id"])
        self.assertEqual(status, "skipped_invalid")
        self.assertEqual(data["last_error"], "No rules in segment")

    def test_current_account_scoping(self):
        self.enable_baseline()
        other_cid = "%s_other_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        other_segment_id = "%s_other_segment" % self.test_id
        self.db.execute(
            "insert into segments (id, cid, data) values (%s, %s, %s)",
            other_segment_id,
            other_cid,
            {"name": "Other", "parts": []},
        )
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            "%s_other_automation" % self.test_id,
            other_cid,
            {
                "name": "Other",
                "status": "published",
                "published": {
                    "entry": {"type": "segment_entered", "segment_id": other_segment_id},
                    "nodes": [{"id": "node_exit_1", "type": "exit", "label": "Exit"}],
                },
            },
        )

        result = self.baseline()

        self.assertEqual(result["segments_seen"], 0)

    def test_segment_and_bucket_limits_are_enforced_and_resumable(self):
        self.enable_baseline()
        lst = self.create_contact_list()
        self.add_contact(lst["id"])
        self.force_hashlimit(lst["id"], 3)
        first_segment = self.create_segment()
        second_segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": first_segment["id"]})
        self.create_automation({"type": "segment_entered", "segment_id": second_segment["id"]})

        first = self.baseline(limit_segments=1, limit_buckets=1)
        second = self.baseline(limit_segments=1, limit_buckets=1)

        self.assertEqual(first["segments_seen"], 2)
        self.assertEqual(first["segments_claimed"], 1)
        self.assertEqual(first["buckets_processed"], 1)
        self.assertEqual(second["segments_claimed"], 1)
        self.assertEqual(second["buckets_processed"], 1)
        snapshot_segment_ids = self.snapshot_segment_ids()
        self.assertEqual(len(snapshot_segment_ids), 1)
        self.assertIn(snapshot_segment_ids[0], (first_segment["id"], second_segment["id"]))
        status, hashlimit, last_hashval, data = self.snapshot(snapshot_segment_ids[0])
        self.assertEqual(hashlimit, 3)
        self.assertEqual(status, "idle")
        self.assertEqual(last_hashval, 1)
        self.assertFalse(data["baseline_complete"])

    def test_non_stale_claim_prevents_duplicate_baseline(self):
        self.enable_baseline()
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, claimed_at, claim_token, data)
            values (%s, %s, %s, 'baselining', 1, null, %s, 'existing', %s)
            """,
            "%s:%s" % (self.user_cookie["cid"], segment["id"]),
            self.user_cookie["cid"],
            segment["id"],
            datetime.utcnow(),
            {"baseline_complete": False},
        )

        result = self.baseline()

        self.assertEqual(result["segments_claimed"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "already_baselining")

    def test_stale_claim_is_recovered(self):
        self.enable_baseline()
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, claimed_at, claim_token, data)
            values (%s, %s, %s, 'baselining', 1, null, %s, 'stale', %s)
            """,
            "%s:%s" % (self.user_cookie["cid"], segment["id"]),
            self.user_cookie["cid"],
            segment["id"],
            datetime.utcnow() - timedelta(minutes=31),
            {"baseline_complete": False},
        )

        result = self.baseline()

        self.assertEqual(result["segments_claimed"], 1)
        status, _, _, data = self.snapshot(segment["id"])
        self.assertEqual(status, "completed")
        self.assertTrue(data["recovered_claim"])

    def test_hashlimit_change_clears_and_rebuilds_members(self):
        self.enable_baseline()
        lst = self.create_contact_list()
        email, _ = self.add_contact(lst["id"])
        segment = self.create_segment(prefix=email)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        self.assertEqual(self.member_count(segment["id"]), 1)

        self.force_hashlimit(lst["id"], 2)
        result = self.baseline(segment_id=segment["id"], limit_buckets=2)

        self.assertEqual(result["events_created"], 0)
        self.assertEqual(result["segments_claimed"], 1)
        self.assertEqual(result["skipped"][0]["reason"], "hashlimit_changed_rebaseline")
        status, hashlimit, _, data = self.snapshot(segment["id"])
        self.assertEqual(status, "completed")
        self.assertEqual(hashlimit, 2)
        self.assertTrue(data["baseline_complete"])

    def test_diff_flag_off_does_no_work(self):
        self.enable_baseline()
        lst = self.create_contact_list()
        email, _ = self.add_contact(lst["id"])
        segment = self.create_segment(prefix=email)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])

        result = self.diff(segment_id=segment["id"])

        self.assertFalse(result["enabled"])
        self.assertEqual(result["mode"], "diff")
        self.assertEqual(result["events_created"], 0)

    def test_diff_requires_completed_baseline(self):
        self.enable_diff()
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})

        no_snapshot = self.diff(segment_id=segment["id"])
        self.assertEqual(no_snapshot["events_created"], 0)
        self.assertEqual(no_snapshot["skipped"][0]["reason"], "baseline_required")

        self.db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, data)
            values (%s, %s, %s, 'idle', 1, null, %s)
            """,
            "%s:%s" % (self.user_cookie["cid"], segment["id"]),
            self.user_cookie["cid"],
            segment["id"],
            {"baseline_complete": False, "hashlimit_initialized": True},
        )
        incomplete = self.diff(segment_id=segment["id"])
        self.assertEqual(incomplete["events_created"], 0)
        self.assertEqual(incomplete["skipped"][0]["reason"], "baseline_incomplete")

    def test_diff_entered_contact_emits_segment_entered_event(self):
        self.enable_baseline()
        self.enable_diff()
        lst = self.create_contact_list()
        segment = self.create_segment(prefix=self.test_id)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        email, _ = self.add_contact(lst["id"])

        result = self.diff(segment_id=segment["id"])

        self.assertEqual(result["events_created"], 1)
        self.assertEqual(result["segment_entered_events_created"], 1)
        events = self.segment_trigger_events(segment["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "segment_entered")
        self.assertEqual(events[0]["contact_email"], email)
        self.assertEqual(events[0]["data"]["source"]["type"], "automation_segment_scanner")
        self.assertEqual(events[0]["data"]["source"]["mode"], "diff")

    def test_diff_left_contact_emits_segment_left_event(self):
        self.enable_baseline()
        self.enable_diff()
        tag = "%s_left_tag" % self.test_id
        lst = self.create_contact_list()
        email, contact_id = self.add_contact(lst["id"])
        self.add_tag_value(contact_id, tag)
        segment = self.create_tag_segment(tag)
        self.create_automation({"type": "segment_left", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        self.remove_tag_value(contact_id, tag)

        result = self.diff(segment_id=segment["id"])

        self.assertEqual(result["events_created"], 1)
        self.assertEqual(result["segment_left_events_created"], 1)
        events = self.segment_trigger_events(segment["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "segment_left")
        self.assertEqual(events[0]["contact_email"], email)

    def test_diff_unconfigured_direction_emits_no_event(self):
        self.enable_baseline()
        self.enable_diff()
        tag = "%s_unconfigured_tag" % self.test_id
        lst = self.create_contact_list()
        _, contact_id = self.add_contact(lst["id"])
        self.add_tag_value(contact_id, tag)
        segment = self.create_tag_segment(tag)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        self.remove_tag_value(contact_id, tag)

        result = self.diff(segment_id=segment["id"])

        self.assertEqual(result["events_created"], 0)
        self.assertEqual(self.segment_trigger_events(segment["id"]), [])

    def test_repeated_diff_does_not_duplicate_events(self):
        self.enable_baseline()
        self.enable_diff()
        lst = self.create_contact_list()
        segment = self.create_segment(prefix=self.test_id)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        self.add_contact(lst["id"])

        first = self.diff(segment_id=segment["id"])
        second = self.diff(segment_id=segment["id"])

        self.assertEqual(first["events_created"], 1)
        self.assertEqual(second["events_created"], 0)
        self.assertEqual(len(self.segment_trigger_events(segment["id"])), 1)

    def test_event_cap_prevents_partial_bucket_processing(self):
        self.enable_baseline()
        self.enable_diff()
        lst = self.create_contact_list()
        segment = self.create_segment(prefix=self.test_id)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        self.add_contact(lst["id"])
        self.add_contact(lst["id"])
        before_members = self.member_count(segment["id"])

        result = self.diff(segment_id=segment["id"], limit_events=1)

        self.assertTrue(result["event_limit_reached"])
        self.assertEqual(result["events_created"], 0)
        self.assertEqual(len(self.segment_trigger_events(segment["id"])), 0)
        self.assertEqual(self.member_count(segment["id"]), before_members)
        status, _, last_hashval, _ = self.snapshot(segment["id"])
        self.assertEqual(status, "idle")
        self.assertIsNone(last_hashval)

    def test_diff_bucket_progress_resumes_across_calls(self):
        self.enable_baseline()
        self.enable_diff()
        lst = self.create_contact_list()
        email, _ = self.add_contact(lst["id"])
        self.force_hashlimit(lst["id"], 3)
        segment = self.create_segment(prefix=email)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"], limit_buckets=3)

        first = self.diff(segment_id=segment["id"], limit_buckets=1)
        second = self.diff(segment_id=segment["id"], limit_buckets=1)

        self.assertEqual(first["buckets_processed"], 1)
        self.assertEqual(second["buckets_processed"], 1)
        _, _, last_hashval, data = self.snapshot(segment["id"])
        self.assertEqual(last_hashval, 1)
        self.assertTrue(data["baseline_complete"])

    def test_diff_hashlimit_change_requires_rebaseline_and_emits_zero_events(self):
        self.enable_baseline()
        self.enable_diff()
        lst = self.create_contact_list()
        email, _ = self.add_contact(lst["id"])
        segment = self.create_segment(prefix=email)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])

        self.force_hashlimit(lst["id"], 2)
        result = self.diff(segment_id=segment["id"])

        self.assertEqual(result["events_created"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "hashlimit_changed_rebaseline_required")
        self.assertEqual(self.member_count(segment["id"]), 0)
        status, hashlimit, last_hashval, data = self.snapshot(segment["id"])
        self.assertEqual(status, "idle")
        self.assertEqual(hashlimit, 2)
        self.assertIsNone(last_hashval)
        self.assertFalse(data["baseline_complete"])

    def test_diff_invalid_segment_skipped_cleanly(self):
        self.enable_baseline()
        self.enable_diff()
        segment = self.create_segment(empty=True)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, data)
            values (%s, %s, %s, 'completed', 1, null, %s)
            on conflict (cid, segment_id) do update
                set status = 'completed', hashlimit = 1, last_hashval = null, data = excluded.data
            """,
            "%s:%s" % (self.user_cookie["cid"], segment["id"]),
            self.user_cookie["cid"],
            segment["id"],
            {"baseline_complete": True, "hashlimit_initialized": True},
        )

        result = self.diff(segment_id=segment["id"])

        self.assertEqual(result["events_created"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "invalid_segment")
        status, _, _, data = self.snapshot(segment["id"])
        self.assertEqual(status, "skipped_invalid")
        self.assertEqual(data["last_error"], "No rules in segment")

    def test_diff_includes_paused_and_ignores_draft_unpublished(self):
        self.enable_baseline()
        self.enable_diff()
        paused_segment = self.create_segment()
        draft_segment = self.create_segment()
        unpublished_segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": paused_segment["id"]}, paused=True)
        self.create_automation({"type": "segment_entered", "segment_id": draft_segment["id"]}, publish=False)
        automation = self.create_automation({"type": "manual"}, publish=False)
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json={
                "entry": {"type": "segment_left", "segment_id": unpublished_segment["id"]},
                "draft": {
                    "nodes": [{"id": "node_exit_1", "type": "exit", "label": "Exit automation"}],
                },
            },
        )
        self.baseline()

        result = self.diff()

        self.assertEqual(result["segments_seen"], 1)
        self.assertIsNotNone(self.snapshot(paused_segment["id"]))
        self.assertIsNone(self.snapshot(draft_segment["id"]))
        self.assertIsNone(self.snapshot(unpublished_segment["id"]))

    def test_diff_discovers_multi_entry_segment_trigger(self):
        self.enable_baseline()
        self.enable_diff()
        segment = self.create_segment()
        self.create_automation({
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "%s_tag" % self.test_id},
                {"type": "segment_entered", "segment_id": segment["id"]},
            ],
        })
        self.baseline(segment_id=segment["id"])

        result = self.diff(segment_id=segment["id"])

        self.assertEqual(result["segments_seen"], 1)
        self.assertEqual(result["segments_claimed"], 1)

    def test_diff_current_account_scoping(self):
        self.enable_diff()
        other_cid = "%s_other_diff_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        other_segment_id = "%s_other_diff_segment" % self.test_id
        self.db.execute(
            "insert into segments (id, cid, data) values (%s, %s, %s)",
            other_segment_id,
            other_cid,
            {
                "name": "Other",
                "operator": "and",
                "parts": [{
                    "type": "Info",
                    "prop": "Email",
                    "operator": "contains",
                    "value": self.test_id,
                }],
            },
        )
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            "%s_other_diff_automation" % self.test_id,
            other_cid,
            {
                "name": "Other",
                "status": "published",
                "published": {
                    "entry": {"type": "segment_entered", "segment_id": other_segment_id},
                    "nodes": [{"id": "node_exit_1", "type": "exit", "label": "Exit"}],
                },
            },
        )
        self.db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, data)
            values (%s, %s, %s, 'completed', 1, null, %s)
            """,
            "%s:%s" % (other_cid, other_segment_id),
            other_cid,
            other_segment_id,
            {"baseline_complete": True, "hashlimit_initialized": True},
        )

        result = self.diff()

        self.assertEqual(result["segments_seen"], 0)
        self.assertEqual(result["events_created"], 0)

    def test_diff_non_stale_claim_blocks_and_stale_claim_recovers(self):
        self.enable_baseline()
        self.enable_diff()
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        self.db.execute(
            """
            update automation_segment_trigger_snapshots
            set status = 'diffing', claimed_at = %s, claim_token = 'existing'
            where cid = %s and segment_id = %s
            """,
            datetime.utcnow(),
            self.user_cookie["cid"],
            segment["id"],
        )

        blocked = self.diff(segment_id=segment["id"])
        self.assertEqual(blocked["segments_claimed"], 0)
        self.assertEqual(blocked["skipped"][0]["reason"], "already_diffing")

        self.db.execute(
            """
            update automation_segment_trigger_snapshots
            set status = 'diffing', claimed_at = %s, claim_token = 'stale'
            where cid = %s and segment_id = %s
            """,
            datetime.utcnow() - timedelta(minutes=31),
            self.user_cookie["cid"],
            segment["id"],
        )
        recovered = self.diff(segment_id=segment["id"])
        self.assertEqual(recovered["segments_claimed"], 1)
        _, _, _, data = self.snapshot(segment["id"])
        self.assertTrue(data["recovered_claim"])

    def test_trigger_processor_enrols_from_diff_event(self):
        self.enable_baseline()
        self.enable_diff()
        self.enable_trigger_processing()
        lst = self.create_contact_list()
        segment = self.create_segment(prefix=self.test_id)
        automation = self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        _, contact_id = self.add_contact(lst["id"])

        self.diff(segment_id=segment["id"])
        processed = self.user_post("/api/automation-trigger-events/process", json={"limit": 10})

        self.assertEqual(processed["enrolled"], 1)
        enrolment_count = self.db.single(
            """
            select count(*) from automation_enrolments
            where cid = %s and automation_id = %s and contact_id = %s
            """,
            self.user_cookie["cid"],
            automation["id"],
            contact_id,
        )
        self.assertEqual(enrolment_count, 1)

    def test_segment_trigger_status_hidden_from_customer_by_default(self):
        self.clear_customer_automation_diagnostics()

        result = self.simulate_get(
            "/api/automation-segment-trigger-status",
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)
        self.assertIn("Automation diagnostics are not enabled", result.text)

    def test_segment_trigger_status_projects_missing_and_completed_snapshots(self):
        self.set_customer_automation_diagnostics(True)
        self.set_customer_automation_processing(True)
        self.enable_baseline()
        self.enable_diff()
        self.enable_trigger_processing()
        lst = self.create_contact_list()
        email, contact_id = self.add_contact(lst["id"])
        missing_segment = self.create_segment(prefix="missing-%s" % self.test_id)
        completed_segment = self.create_segment(prefix=email)
        self.create_automation({"type": "segment_entered", "segment_id": missing_segment["id"]})
        self.create_automation({"type": "segment_left", "segment_id": completed_segment["id"]}, paused=True)
        self.db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, last_started_at, last_completed_at, data)
            values (%s, %s, %s, 'completed', 3, null, %s, %s, %s)
            """,
            "%s:%s" % (self.user_cookie["cid"], completed_segment["id"]),
            self.user_cookie["cid"],
            completed_segment["id"],
            datetime.utcnow() - timedelta(minutes=3),
            datetime.utcnow() - timedelta(minutes=2),
            {
                "baseline_complete": True,
                "secret": "not returned",
                "last_error": "bounded visible error",
            },
        )
        self.db.execute(
            """
            insert into automation_segment_trigger_members
                (cid, segment_id, contact_id, contact_email, bucket, first_seen_at, last_seen_at)
            values (%s, %s, %s, %s, 0, %s, %s)
            """,
            self.user_cookie["cid"],
            completed_segment["id"],
            contact_id,
            email,
            datetime.utcnow(),
            datetime.utcnow(),
        )
        self.insert_segment_trigger_event(completed_segment["id"], "segment_entered", contact_id)
        self.insert_segment_trigger_event(completed_segment["id"], "segment_left", contact_id)

        result = self.user_get("/api/automation-segment-trigger-status")

        self.assertEqual(result["limit"], 50)
        self.assertEqual(result["summary"]["referenced_segments"], 2)
        self.assertEqual(result["summary"]["missing_snapshots"], 1)
        self.assertEqual(result["summary"]["baseline_complete"], 1)
        self.assertEqual(result["summary"]["members"], 1)
        self.assertEqual(result["summary"]["recent_events"]["segment_entered"], 1)
        self.assertEqual(result["summary"]["recent_events"]["segment_left"], 1)
        self.assertEqual(result["flags"]["automation_segment_trigger_baseline_enabled"], True)
        self.assertEqual(result["flags"]["automation_segment_trigger_diff_enabled"], True)
        self.assertEqual(result["flags"]["automation_triggers_enabled"], True)
        self.assertEqual(result["flags"]["customer_automation_processing_enabled"], True)

        segments = {row["segment_id"]: row for row in result["segments"]}
        self.assertEqual(segments[missing_segment["id"]]["snapshot"]["exists"], False)
        self.assertEqual(segments[missing_segment["id"]]["snapshot"]["status"], "baseline_needed")
        completed = segments[completed_segment["id"]]
        self.assertEqual(completed["snapshot"]["exists"], True)
        self.assertEqual(completed["snapshot"]["status"], "completed")
        self.assertEqual(completed["snapshot"]["baseline_complete"], True)
        self.assertEqual(completed["snapshot"]["hashlimit"], 3)
        self.assertEqual(completed["snapshot"]["member_count"], 1)
        self.assertEqual(completed["snapshot"]["last_error"], "bounded visible error")
        self.assertEqual(completed["recent_events"]["segment_entered"], 1)
        self.assertEqual(completed["recent_events"]["segment_left"], 1)
        self.assertNotIn("data", completed["snapshot"])
        self.assertNotIn("secret", completed["snapshot"])
        self.assertNotIn("metadata", completed)

    def test_segment_trigger_status_projects_stale_claim(self):
        self.set_customer_automation_diagnostics(True)
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, claimed_at, data)
            values (%s, %s, %s, 'diffing', 1, 0, %s, %s)
            """,
            "%s:%s" % (self.user_cookie["cid"], segment["id"]),
            self.user_cookie["cid"],
            segment["id"],
            datetime.utcnow() - timedelta(minutes=31),
            {
                "baseline_complete": True,
                "skipped_reason": "previous skip",
            },
        )

        result = self.user_get("/api/automation-segment-trigger-status")

        self.assertEqual(result["summary"]["running"], 1)
        self.assertEqual(result["summary"]["stale_claims"], 1)
        snapshot = result["segments"][0]["snapshot"]
        self.assertEqual(snapshot["running"], True)
        self.assertEqual(snapshot["stale_claim"], True)
        self.assertEqual(snapshot["skipped_reason"], "previous skip")

    def test_segment_trigger_status_visible_to_admin_impersonation_and_scoped(self):
        self.set_customer_automation_diagnostics(False)
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        other_cid = "%s_impersonation_other_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        other_segment_id = "%s_impersonation_other_segment" % self.test_id
        self.db.execute(
            "insert into companies (id, cid, data) values (%s, %s, %s)",
            other_cid,
            other_cid,
            {"admin": False, "name": "Other impersonation account"},
        )
        self.db.execute(
            "insert into segments (id, cid, data) values (%s, %s, %s)",
            other_segment_id,
            other_cid,
            {"name": "Other impersonation segment", "parts": []},
        )
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            "%s_impersonation_other_automation" % self.test_id,
            other_cid,
            {
                "name": "Other impersonation automation",
                "status": "published",
                "published": {
                    "entry": {"type": "segment_entered", "segment_id": other_segment_id},
                    "nodes": [{"id": "node_exit_1", "type": "exit", "label": "Exit"}],
                },
            },
        )

        result = self.simulate_get(
            "/api/automation-segment-trigger-status",
            headers=self.admin_impersonation_headers(),
        )

        self.assertEqual(result.status_code, 200, result.text)
        segment_ids = [row["segment_id"] for row in result.json["segments"]]
        self.assertIn(segment["id"], segment_ids)
        self.assertNotIn(other_segment_id, segment_ids)

    def test_segment_trigger_status_includes_multi_and_ignores_draft_unpublished(self):
        self.set_customer_automation_diagnostics(True)
        included = self.create_segment()
        draft_only = self.create_segment()
        unpublished = self.create_segment()
        self.create_automation({
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "%s_tag" % self.test_id},
                {"type": "segment_left", "segment_id": included["id"]},
            ],
        })
        self.create_automation({"type": "segment_entered", "segment_id": draft_only["id"]}, publish=False)
        automation = self.create_automation({"type": "manual"}, publish=False)
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json={
                "entry": {"type": "segment_entered", "segment_id": unpublished["id"]},
                "draft": {"nodes": [{"id": "node_exit_1", "type": "exit", "label": "Exit"}]},
            },
        )

        result = self.user_get("/api/automation-segment-trigger-status")

        segment_ids = [row["segment_id"] for row in result["segments"]]
        self.assertEqual(segment_ids, [included["id"]])
        self.assertEqual(result["segments"][0]["referenced_by"][0]["trigger_type"], "segment_left")

    def test_segment_trigger_status_is_account_scoped_and_limited(self):
        self.set_customer_automation_diagnostics(True)
        first = self.create_segment()
        second = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": first["id"]})
        self.create_automation({"type": "segment_left", "segment_id": second["id"]})
        other_cid = "%s_status_other_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        other_segment_id = "%s_status_other_segment" % self.test_id
        self.db.execute(
            "insert into companies (id, cid, data) values (%s, %s, %s)",
            other_cid,
            other_cid,
            {"admin": False, "name": "Other status account"},
        )
        self.db.execute(
            "insert into segments (id, cid, data) values (%s, %s, %s)",
            other_segment_id,
            other_cid,
            {"name": "Other status segment", "parts": []},
        )
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            "%s_status_other_automation" % self.test_id,
            other_cid,
            {
                "name": "Other status automation",
                "status": "published",
                "published": {
                    "entry": {"type": "segment_entered", "segment_id": other_segment_id},
                    "nodes": [{"id": "node_exit_1", "type": "exit", "label": "Exit"}],
                },
            },
        )
        self.insert_segment_trigger_event(other_segment_id, "segment_entered", 999, cid=other_cid)

        result = self.user_get("/api/automation-segment-trigger-status?limit=1")
        capped = self.user_get("/api/automation-segment-trigger-status?limit=999")

        self.assertEqual(result["limit"], 1)
        self.assertEqual(capped["limit"], 100)
        self.assertEqual(result["summary"]["referenced_segments"], 2)
        self.assertEqual(result["summary"]["returned_segments"], 1)
        self.assertEqual(len(result["segments"]), 1)
        self.assertNotEqual(result["segments"][0]["segment_id"], other_segment_id)

    def test_baseline_task_path(self):
        self.enable_baseline()
        lst = self.create_contact_list()
        email, _ = self.add_contact(lst["id"])
        segment = self.create_segment(prefix=email)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})

        result = self.scan_task("baseline", segment["id"])

        self.assertTrue(result["enabled"])
        self.assertEqual(result["segments_seen"], 1)
        self.assertEqual(result["segments_claimed"], 1)
        self.assertEqual(result["events_created"], 0)
        self.assertEqual(self.member_count(segment["id"]), 1)

    def test_diff_task_path(self):
        self.enable_baseline()
        self.enable_diff()
        lst = self.create_contact_list()
        segment = self.create_segment(prefix=self.test_id)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])
        self.add_contact(lst["id"])

        result = self.scan_task("diff", segment["id"])

        self.assertTrue(result["enabled"])
        self.assertEqual(result["mode"], "diff")
        self.assertEqual(result["events_created"], 1)
        self.assertEqual(len(self.segment_trigger_events(segment["id"])), 1)

    def test_task_respects_baseline_flag_off(self):
        segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})

        result = self.scan_task("baseline", segment["id"])

        self.assertFalse(result["enabled"])
        self.assertEqual(result["events_created"], 0)
        self.assertIsNone(self.snapshot(segment["id"]))

    def test_task_respects_diff_flag_off(self):
        self.enable_baseline()
        lst = self.create_contact_list()
        email, _ = self.add_contact(lst["id"])
        segment = self.create_segment(prefix=email)
        self.create_automation({"type": "segment_entered", "segment_id": segment["id"]})
        self.baseline(segment_id=segment["id"])

        result = self.scan_task("diff", segment["id"])

        self.assertFalse(result["enabled"])
        self.assertEqual(result["events_created"], 0)

    def test_task_normalizes_and_caps_limits(self):
        self.enable_baseline()
        self.enable_diff()
        lst = self.create_contact_list()
        first_segment = self.create_segment(prefix="%s_one" % self.test_id)
        second_segment = self.create_segment(prefix="%s_two" % self.test_id)
        self.create_automation({"type": "segment_entered", "segment_id": first_segment["id"]})
        self.create_automation({"type": "segment_entered", "segment_id": second_segment["id"]})
        self.add_contact(lst["id"], "%s_one@example.com" % self.test_id)
        self.add_contact(lst["id"], "%s_two@example.com" % self.test_id)

        baseline = self.scan_task("baseline", None, 1, 10000)
        self.assertEqual(baseline["segments_seen"], 2)
        self.assertEqual(baseline["segments_claimed"], 1)

        segment_id = self.snapshot_segment_ids()[0]
        self.add_contact(lst["id"], "%s_extra@example.com" % self.test_id)
        diff = self.scan_task("diff", segment_id, 10, 10000, 10000)
        self.assertLessEqual(diff["buckets_processed"], automations.AUTOMATION_SEGMENT_BASELINE_MAX_BUCKET_LIMIT)
        self.assertLessEqual(diff["events_created"], automations.AUTOMATION_SEGMENT_DIFF_MAX_EVENT_LIMIT)

    def test_task_invalid_mode_fails_clearly(self):
        result = self.scan_task("sideways")

        self.assertFalse(result["enabled"])
        self.assertEqual(result["mode"], "sideways")
        self.assertEqual(result["events_created"], 0)
        self.assertEqual(result["errors"][0]["title"], "Invalid automation segment trigger scan mode")

    def test_task_segment_id_scoping(self):
        self.enable_baseline()
        first_segment = self.create_segment()
        second_segment = self.create_segment()
        self.create_automation({"type": "segment_entered", "segment_id": first_segment["id"]})
        self.create_automation({"type": "segment_entered", "segment_id": second_segment["id"]})

        result = self.scan_task("baseline", second_segment["id"])

        self.assertEqual(result["segments_seen"], 1)
        self.assertIsNone(self.snapshot(first_segment["id"]))
        self.assertIsNotNone(self.snapshot(second_segment["id"]))

    def test_segment_scheduler_flags_off_no_dispatch(self):
        self.create_scheduler_account()

        result, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertFalse(result["enabled"])
        self.assertEqual(result["dispatched"], 0)
        self.assertEqual(dispatched, [])

    def test_segment_scheduler_baseline_flag_dispatches_for_missing_baseline(self):
        self.enable_baseline()
        cid, _, _ = self.create_scheduler_account()

        result, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertTrue(result["enabled"])
        self.assertEqual(result["baseline_dispatched"], 1)
        self.assertEqual(result["diff_dispatched"], 0)
        self.assertEqual(dispatched[0]["task"], automations.process_automation_segment_triggers_task)
        self.assertEqual(dispatched[0]["cid"], cid)
        self.assertEqual(dispatched[0]["mode"], "baseline")
        self.assertIsNone(dispatched[0]["segment_id"])
        self.assertEqual(dispatched[0]["limit_segments"], automations.AUTOMATION_SEGMENT_BASELINE_DEFAULT_SEGMENT_LIMIT)
        self.assertEqual(dispatched[0]["limit_buckets"], automations.AUTOMATION_SEGMENT_BASELINE_DEFAULT_BUCKET_LIMIT)
        self.assertEqual(dispatched[0]["limit_events"], automations.AUTOMATION_SEGMENT_DIFF_DEFAULT_EVENT_LIMIT)

    def test_segment_scheduler_baseline_flag_dispatches_for_incomplete_baseline(self):
        self.enable_baseline()
        cid, _, _ = self.create_scheduler_account(baseline_complete=False)

        _, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["cid"], cid)
        self.assertEqual(dispatched[0]["mode"], "baseline")

    def test_segment_scheduler_diff_flag_does_not_dispatch_without_completed_baseline(self):
        self.enable_diff()
        self.create_scheduler_account()

        result, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertEqual(result["dispatched"], 0)
        self.assertEqual(dispatched, [])

    def test_segment_scheduler_diff_flag_dispatches_for_completed_baseline(self):
        self.enable_diff()
        cid, _, _ = self.create_scheduler_account(baseline_complete=True)

        result, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertEqual(result["baseline_dispatched"], 0)
        self.assertEqual(result["diff_dispatched"], 1)
        self.assertEqual(dispatched[0]["cid"], cid)
        self.assertEqual(dispatched[0]["mode"], "diff")

    def test_segment_scheduler_both_flags_choose_baseline_first(self):
        self.enable_baseline()
        self.enable_diff()
        cid, _, _ = self.create_scheduler_account(baseline_complete=False)

        result, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertEqual(result["baseline_dispatched"], 1)
        self.assertEqual(result["diff_dispatched"], 0)
        self.assertEqual(dispatched[0]["cid"], cid)
        self.assertEqual(dispatched[0]["mode"], "baseline")

    def test_segment_scheduler_ignores_customer_processing_disabled(self):
        self.enable_baseline()
        self.create_scheduler_account(automation_processing_enabled=False)

        result, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertEqual(result["dispatched"], 0)
        self.assertEqual(dispatched, [])

    def test_segment_scheduler_ignores_draft_and_unpublished_but_includes_paused(self):
        self.enable_baseline()
        self.create_scheduler_account(published=False)
        cid, _, _ = self.create_scheduler_account(paused=True)

        result, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertEqual(result["dispatched"], 1)
        self.assertEqual(dispatched[0]["cid"], cid)

    def test_segment_scheduler_discovers_multi_entry_trigger(self):
        self.enable_baseline()
        cid, _, _ = self.create_scheduler_account(
            entry=lambda segment_id: {
                "type": "multi",
                "triggers": [
                    {"type": "tag_added", "tag": "%s_tag" % self.test_id},
                    {"type": "segment_left", "segment_id": segment_id},
                ],
            }
        )

        result, dispatched = self.run_segment_scheduler_with_task_patch()

        self.assertEqual(result["dispatched"], 1)
        self.assertEqual(dispatched[0]["cid"], cid)
        self.assertEqual(dispatched[0]["mode"], "baseline")

    def test_segment_scheduler_account_cap_enforced(self):
        self.enable_baseline()
        original_limit = os.environ.get("automation_segment_trigger_account_limit")
        os.environ["automation_segment_trigger_account_limit"] = "1"
        try:
            self.create_scheduler_account()
            self.create_scheduler_account()
            result, dispatched = self.run_segment_scheduler_with_task_patch()
        finally:
            if original_limit is None:
                os.environ.pop("automation_segment_trigger_account_limit", None)
            else:
                os.environ["automation_segment_trigger_account_limit"] = original_limit

        self.assertEqual(result["account_limit"], 1)
        self.assertEqual(result["dispatched"], 1)
        self.assertEqual(len(dispatched), 1)

    def test_segment_scheduler_advisory_lock_prevents_overlap(self):
        self.enable_baseline()
        self.create_scheduler_account()
        lock_conn = psycopg2.connect(os.environ["postgres_conn"])
        lock_conn.autocommit = False
        lock_cur = lock_conn.cursor()
        lock_cur.execute(
            "select pg_advisory_xact_lock(%s::bigint)",
            (automations.CHECK_AUTOMATION_SEGMENT_TRIGGERS_LOCK,),
        )
        try:
            result, dispatched = self.run_segment_scheduler_with_task_patch()
        finally:
            lock_conn.rollback()
            lock_cur.close()
            lock_conn.close()

        self.assertTrue(result["locked"])
        self.assertEqual(result["dispatched"], 0)
        self.assertEqual(dispatched, [])

    def test_segment_scan_scheduler_cron_registration(self):
        crontab_path = os.path.join(os.path.dirname(__file__), "..", "config", "crontab")
        with open(crontab_path) as fp:
            lines = [
                line.strip()
                for line in fp.readlines()
                if "check_automation_segment_triggers" in line
            ]

        self.assertEqual(lines, [
            "*/5 * * * * /scripts/cron.py api.automations check_automation_segment_triggers 26",
        ])
