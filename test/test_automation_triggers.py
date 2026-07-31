import os
import shortuuid
from datetime import datetime, timedelta

import test_base
from api.shared import contacts
from api.migrations import add_automation_trigger_events_table


class TestAutomationTriggers(test_base.TestBase):

    def setUp(self):
        super(TestAutomationTriggers, self).setUp()
        add_automation_trigger_events_table.run(self.db)
        self.test_id = "automation_trigger_%s" % shortuuid.uuid().lower()
        self.created_automation_ids = []
        self.created_list_ids = []
        self.created_emails = []
        self.created_other_cids = []
        self.original_env = {
            "automation_triggers_enabled": os.environ.get("automation_triggers_enabled"),
            "automation_trigger_emission_enabled": os.environ.get("automation_trigger_emission_enabled"),
            "automation_trigger_manual_events_enabled": os.environ.get("automation_trigger_manual_events_enabled"),
            "automation_trigger_max_depth": os.environ.get("automation_trigger_max_depth"),
            "automation_trigger_cooldown_minutes": os.environ.get("automation_trigger_cooldown_minutes"),
        }
        for key in self.original_env:
            os.environ.pop(key, None)

    def tearDown(self):
        cid = self.user_cookie["cid"]
        self.db.execute(
            "delete from automation_trigger_events where cid = %s and data->>'correlation_id' like %s",
            cid,
            "%s%%" % self.test_id,
        )
        self.db.execute(
            "delete from alltags where cid = %s and tag like %s",
            cid,
            "%s%%" % self.test_id,
        )
        if self.created_other_cids:
            self.db.execute(
                "delete from automation_trigger_events where cid = any(%s)",
                self.created_other_cids,
            )
            self.db.execute(
                "delete from automation_enrolments where cid = any(%s)",
                self.created_other_cids,
            )
            self.db.execute(
                "delete from automations where cid = any(%s)",
                self.created_other_cids,
            )
        if self.created_automation_ids:
            self.db.execute(
                "delete from automation_step_runs where automation_id = any(%s)",
                self.created_automation_ids,
            )
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
                    "delete from automation_trigger_events where cid = %s and contact_id = any(%s)",
                    cid,
                    contact_ids,
                )
                self.db.execute(
                    "delete from automation_enrolments where cid = %s and contact_id = any(%s)",
                    cid,
                    contact_ids,
                )
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
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        super(TestAutomationTriggers, self).tearDown()

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def enable_manual_events(self):
        os.environ["automation_trigger_manual_events_enabled"] = "true"

    def enable_processing(self):
        os.environ["automation_triggers_enabled"] = "true"

    def enable_emission(self):
        os.environ["automation_trigger_emission_enabled"] = "true"

    def create_contact(self):
        suffix = self.unique()
        email = "automation-trigger-%s@example.com" % suffix
        lst = self.user_post(
            "/api/lists",
            json={"name": "automation_trigger_%s" % suffix},
        )
        self.created_list_ids.append(lst["id"])
        self.created_emails.append(email)
        self.user_post(
            "/api/lists/%s/feed" % lst["id"],
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

    def workflow(self, tag, reentry="once"):
        return {
            "entry": {
                "type": "tag_added",
                "tag": tag,
            },
            "reentry": reentry,
            "draft": {
                "nodes": [
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

    def add_tag_workflow(self, add_tag, entry_type="manual", entry_tag=None, reentry="once"):
        entry = {"type": "manual"}
        if entry_type == "tag_added":
            entry = {
                "type": "tag_added",
                "tag": entry_tag or add_tag,
            }
        return {
            "entry": entry,
            "reentry": reentry,
            "draft": {
                "nodes": [
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": "Add tag",
                        "draft_tag": add_tag,
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

    def create_automation(self, tag, reentry="once", paused=False):
        automation = self.user_post(
            "/api/automations",
            json={"name": "%s_automation_%s" % (self.test_id, self.unique())},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(tag, reentry),
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(published.status_code, 200)
        if paused:
            paused_result = self.simulate_post(
                "/api/automations/%s/pause" % automation["id"],
                headers=self.headers(),
            )
            self.assertEqual(paused_result.status_code, 200)
            return paused_result.json
        return published.json

    def create_add_tag_automation(self, add_tag, entry_type="manual", entry_tag=None):
        automation = self.user_post(
            "/api/automations",
            json={"name": "%s_add_tag_automation_%s" % (self.test_id, self.unique())},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.add_tag_workflow(add_tag, entry_type, entry_tag),
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(published.status_code, 200)
        return published.json

    def create_event(self, email, tag, **overrides):
        doc = {
            "event_type": "tag_added",
            "contact_email": email,
            "tag": tag,
            "correlation_id": "%s_%s" % (self.test_id, self.unique()),
        }
        doc.update(overrides)
        return self.user_post("/api/automation-trigger-events", json=doc)

    def process_events(self, limit=25):
        return self.user_post("/api/automation-trigger-events/process", json={"limit": limit})

    def run_next(self, automation_id, enrolment_id):
        return self.simulate_post(
            "/api/automations/%s/enrolments/%s/run-next" % (automation_id, enrolment_id),
            headers=self.headers(),
        )

    def add_contact_tag(self, email, contact_id, tag, **kwargs):
        webhook_msgs = []
        contacts.update_tags(
            self.db,
            self.user_cookie["cid"],
            [email],
            [tag],
            webhook_msgs,
            [(email, contact_id)],
            **kwargs
        )

    def emitted_events(self, tag):
        return self.db.execute(
            """
            select id, data
            from automation_trigger_events
            where cid = %s and event_type = 'tag_added' and data->>'tag' = %s
            order by ts, id
            """,
            self.user_cookie["cid"],
            tag,
        ).fetchall()

    def enrolment_rows(self, automation_id):
        return self.db.execute(
            """
            select id, data
            from automation_enrolments
            where cid = %s and automation_id = %s
            order by data->>'created', id
            """,
            self.user_cookie["cid"],
            automation_id,
        ).fetchall()

    def patch_enrolment_status(self, enrolment_id, status):
        self.db.execute(
            """
            update automation_enrolments
            set data = data || jsonb_build_object('status', %s)
            where cid = %s and id = %s
            """,
            status,
            self.user_cookie["cid"],
            enrolment_id,
        )

    def event_status(self, event_id):
        return self.db.single(
            "select data->>'status' from automation_trigger_events where cid = %s and id = %s",
            self.user_cookie["cid"],
            event_id,
        )

    def event_data(self, event_id):
        return self.db.single(
            "select data from automation_trigger_events where cid = %s and id = %s",
            self.user_cookie["cid"],
            event_id,
        )

    def test_manual_event_insertion_disabled_by_default(self):
        email, _ = self.create_contact()
        result = self.simulate_post(
            "/api/automation-trigger-events",
            json={
                "event_type": "tag_added",
                "contact_email": email,
                "tag": "vip",
            },
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)

    def test_manual_event_insertion_works_only_when_enabled(self):
        self.enable_manual_events()
        email, contact_id = self.create_contact()

        event = self.create_event(email, " VIP!!! ")

        self.assertEqual(event["event_type"], "tag_added")
        self.assertEqual(event["contact_id"], contact_id)
        self.assertEqual(event["tag"], "vip")
        self.assertEqual(event["status"], "pending")
        self.assertEqual(event["source"]["type"], "manual")

    def test_processor_disabled_by_default(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        event = self.create_event(email, "processor-disabled")

        result = self.process_events()

        self.assertEqual(result["enabled"], False)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(self.event_status(event["id"]), "pending")

    def test_enabled_processor_enrols_matching_published_automation(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_match" % self.test_id
        automation = self.create_automation(tag)
        event = self.create_event(email, tag)

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["status"], "ready")
        self.assertEqual(rows[0][1]["source"], "trigger:%s" % event["id"])
        self.assertEqual(self.event_status(event["id"]), "processed")

    def test_emission_flag_off_does_not_create_event_even_with_match(self):
        email, contact_id = self.create_contact()
        tag = "%s_emit_off" % self.test_id
        self.create_automation(tag)

        self.add_contact_tag(email, contact_id, tag)

        self.assertEqual(len(self.emitted_events(tag)), 0)

    def test_emission_enabled_without_matching_automation_does_not_create_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_no_emit_match" % self.test_id

        self.add_contact_tag(email, contact_id, tag)

        self.assertEqual(len(self.emitted_events(tag)), 0)

    def test_matching_published_automation_creates_pending_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_emit_published" % self.test_id
        self.create_automation(tag)

        self.add_contact_tag(email, contact_id, tag)

        events = self.emitted_events(tag)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["status"], "pending")
        self.assertEqual(events[0][1]["source"]["type"], "manual")
        self.assertEqual(events[0][1]["depth"], 0)

    def test_matching_paused_automation_creates_pending_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_emit_paused" % self.test_id
        self.create_automation(tag, paused=True)

        self.add_contact_tag(email, contact_id, tag)

        events = self.emitted_events(tag)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["status"], "pending")

    def test_idempotent_second_tag_add_does_not_create_second_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_emit_once" % self.test_id
        self.create_automation(tag)

        self.add_contact_tag(email, contact_id, tag)
        self.add_contact_tag(email, contact_id, tag)

        self.assertEqual(len(self.emitted_events(tag)), 1)

    def test_processing_emitted_event_creates_enrolment_with_correlation_data(self):
        self.enable_emission()
        self.enable_processing()
        email, contact_id = self.create_contact()
        tag = "%s_emit_process" % self.test_id
        automation = self.create_automation(tag)

        self.add_contact_tag(email, contact_id, tag)
        events = self.emitted_events(tag)
        result = self.process_events()

        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["trigger_correlation_id"], events[0][1]["correlation_id"])
        self.assertEqual(rows[0][1]["trigger_depth"], 0)

    def test_automation_add_tag_emits_source_metadata_when_another_automation_matches(self):
        self.enable_emission()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_automation_source" % self.test_id
        source_automation = self.create_add_tag_automation(tag)
        target_automation = self.create_automation(tag, reentry="multiple")
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        self.assertEqual(run.status_code, 200)
        events = self.emitted_events(tag)
        self.assertEqual(len(events), 1)
        source = events[0][1]["source"]
        self.assertEqual(source["type"], "automation")
        self.assertEqual(source["automation_id"], source_automation["id"])
        self.assertEqual(source["enrolment_id"], enrolment["id"])
        self.assertEqual(source["node_id"], "node_add_tag_1")
        self.assertEqual(source["step_run_id"], run.json["step_run"]["id"])
        self.assertEqual(source["published_revision"], str(source_automation["published_revision"]))

        result = self.process_events()

        self.assertEqual(result["enrolled"], 1)
        self.assertEqual(len(self.enrolment_rows(target_automation["id"])), 1)

    def test_same_automation_source_emitted_event_is_suppressed(self):
        self.enable_emission()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_same_auto_emit" % self.test_id
        automation = self.create_add_tag_automation(tag, "tag_added", tag)
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % automation["id"],
            json={"email": email},
        )

        run = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(run.status_code, 200)
        result = self.process_events()

        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(result["details"][0]["reason"], "same_automation_source")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 1)

    def test_depth_increments_for_automation_caused_event(self):
        self.enable_emission()
        email, _ = self.create_contact()
        tag = "%s_depth_increment" % self.test_id
        source_automation = self.create_add_tag_automation(tag)
        self.create_automation(tag)
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )
        self.patch_enrolment_status(enrolment["id"], "ready")
        self.db.execute(
            """
            update automation_enrolments
            set data = data || jsonb_build_object('trigger_correlation_id', %s, 'trigger_depth', 2)
            where cid = %s and id = %s
            """,
            "%s_existing_correlation" % self.test_id,
            self.user_cookie["cid"],
            enrolment["id"],
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        self.assertEqual(run.status_code, 200)

        events = self.emitted_events(tag)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["correlation_id"], "%s_existing_correlation" % self.test_id)
        self.assertEqual(events[0][1]["depth"], 3)

    def test_source_payload_is_bounded_and_sanitized(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_source_bounds" % self.test_id
        self.create_automation(tag)

        self.add_contact_tag(
            email,
            contact_id,
            tag,
            automation_trigger_source={
                "type": "api",
                "automation_id": "a" * 200,
                "metadata": "x" * 5000,
            },
            automation_trigger_correlation_id="c" * 200,
            automation_trigger_depth=500,
        )

        event = self.emitted_events(tag)[0][1]
        self.assertEqual(event["source"]["type"], "api")
        self.assertEqual(len(event["source"]["automation_id"]), 128)
        self.assertNotIn("metadata", event["source"])
        self.assertEqual(len(event["correlation_id"]), 128)
        self.assertEqual(event["depth"], 100)

    def test_emission_matching_is_current_account_scoped(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_emit_scope" % self.test_id
        other_cid = "%s_emit_other_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            "%s_emit_other_automation" % self.test_id,
            other_cid,
            {
                "name": "%s emit other automation" % self.test_id,
                "status": "published",
                "published": {
                    "entry": {
                        "type": "tag_added",
                        "tag": tag,
                    },
                    "reentry": "once",
                    "nodes": [
                        {
                            "id": "node_exit_1",
                            "type": "exit",
                            "label": "Exit automation",
                        },
                    ],
                },
                "published_revision": 1,
            },
        )

        self.add_contact_tag(email, contact_id, tag)

        self.assertEqual(len(self.emitted_events(tag)), 0)

    def test_paused_automation_creates_held_enrolment(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_paused" % self.test_id
        automation = self.create_automation(tag, paused=True)
        self.create_event(email, tag)

        result = self.process_events()

        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["status"], "held")

    def test_no_match_debug_event_is_processed_without_enrolment(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        event = self.create_event(email, "%s_no_match" % self.test_id)

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 0)
        self.assertEqual(result["no_match"], 1)
        self.assertEqual(self.event_status(event["id"]), "processed")

    def test_same_automation_source_suppresses(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_same_source" % self.test_id
        automation = self.create_automation(tag)
        self.create_event(
            email,
            tag,
            source={
                "type": "automation",
                "automation_id": automation["id"],
            },
        )

        result = self.process_events()

        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(result["details"][0]["reason"], "same_automation_source")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 0)

    def test_active_pass_suppresses(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_active" % self.test_id
        automation = self.create_automation(tag, reentry="multiple")
        self.user_post("/api/automations/%s/enrolments" % automation["id"], json={"email": email})
        self.create_event(email, tag)

        result = self.process_events()

        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(result["details"][0]["reason"], "active_pass")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 1)

    def test_once_suppresses_prior_enrolment(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_once" % self.test_id
        automation = self.create_automation(tag)
        enrolment = self.user_post("/api/automations/%s/enrolments" % automation["id"], json={"email": email})
        self.patch_enrolment_status(enrolment["id"], "completed")
        self.create_event(email, tag)

        result = self.process_events()

        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(result["details"][0]["reason"], "once")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 1)

    def test_multiple_allows_terminal_previous_pass(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_multiple_terminal" % self.test_id
        automation = self.create_automation(tag, reentry="multiple")
        enrolment = self.user_post("/api/automations/%s/enrolments" % automation["id"], json={"email": email})
        self.patch_enrolment_status(enrolment["id"], "completed")
        self.create_event(email, tag)

        result = self.process_events()

        self.assertEqual(result["enrolled"], 1)
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 2)

    def test_depth_guard_suppresses(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_depth" % self.test_id
        automation = self.create_automation(tag)
        self.create_event(email, tag, depth=3)

        result = self.process_events()

        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(result["details"][0]["reason"], "max_depth")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 0)

    def test_cooldown_suppresses_repeat_event(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_cooldown" % self.test_id
        automation = self.create_automation(tag, reentry="multiple")
        self.create_event(email, tag)
        first = self.process_events()
        self.assertEqual(first["enrolled"], 1)
        enrolment_id = self.enrolment_rows(automation["id"])[0][0]
        self.patch_enrolment_status(enrolment_id, "completed")

        self.create_event(email, tag)
        second = self.process_events()

        self.assertEqual(second["suppressed"], 1)
        self.assertEqual(second["details"][0]["reason"], "cooldown")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 1)

    def test_current_account_scoping_for_matching(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_scope" % self.test_id
        other_cid = "%s_other_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            "%s_other_automation" % self.test_id,
            other_cid,
            {
                "name": "%s other automation" % self.test_id,
                "status": "published",
                "published": self.workflow(tag)["draft"] | {
                    "entry": {
                        "type": "tag_added",
                        "tag": tag,
                    },
                    "reentry": "once",
                },
                "published_revision": 1,
            },
        )
        self.create_event(email, tag)

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 0)
        self.assertEqual(result["no_match"], 1)

    def test_capped_details_and_errors(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_errors" % self.test_id
        for index in range(105):
            automation_id = "%s_error_%s" % (self.test_id, index)
            self.created_automation_ids.append(automation_id)
            self.db.execute(
                "insert into automations (id, cid, data) values (%s, %s, %s)",
                automation_id,
                self.user_cookie["cid"],
                {
                    "name": "%s error %s" % (self.test_id, index),
                    "status": "published",
                    "published": {
                        "entry": {
                            "type": "tag_added",
                            "tag": tag,
                        },
                        "reentry": "once",
                        "nodes": [],
                    },
                    "published_revision": 1,
                },
            )
        self.create_event(email, tag)

        result = self.process_events()

        self.assertEqual(result["failed"], 105)
        self.assertEqual(len(result["errors"]), 100)

    def test_already_claimed_event_is_not_processed_again(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        event = self.create_event(email, "%s_claimed" % self.test_id)
        self.db.execute(
            """
            update automation_trigger_events
            set data = data || jsonb_build_object('status', 'processing', 'claimed_at', %s)
            where cid = %s and id = %s
            """,
            datetime.utcnow().isoformat() + "Z",
            self.user_cookie["cid"],
            event["id"],
        )

        result = self.process_events()

        self.assertEqual(result["processed"], 0)
        self.assertEqual(self.event_status(event["id"]), "processing")

    def test_non_stale_processing_event_is_not_recovered(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_non_stale" % self.test_id
        automation = self.create_automation(tag)
        event = self.create_event(email, tag)
        self.db.execute(
            """
            update automation_trigger_events
            set data = data || jsonb_build_object('status', 'processing', 'claimed_at', %s)
            where cid = %s and id = %s
            """,
            datetime.utcnow().isoformat() + "Z",
            self.user_cookie["cid"],
            event["id"],
        )

        result = self.process_events()

        self.assertEqual(result["processed"], 0)
        self.assertEqual(self.event_status(event["id"]), "processing")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 0)

    def test_stale_processing_event_is_reclaimed_and_processed(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_stale" % self.test_id
        automation = self.create_automation(tag)
        event = self.create_event(email, tag)
        stale_claimed_at = (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z"
        self.db.execute(
            """
            update automation_trigger_events
            set data = data || jsonb_build_object('status', 'processing', 'claimed_at', %s)
            where cid = %s and id = %s
            """,
            stale_claimed_at,
            self.user_cookie["cid"],
            event["id"],
        )

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 1)
        self.assertEqual(self.event_status(event["id"]), "processed")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 1)
        data = self.event_data(event["id"])
        self.assertEqual(data["recovery_count"], 1)
        self.assertTrue(data.get("recovered_at"))

    def test_stale_recovery_is_account_scoped(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_stale_scope" % self.test_id
        automation = self.create_automation(tag)
        event = self.create_event(email, tag)
        other_cid = "%s_other_stale_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        self.db.execute(
            """
            update automation_trigger_events
            set cid = %s,
                data = data || jsonb_build_object('status', 'processing', 'claimed_at', %s)
            where cid = %s and id = %s
            """,
            other_cid,
            (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z",
            self.user_cookie["cid"],
            event["id"],
        )

        result = self.process_events()

        self.assertEqual(result["processed"], 0)
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 0)
        self.assertEqual(
            self.db.single(
                "select data->>'status' from automation_trigger_events where cid = %s and id = %s",
                other_cid,
                event["id"],
            ),
            "processing",
        )

    def test_recovered_event_does_not_duplicate_existing_enrolment(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_stale_existing" % self.test_id
        automation = self.create_automation(tag, reentry="multiple")
        existing = self.user_post("/api/automations/%s/enrolments" % automation["id"], json={"email": email})
        event = self.create_event(email, tag)
        self.db.execute(
            """
            update automation_trigger_events
            set data = data || jsonb_build_object('status', 'processing', 'claimed_at', %s)
            where cid = %s and id = %s
            """,
            (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z",
            self.user_cookie["cid"],
            event["id"],
        )

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(result["details"][0]["reason"], "active_pass")
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], existing["id"])
        data = self.event_data(event["id"])
        self.assertEqual(data["recovery_count"], 1)
