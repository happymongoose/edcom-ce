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
        company = self.db.companies.get(self.user_cookie["cid"])
        self.original_automation_diagnostics_visible = company.get("automation_diagnostics_visible")
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
            "update companies set data = data - 'automation_diagnostics_visible' where id = %s",
            cid,
        )
        if self.original_automation_diagnostics_visible is not None:
            self.db.execute(
                "update companies set data = data || %s where id = %s",
                {"automation_diagnostics_visible": self.original_automation_diagnostics_visible},
                cid,
            )
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

    def create_contact_list(self, name=None):
        lst = self.user_post(
            "/api/lists",
            json={"name": name or "automation_trigger_list_%s" % self.unique()},
        )
        self.created_list_ids.append(lst["id"])
        return lst

    def workflow(self, tag, reentry="once", entry_type="tag_added"):
        return {
            "entry": {
                "type": entry_type,
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

    def list_workflow(self, list_id, reentry="once", entry_type="list_joined"):
        return {
            "entry": {
                "type": entry_type,
                "list_id": list_id,
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

    def remove_tag_workflow(self, remove_tag, entry_type="manual", entry_tag=None, reentry="once"):
        entry = {"type": "manual"}
        if entry_type in ("tag_added", "tag_removed"):
            entry = {
                "type": entry_type,
                "tag": entry_tag or remove_tag,
            }
        return {
            "entry": entry,
            "reentry": reentry,
            "draft": {
                "nodes": [
                    {
                        "id": "node_remove_tag_1",
                        "type": "remove_tag",
                        "label": "Remove tag",
                        "draft_tag": remove_tag,
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

    def add_to_list_workflow(self, list_id, entry_type="manual", entry_list_id=None, reentry="once"):
        entry = {"type": "manual"}
        if entry_type in ("list_joined", "list_left"):
            entry = {
                "type": entry_type,
                "list_id": entry_list_id or list_id,
            }
        return {
            "entry": entry,
            "reentry": reentry,
            "draft": {
                "nodes": [
                    {
                        "id": "node_add_to_list_1",
                        "type": "add_to_list",
                        "label": "Add to list",
                        "list_id": list_id,
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

    def remove_from_list_workflow(self, list_id, entry_type="manual", entry_list_id=None, reentry="once"):
        entry = {"type": "manual"}
        if entry_type in ("list_joined", "list_left"):
            entry = {
                "type": entry_type,
                "list_id": entry_list_id or list_id,
            }
        return {
            "entry": entry,
            "reentry": reentry,
            "draft": {
                "nodes": [
                    {
                        "id": "node_remove_from_list_1",
                        "type": "remove_from_list",
                        "label": "Remove from list",
                        "list_id": list_id,
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

    def create_automation(self, tag, reentry="once", paused=False, entry_type="tag_added"):
        automation = self.user_post(
            "/api/automations",
            json={"name": "%s_automation_%s" % (self.test_id, self.unique())},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(tag, reentry, entry_type),
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

    def create_list_trigger_automation(self, list_id, reentry="once", paused=False, entry_type="list_joined"):
        automation = self.user_post(
            "/api/automations",
            json={"name": "%s_list_automation_%s" % (self.test_id, self.unique())},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.list_workflow(list_id, reentry, entry_type),
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

    def create_remove_tag_automation(self, remove_tag, entry_type="manual", entry_tag=None):
        automation = self.user_post(
            "/api/automations",
            json={"name": "%s_remove_tag_automation_%s" % (self.test_id, self.unique())},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.remove_tag_workflow(remove_tag, entry_type, entry_tag),
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(published.status_code, 200)
        return published.json

    def create_add_to_list_automation(self, list_id, entry_type="manual", entry_list_id=None):
        automation = self.user_post(
            "/api/automations",
            json={"name": "%s_add_to_list_automation_%s" % (self.test_id, self.unique())},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.add_to_list_workflow(list_id, entry_type, entry_list_id),
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(published.status_code, 200)
        return published.json

    def create_remove_from_list_automation(self, list_id, entry_type="manual", entry_list_id=None):
        automation = self.user_post(
            "/api/automations",
            json={"name": "%s_remove_from_list_automation_%s" % (self.test_id, self.unique())},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.remove_from_list_workflow(list_id, entry_type, entry_list_id),
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

    def create_list_event(self, email, list_id, event_type="list_joined", **overrides):
        doc = {
            "event_type": event_type,
            "contact_email": email,
            "list_id": list_id,
            "correlation_id": "%s_%s" % (self.test_id, self.unique()),
        }
        doc.update(overrides)
        return self.user_post("/api/automation-trigger-events", json=doc)

    def process_events(self, limit=25):
        return self.user_post("/api/automation-trigger-events/process", json={"limit": limit})

    def list_events(self, limit=None):
        self.set_automation_diagnostics_visible(True)
        path = "/api/automation-trigger-events"
        if limit is not None:
            path += "?limit=%s" % limit
        return self.user_get(path)

    def set_automation_diagnostics_visible(self, visible):
        self.db.execute(
            "update companies set data = data || %s where id = %s",
            {"automation_diagnostics_visible": visible},
            self.user_cookie["cid"],
        )

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

    def emitted_events(self, tag, event_type="tag_added"):
        return self.db.execute(
            """
            select id, data
            from automation_trigger_events
            where cid = %s and event_type = %s and data->>'tag' = %s
            order by ts, id
            """,
            self.user_cookie["cid"],
            event_type,
            tag,
        ).fetchall()

    def emitted_list_events(self, list_id, event_type="list_joined"):
        return self.db.execute(
            """
            select id, data
            from automation_trigger_events
            where cid = %s and event_type = %s and data->>'list_id' = %s
            order by ts, id
            """,
            self.user_cookie["cid"],
            event_type,
            list_id,
        ).fetchall()

    def add_contact_to_list_row(self, contact_id, list_id):
        self.db.execute(
            f"""
            insert into contacts."contact_lists_{self.user_cookie['cid']}" (contact_id, list_id)
            values (%s, %s)
            on conflict (contact_id, list_id) do nothing
            """,
            contact_id,
            list_id,
        )

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

    def test_trigger_event_list_is_current_account_scoped(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        visible = self.create_event(email, "%s_list_scope_visible" % self.test_id)
        hidden = self.create_event(email, "%s_list_scope_hidden" % self.test_id)
        other_cid = "%s_list_other_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        self.db.execute(
            "update automation_trigger_events set cid = %s where cid = %s and id = %s",
            other_cid,
            self.user_cookie["cid"],
            hidden["id"],
        )

        events = self.list_events()["events"]
        event_ids = [event["id"] for event in events]

        self.assertIn(visible["id"], event_ids)
        self.assertNotIn(hidden["id"], event_ids)

    def test_trigger_event_list_is_hidden_when_customer_diagnostics_disabled(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        self.create_event(email, "%s_list_hidden" % self.test_id)
        self.set_automation_diagnostics_visible(False)

        result = self.simulate_get(
            "/api/automation-trigger-events",
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)
        self.assertIn("Automation diagnostics are not enabled", result.text)

    def test_trigger_event_list_is_newest_first(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        older = self.create_event(email, "%s_list_older" % self.test_id)
        newer = self.create_event(email, "%s_list_newer" % self.test_id)
        self.db.execute(
            "update automation_trigger_events set ts = %s where cid = %s and id = %s",
            datetime(2099, 1, 1, 12, 0, 0),
            self.user_cookie["cid"],
            older["id"],
        )
        self.db.execute(
            "update automation_trigger_events set ts = %s where cid = %s and id = %s",
            datetime(2099, 1, 1, 13, 0, 0),
            self.user_cookie["cid"],
            newer["id"],
        )

        events = self.list_events(limit=2)["events"]

        self.assertEqual(events[0]["id"], newer["id"])
        self.assertEqual(events[1]["id"], older["id"])

    def test_trigger_event_list_default_and_max_limit(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        for index in range(105):
            self.create_event(email, "%s_list_limit_%03d" % (self.test_id, index))

        default_events = self.list_events()["events"]
        max_events = self.list_events(limit=999)["events"]

        self.assertEqual(len(default_events), 50)
        self.assertEqual(len(max_events), 100)

    def test_trigger_event_list_includes_suppressed_reason_and_source_automation_name(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_list_suppressed" % self.test_id
        automation = self.create_automation(tag)
        event = self.create_event(
            email,
            tag,
            source={
                "type": "automation",
                "automation_id": automation["id"],
            },
        )

        result = self.process_events()
        listed = [item for item in self.list_events()["events"] if item["id"] == event["id"]][0]

        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(listed["source_type"], "automation")
        self.assertEqual(listed["source_automation_id"], automation["id"])
        self.assertEqual(listed["source_automation_name"], automation["name"])
        self.assertEqual(listed["results"][0]["status"], "suppressed")
        self.assertEqual(listed["results"][0]["reason"], "same_automation_source")

    def test_trigger_event_list_source_automation_name_is_account_scoped(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        event = self.create_event(email, "%s_list_source_scope" % self.test_id)
        other_cid = "%s_list_source_other_cid" % self.test_id
        other_automation_id = "%s_list_source_other_automation" % self.test_id
        self.created_other_cids.append(other_cid)
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            other_automation_id,
            other_cid,
            {"name": "%s source other" % self.test_id},
        )
        self.db.execute(
            """
            update automation_trigger_events
            set data = data || jsonb_build_object(
                'source',
                jsonb_build_object('type', 'automation', 'automation_id', %s)
            )
            where cid = %s and id = %s
            """,
            other_automation_id,
            self.user_cookie["cid"],
            event["id"],
        )

        listed = [item for item in self.list_events()["events"] if item["id"] == event["id"]][0]

        self.assertEqual(listed["source_automation_id"], other_automation_id)
        self.assertIsNone(listed["source_automation_name"])

    def test_trigger_event_list_does_not_return_raw_oversized_metadata(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        event = self.create_event(email, "%s_list_raw" % self.test_id)
        self.db.execute(
            """
            update automation_trigger_events
            set data = data || %s
            where cid = %s and id = %s
            """,
            {
                "large_metadata": "x" * 5000,
                "source": {
                    "type": "manual",
                    "metadata": "x" * 5000,
                },
                "results": [
                    {
                        "status": "suppressed",
                        "reason": "test",
                        "metadata": "x" * 5000,
                    }
                ],
            },
            self.user_cookie["cid"],
            event["id"],
        )

        listed = [item for item in self.list_events()["events"] if item["id"] == event["id"]][0]

        self.assertNotIn("large_metadata", listed)
        self.assertNotIn("source", listed)
        self.assertNotIn("metadata", listed["results"][0])

    def test_trigger_event_list_projects_list_id_without_raw_metadata(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        event = self.create_list_event(email, lst["id"], "list_joined")
        self.db.execute(
            """
            update automation_trigger_events
            set data = data || %s
            where cid = %s and id = %s
            """,
            {
                "large_metadata": "x" * 5000,
                "results": [
                    {
                        "status": "no_match",
                        "reason": "test",
                        "list_id": lst["id"],
                        "metadata": "x" * 5000,
                    }
                ],
            },
            self.user_cookie["cid"],
            event["id"],
        )

        listed = [item for item in self.list_events()["events"] if item["id"] == event["id"]][0]

        self.assertEqual(listed["list_id"], lst["id"])
        self.assertNotIn("large_metadata", listed)
        self.assertNotIn("metadata", listed["results"][0])
        self.assertEqual(listed["results"][0]["list_id"], lst["id"])

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

    def test_manual_tag_removed_event_insertion_works_when_enabled(self):
        self.enable_manual_events()
        email, contact_id = self.create_contact()

        event = self.create_event(email, "%s_removed_manual" % self.test_id, event_type="tag_removed")

        self.assertEqual(event["event_type"], "tag_removed")
        self.assertEqual(event["contact_id"], contact_id)
        self.assertEqual(event["tag"], "%s_removed_manual" % self.test_id)
        self.assertEqual(event["status"], "pending")

    def test_manual_list_joined_event_insertion_works_when_enabled(self):
        self.enable_manual_events()
        email, contact_id = self.create_contact()
        lst = self.create_contact_list()

        event = self.create_list_event(email, lst["id"], "list_joined")

        self.assertEqual(event["event_type"], "list_joined")
        self.assertEqual(event["contact_id"], contact_id)
        self.assertEqual(event["list_id"], lst["id"])
        self.assertEqual(event["status"], "pending")

    def test_manual_list_left_event_insertion_works_when_enabled(self):
        self.enable_manual_events()
        email, contact_id = self.create_contact()
        lst = self.create_contact_list()

        event = self.create_list_event(email, lst["id"], "list_left")

        self.assertEqual(event["event_type"], "list_left")
        self.assertEqual(event["contact_id"], contact_id)
        self.assertEqual(event["list_id"], lst["id"])
        self.assertEqual(event["status"], "pending")

    def test_manual_list_event_missing_list_id_fails(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        result = self.simulate_post(
            "/api/automation-trigger-events",
            json={
                "event_type": "list_joined",
                "contact_email": email,
            },
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)

    def test_manual_list_event_unknown_or_unowned_list_fails(self):
        self.enable_manual_events()
        email, _ = self.create_contact()
        unknown = self.simulate_post(
            "/api/automation-trigger-events",
            json={
                "event_type": "list_left",
                "contact_email": email,
                "list_id": "missing-list-id",
            },
            headers=self.headers(),
        )
        self.assertEqual(unknown.status_code, 400)

        lst = self.create_contact_list()
        self.db.execute(
            "update lists set cid = %s where id = %s",
            "other-account-cid",
            lst["id"],
        )
        try:
            unowned = self.simulate_post(
                "/api/automation-trigger-events",
                json={
                    "event_type": "list_joined",
                    "contact_email": email,
                    "list_id": lst["id"],
                },
                headers=self.headers(),
            )
            self.assertEqual(unowned.status_code, 400)
        finally:
            self.db.execute(
                "update lists set cid = %s where id = %s",
                self.user_cookie["cid"],
                lst["id"],
            )

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

    def test_enabled_processor_enrols_matching_tag_removed_automation(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_removed_match" % self.test_id
        automation = self.create_automation(tag, entry_type="tag_removed")
        event = self.create_event(email, tag, event_type="tag_removed")

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["status"], "ready")
        self.assertEqual(rows[0][1]["source"], "trigger:%s" % event["id"])
        self.assertEqual(self.event_status(event["id"]), "processed")

    def test_processor_matches_non_first_multi_entry_trigger(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        tag = "%s_multi_second" % self.test_id
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_trigger_%s" % self.unique()},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json={
                "entry": {
                    "type": "multi",
                    "triggers": [
                        {"type": "tag_added", "tag": "%s_other" % tag},
                        {"type": "tag_removed", "tag": tag},
                    ],
                },
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
        automation = self.user_post("/api/automations/%s/publish" % automation["id"])
        event = self.create_event(email, tag, event_type="tag_removed")

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["source"], "trigger:%s" % event["id"])

    def test_enabled_processor_enrols_matching_list_joined_automation(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_list_trigger_automation(lst["id"])
        event = self.create_list_event(email, lst["id"], "list_joined")

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["status"], "ready")
        self.assertEqual(rows[0][1]["source"], "trigger:%s" % event["id"])
        self.assertEqual(self.event_status(event["id"]), "processed")

    def test_enabled_processor_enrols_matching_list_left_automation(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_list_trigger_automation(lst["id"], entry_type="list_left")
        event = self.create_list_event(email, lst["id"], "list_left")

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["status"], "ready")
        self.assertEqual(rows[0][1]["source"], "trigger:%s" % event["id"])
        self.assertEqual(self.event_status(event["id"]), "processed")

    def test_no_match_list_event_is_processed_without_enrolment(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        event = self.create_list_event(email, lst["id"], "list_joined")

        result = self.process_events()

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["enrolled"], 0)
        self.assertEqual(result["no_match"], 1)
        self.assertEqual(self.event_status(event["id"]), "processed")

    def test_tag_removed_emission_flag_off_does_not_create_event_even_with_match(self):
        email, contact_id = self.create_contact()
        tag = "%s_removed_emit_off" % self.test_id
        self.create_automation(tag, entry_type="tag_removed")
        self.add_contact_tag(email, contact_id, tag)

        removed = contacts.remove_tag(
            self.db,
            self.user_cookie["cid"],
            email,
            contact_id,
            tag,
            {},
            [],
        )

        self.assertTrue(removed)
        self.assertEqual(len(self.emitted_events(tag, "tag_removed")), 0)

    def test_tag_removed_noop_does_not_create_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_removed_noop" % self.test_id
        self.create_automation(tag, entry_type="tag_removed")

        removed = contacts.remove_tag(
            self.db,
            self.user_cookie["cid"],
            email,
            contact_id,
            tag,
            {},
            [],
        )

        self.assertFalse(removed)
        self.assertEqual(len(self.emitted_events(tag, "tag_removed")), 0)

    def test_tag_removed_emission_enabled_without_matching_automation_does_not_create_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_removed_no_match" % self.test_id
        self.add_contact_tag(email, contact_id, tag)

        removed = contacts.remove_tag(
            self.db,
            self.user_cookie["cid"],
            email,
            contact_id,
            tag,
            {},
            [],
        )

        self.assertTrue(removed)
        self.assertEqual(len(self.emitted_events(tag, "tag_removed")), 0)

    def test_matching_published_tag_removed_automation_creates_pending_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_removed_emit_published" % self.test_id
        self.create_automation(tag, entry_type="tag_removed")
        self.add_contact_tag(email, contact_id, tag)

        removed = contacts.remove_tag(
            self.db,
            self.user_cookie["cid"],
            email,
            contact_id,
            tag,
            {},
            [],
        )

        events = self.emitted_events(tag, "tag_removed")
        self.assertTrue(removed)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["status"], "pending")
        self.assertEqual(events[0][1]["source"]["type"], "manual")
        self.assertEqual(events[0][1]["depth"], 0)

    def test_tag_emission_finds_matching_multi_entry_trigger(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_multi_emit_tag" % self.test_id
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_trigger_%s" % self.unique()},
        )
        self.created_automation_ids.append(automation["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json={
                "entry": {
                    "type": "multi",
                    "triggers": [
                        {"type": "tag_added", "tag": "%s_other" % tag},
                        {"type": "tag_removed", "tag": tag},
                    ],
                },
                "reentry": "multiple",
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
        self.user_post("/api/automations/%s/publish" % automation["id"])
        self.add_contact_tag(email, contact_id, tag)

        removed = contacts.remove_tag(
            self.db,
            self.user_cookie["cid"],
            email,
            contact_id,
            tag,
            {},
            [],
        )

        self.assertTrue(removed)
        self.assertEqual(len(self.emitted_events(tag, "tag_removed")), 1)

    def test_matching_paused_tag_removed_automation_creates_pending_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_removed_emit_paused" % self.test_id
        self.create_automation(tag, paused=True, entry_type="tag_removed")
        self.add_contact_tag(email, contact_id, tag)

        contacts.remove_tag(
            self.db,
            self.user_cookie["cid"],
            email,
            contact_id,
            tag,
            {},
            [],
        )

        events = self.emitted_events(tag, "tag_removed")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["status"], "pending")

    def test_processing_emitted_tag_removed_event_creates_enrolment(self):
        self.enable_emission()
        self.enable_processing()
        email, contact_id = self.create_contact()
        tag = "%s_removed_emit_process" % self.test_id
        automation = self.create_automation(tag, entry_type="tag_removed")
        self.add_contact_tag(email, contact_id, tag)

        contacts.remove_tag(
            self.db,
            self.user_cookie["cid"],
            email,
            contact_id,
            tag,
            {},
            [],
        )
        events = self.emitted_events(tag, "tag_removed")
        result = self.process_events()

        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["source"], "trigger:%s" % events[0][0])

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

    def test_automation_remove_tag_emits_source_metadata_when_another_automation_matches(self):
        self.enable_emission()
        self.enable_processing()
        email, contact_id = self.create_contact()
        tag = "%s_remove_automation_source" % self.test_id
        self.add_contact_tag(email, contact_id, tag)
        source_automation = self.create_remove_tag_automation(tag)
        target_automation = self.create_automation(tag, reentry="multiple", entry_type="tag_removed")
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        self.assertEqual(run.status_code, 200)
        events = self.emitted_events(tag, "tag_removed")
        self.assertEqual(len(events), 1)
        source = events[0][1]["source"]
        self.assertEqual(source["type"], "automation")
        self.assertEqual(source["automation_id"], source_automation["id"])
        self.assertEqual(source["enrolment_id"], enrolment["id"])
        self.assertEqual(source["node_id"], "node_remove_tag_1")
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

    def test_same_automation_source_tag_removed_event_is_suppressed(self):
        self.enable_emission()
        self.enable_processing()
        email, contact_id = self.create_contact()
        tag = "%s_same_auto_remove_emit" % self.test_id
        self.add_contact_tag(email, contact_id, tag)
        automation = self.create_remove_tag_automation(tag, "tag_removed", tag)
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

    def test_depth_increments_for_automation_caused_tag_removed_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        tag = "%s_remove_depth_increment" % self.test_id
        self.add_contact_tag(email, contact_id, tag)
        source_automation = self.create_remove_tag_automation(tag)
        self.create_automation(tag, entry_type="tag_removed")
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
            "%s_existing_remove_correlation" % self.test_id,
            self.user_cookie["cid"],
            enrolment["id"],
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        self.assertEqual(run.status_code, 200)

        events = self.emitted_events(tag, "tag_removed")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["correlation_id"], "%s_existing_remove_correlation" % self.test_id)
        self.assertEqual(events[0][1]["depth"], 3)

    def test_list_joined_emission_flag_off_does_not_create_event_even_with_match(self):
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        self.create_list_trigger_automation(lst["id"])
        source_automation = self.create_add_to_list_automation(lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])

        self.assertEqual(run.status_code, 200)
        self.assertTrue(run.json["step_run"]["added"])
        self.assertEqual(len(self.emitted_list_events(lst["id"])), 0)

    def test_noop_list_add_does_not_create_event(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        lst = self.create_contact_list()
        self.add_contact_to_list_row(contact_id, lst["id"])
        self.create_list_trigger_automation(lst["id"])
        source_automation = self.create_add_to_list_automation(lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])

        self.assertEqual(run.status_code, 200)
        self.assertFalse(run.json["step_run"]["added"])
        self.assertEqual(len(self.emitted_list_events(lst["id"])), 0)

    def test_noop_list_remove_does_not_create_event(self):
        self.enable_emission()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        self.create_list_trigger_automation(lst["id"], entry_type="list_left")
        source_automation = self.create_remove_from_list_automation(lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])

        self.assertEqual(run.status_code, 200)
        self.assertFalse(run.json["step_run"]["removed"])
        self.assertEqual(len(self.emitted_list_events(lst["id"], "list_left")), 0)

    def test_list_joined_emission_without_matching_automation_does_not_create_event(self):
        self.enable_emission()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        source_automation = self.create_add_to_list_automation(lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])

        self.assertEqual(run.status_code, 200)
        self.assertTrue(run.json["step_run"]["added"])
        self.assertEqual(len(self.emitted_list_events(lst["id"])), 0)

    def test_matching_published_list_joined_automation_creates_pending_event(self):
        self.enable_emission()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        self.create_list_trigger_automation(lst["id"])
        source_automation = self.create_add_to_list_automation(lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        events = self.emitted_list_events(lst["id"])

        self.assertEqual(run.status_code, 200)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["status"], "pending")
        self.assertEqual(events[0][1]["source"]["type"], "automation")

    def test_list_emission_finds_matching_multi_entry_trigger(self):
        self.enable_emission()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        target_automation = self.user_post(
            "/api/automations",
            json={"name": "automation_trigger_%s" % self.unique()},
        )
        self.created_automation_ids.append(target_automation["id"])
        self.user_patch(
            "/api/automations/%s" % target_automation["id"],
            json={
                "entry": {
                    "type": "multi",
                    "triggers": [
                        {"type": "tag_added", "tag": "%s_other" % self.test_id},
                        {"type": "list_joined", "list_id": lst["id"]},
                    ],
                },
                "reentry": "multiple",
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
        self.user_post("/api/automations/%s/publish" % target_automation["id"])
        source_automation = self.create_add_to_list_automation(lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        events = self.emitted_list_events(lst["id"])

        self.assertEqual(run.status_code, 200)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["status"], "pending")

    def test_matching_paused_list_joined_automation_creates_pending_event(self):
        self.enable_emission()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        self.create_list_trigger_automation(lst["id"], paused=True)
        source_automation = self.create_add_to_list_automation(lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        events = self.emitted_list_events(lst["id"])

        self.assertEqual(run.status_code, 200)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["status"], "pending")

    def test_processing_emitted_list_event_creates_enrolment(self):
        self.enable_emission()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        target_automation = self.create_list_trigger_automation(lst["id"], reentry="multiple")
        source_automation = self.create_add_to_list_automation(lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        events = self.emitted_list_events(lst["id"])
        result = self.process_events()

        self.assertEqual(run.status_code, 200)
        self.assertEqual(len(events), 1)
        self.assertEqual(result["enrolled"], 1)
        rows = self.enrolment_rows(target_automation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["source"], "trigger:%s" % events[0][0])

    def test_automation_add_to_list_emits_source_metadata_when_another_automation_matches(self):
        self.enable_emission()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        source_automation = self.create_add_to_list_automation(lst["id"])
        self.create_list_trigger_automation(lst["id"], reentry="multiple")
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        events = self.emitted_list_events(lst["id"])

        self.assertEqual(run.status_code, 200)
        self.assertEqual(len(events), 1)
        source = events[0][1]["source"]
        self.assertEqual(source["type"], "automation")
        self.assertEqual(source["automation_id"], source_automation["id"])
        self.assertEqual(source["enrolment_id"], enrolment["id"])
        self.assertEqual(source["node_id"], "node_add_to_list_1")
        self.assertEqual(source["step_run_id"], run.json["step_run"]["id"])
        self.assertEqual(source["published_revision"], str(source_automation["published_revision"]))

    def test_automation_remove_from_list_emits_source_metadata_when_another_automation_matches(self):
        self.enable_emission()
        email, contact_id = self.create_contact()
        lst = self.create_contact_list()
        self.add_contact_to_list_row(contact_id, lst["id"])
        source_automation = self.create_remove_from_list_automation(lst["id"])
        self.create_list_trigger_automation(lst["id"], reentry="multiple", entry_type="list_left")
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % source_automation["id"],
            json={"email": email},
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        events = self.emitted_list_events(lst["id"], "list_left")

        self.assertEqual(run.status_code, 200)
        self.assertEqual(len(events), 1)
        source = events[0][1]["source"]
        self.assertEqual(source["type"], "automation")
        self.assertEqual(source["automation_id"], source_automation["id"])
        self.assertEqual(source["enrolment_id"], enrolment["id"])
        self.assertEqual(source["node_id"], "node_remove_from_list_1")
        self.assertEqual(source["step_run_id"], run.json["step_run"]["id"])
        self.assertEqual(source["published_revision"], str(source_automation["published_revision"]))

    def test_same_automation_source_list_event_is_suppressed(self):
        self.enable_emission()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_add_to_list_automation(lst["id"], "list_joined", lst["id"])
        enrolment = self.user_post(
            "/api/automations/%s/enrolments" % automation["id"],
            json={"email": email},
        )

        run = self.run_next(automation["id"], enrolment["id"])
        result = self.process_events()

        self.assertEqual(run.status_code, 200)
        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(result["details"][0]["reason"], "same_automation_source")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 1)

    def test_depth_increments_for_automation_caused_list_event(self):
        self.enable_emission()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        source_automation = self.create_add_to_list_automation(lst["id"])
        self.create_list_trigger_automation(lst["id"])
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
            "%s_existing_list_correlation" % self.test_id,
            self.user_cookie["cid"],
            enrolment["id"],
        )

        run = self.run_next(source_automation["id"], enrolment["id"])
        events = self.emitted_list_events(lst["id"])

        self.assertEqual(run.status_code, 200)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][1]["correlation_id"], "%s_existing_list_correlation" % self.test_id)
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

    def test_same_automation_source_suppresses_list_event(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_list_trigger_automation(lst["id"])
        self.create_list_event(
            email,
            lst["id"],
            "list_joined",
            source={
                "type": "automation",
                "automation_id": automation["id"],
            },
        )

        result = self.process_events()

        self.assertEqual(result["suppressed"], 1)
        self.assertEqual(result["details"][0]["reason"], "same_automation_source")
        self.assertEqual(len(self.enrolment_rows(automation["id"])), 0)

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

    def test_active_pass_suppresses_list_event(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_list_trigger_automation(lst["id"], reentry="multiple")
        self.user_post("/api/automations/%s/enrolments" % automation["id"], json={"email": email})
        self.create_list_event(email, lst["id"], "list_joined")

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

    def test_once_suppresses_prior_enrolment_for_list_event(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_list_trigger_automation(lst["id"])
        enrolment = self.user_post("/api/automations/%s/enrolments" % automation["id"], json={"email": email})
        self.patch_enrolment_status(enrolment["id"], "completed")
        self.create_list_event(email, lst["id"], "list_joined")

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

    def test_multiple_allows_terminal_previous_pass_for_list_event(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_list_trigger_automation(lst["id"], reentry="multiple")
        enrolment = self.user_post("/api/automations/%s/enrolments" % automation["id"], json={"email": email})
        self.patch_enrolment_status(enrolment["id"], "completed")
        self.create_list_event(email, lst["id"], "list_joined")

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

    def test_depth_guard_suppresses_list_event(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_list_trigger_automation(lst["id"])
        self.create_list_event(email, lst["id"], "list_joined", depth=3)

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

    def test_cooldown_suppresses_repeat_list_event(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        automation = self.create_list_trigger_automation(lst["id"], reentry="multiple")
        self.create_list_event(email, lst["id"], "list_joined")
        first = self.process_events()
        self.assertEqual(first["enrolled"], 1)
        enrolment_id = self.enrolment_rows(automation["id"])[0][0]
        self.patch_enrolment_status(enrolment_id, "completed")

        self.create_list_event(email, lst["id"], "list_joined")
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

    def test_current_account_scoping_for_list_matching(self):
        self.enable_manual_events()
        self.enable_processing()
        email, _ = self.create_contact()
        lst = self.create_contact_list()
        other_cid = "%s_list_other_cid" % self.test_id
        self.created_other_cids.append(other_cid)
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            "%s_list_other_automation" % self.test_id,
            other_cid,
            {
                "name": "%s list other automation" % self.test_id,
                "status": "published",
                "published": {
                    "entry": {
                        "type": "list_joined",
                        "list_id": lst["id"],
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
        self.create_list_event(email, lst["id"], "list_joined")

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
