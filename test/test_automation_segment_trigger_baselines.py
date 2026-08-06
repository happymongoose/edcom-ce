import os
import shortuuid
from datetime import datetime, timedelta

import test_base
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
        self.original_env = {
            "automation_segment_trigger_baseline_enabled": os.environ.get("automation_segment_trigger_baseline_enabled"),
        }
        self.original_hashlimit = self.db.single(
            "select hashlimit from contacts.contacts_hashlimit where cid = %s",
            self.user_cookie["cid"],
        )
        os.environ.pop("automation_segment_trigger_baseline_enabled", None)

    def tearDown(self):
        cid = self.user_cookie["cid"]
        if self.created_segment_ids:
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
        super(TestAutomationSegmentTriggerBaselines, self).tearDown()

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def enable_baseline(self):
        os.environ["automation_segment_trigger_baseline_enabled"] = "true"

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

    def baseline(self, **doc):
        return self.user_post("/api/automation-segment-trigger-baselines", json=doc)

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
