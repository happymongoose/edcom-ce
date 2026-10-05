import shortuuid
from datetime import datetime, timedelta

import test_base
from api.migrations import add_automation_email_events_table, add_automation_emails_table


class TestAutomationHistory(test_base.TestBase):

    def setUp(self):
        super(TestAutomationHistory, self).setUp()
        add_automation_emails_table.run(self.db)
        add_automation_email_events_table.run(self.db)
        company = self.db.companies.get(self.user_cookie["cid"])
        self.original_automation_diagnostics_visible = company.get("automation_diagnostics_visible")

    def tearDown(self):
        self.db.execute(
            "update companies set data = data - 'automation_diagnostics_visible' where id = %s",
            self.user_cookie["cid"],
        )
        if self.original_automation_diagnostics_visible is not None:
            self.db.execute(
                "update companies set data = data || %s where id = %s",
                {"automation_diagnostics_visible": self.original_automation_diagnostics_visible},
                self.user_cookie["cid"],
            )
        super(TestAutomationHistory, self).tearDown()

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def create_contact(self):
        suffix = self.unique()
        email = "automation-history-%s@example.com" % suffix
        lst = self.user_post("/api/lists", json={"name": "automation_history_%s" % suffix})
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

    def workflow(self, reentry="multiple"):
        return {
            "entry": {
                "type": "manual",
            },
            "reentry": reentry,
            "draft": {
                "nodes": [
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": "Add history tag",
                        "draft_tag": "history-tag",
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit history automation",
                    },
                ],
            },
        }

    def create_automation(self, reentry="multiple"):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_history_%s" % suffix},
        )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(reentry),
        )
        return self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

    def enrol(self, automation_id, email):
        result = self.simulate_post(
            "/api/automations/%s/enrolments" % automation_id,
            json={"email": email},
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 201)
        return result.json

    def run_next(self, automation_id, enrolment_id):
        result = self.simulate_post(
            "/api/automations/%s/enrolments/%s/run-next" % (automation_id, enrolment_id),
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json

    def run_next_skip_wait(self, automation_id, enrolment_id):
        result = self.simulate_post(
            "/api/automations/%s/enrolments/%s/run-next?skip_wait=true" % (automation_id, enrolment_id),
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 200)
        return result.json

    def history(self, automation_id):
        self.set_automation_diagnostics_visible(True)
        return self.user_get("/api/automations/%s/history" % automation_id)

    def set_automation_diagnostics_visible(self, visible):
        self.db.execute(
            "update companies set data = data || %s where id = %s",
            {"automation_diagnostics_visible": visible},
            self.user_cookie["cid"],
        )

    def cleanup(self, *automation_ids):
        self.db.execute(
            "delete from automation_email_events where automation_id = any(%s)",
            list(automation_ids),
        )
        self.db.execute(
            "delete from automation_emails where automation_id = any(%s)",
            list(automation_ids),
        )
        self.db.execute(
            "delete from automation_step_runs where automation_id = any(%s)",
            list(automation_ids),
        )
        self.db.execute(
            "delete from automation_enrolments where automation_id = any(%s)",
            list(automation_ids),
        )
        self.db.set_cid(self.user_cookie["cid"])
        for automation_id in automation_ids:
            self.db.automations.remove(automation_id)

    def create_automation_email(self, automation_id):
        email_id = "automation-history-email-%s" % self.unique()
        self.db.execute(
            """
            insert into automation_emails (id, cid, automation_id, data)
            values (%s, %s, %s, %s)
            """,
            email_id,
            self.user_cookie["cid"],
            automation_id,
            {
                "name": "History welcome email",
                "subject": "History welcome subject",
            },
        )
        return email_id

    def insert_engagement_event(
        self,
        automation_id,
        enrolment,
        automation_email_id,
        event_type,
        ts,
        data=None,
        cid=None,
    ):
        event_id = "automation-history-event-%s" % self.unique()
        self.db.execute(
            """
            insert into automation_email_events (
                id,
                cid,
                contact_id,
                contact_email,
                automation_id,
                automation_email_id,
                enrolment_id,
                send_node_id,
                send_step_run_id,
                event_type,
                ts,
                data
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            event_id,
            cid or self.user_cookie["cid"],
            enrolment["contact_id"],
            enrolment["contact_email"],
            automation_id,
            automation_email_id,
            enrolment["id"],
            "node_send_email_1",
            "send-step-history-1",
            event_type,
            ts,
            data or {},
        )
        return event_id

    def test_history_is_hidden_when_customer_diagnostics_disabled(self):
        automation = self.create_automation()
        self.set_automation_diagnostics_visible(False)

        result = self.simulate_get(
            "/api/automations/%s/history" % automation["id"],
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)
        self.assertIn("Automation diagnostics are not enabled", result.text)
        self.cleanup(automation["id"])

    def test_history_includes_enrolments_and_step_runs(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        self.run_next(automation["id"], enrolment["id"])
        self.run_next(automation["id"], enrolment["id"])

        history = self.history(automation["id"])

        self.assertEqual(history["automation_id"], automation["id"])
        self.assertEqual(history["limits"]["enrolments"], 100)
        self.assertEqual(history["limits"]["step_runs"], 500)
        self.assertEqual(len(history["enrolments"]), 1)
        self.assertEqual(history["enrolments"][0]["id"], enrolment["id"])
        self.assertEqual(history["enrolments"][0]["contact_id"], contact_id)
        self.assertEqual(history["enrolments"][0]["contact_email"], email)
        self.assertEqual(history["enrolments"][0]["status"], "exited")
        self.assertEqual(history["enrolments"][0]["source"], "manual")
        self.assertEqual(len(history["enrolments"][0]["step_runs"]), 2)
        self.assertEqual(history["enrolments"][0]["step_runs"][0]["node_id"], "node_add_tag_1")
        self.assertEqual(history["enrolments"][0]["step_runs"][0]["node_type"], "add_tag")
        self.assertEqual(history["enrolments"][0]["step_runs"][0]["node_label"], "Add history tag")
        self.assertEqual(history["enrolments"][0]["step_runs"][0]["tag"], "history-tag")
        self.assertEqual(history["enrolments"][0]["step_runs"][0]["status"], "succeeded")
        self.assertEqual(history["enrolments"][0]["step_runs"][1]["node_id"], "node_exit_1")

        self.cleanup(automation["id"])

    def test_history_includes_engagement_events(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        automation_email_id = self.create_automation_email(automation["id"])
        enrolment = self.enrol(automation["id"], email)
        self.insert_engagement_event(
            automation["id"],
            enrolment,
            automation_email_id,
            "open",
            datetime(2026, 7, 24, 21, 12, 0),
            {
                "inferred": True,
                "inferred_from_event_type": "click",
                "inferred_from_link_id": "link-1",
                "inferred_from_link_index": 2,
                "oversized_unprojected": "x" * 1000,
            },
        )
        self.insert_engagement_event(
            automation["id"],
            enrolment,
            automation_email_id,
            "click",
            datetime(2026, 7, 24, 21, 13, 0),
            {
                "link_url": "https://example.com/history",
                "link_index": 2,
                "oversized_unprojected": "x" * 1000,
            },
        )

        history = self.history(automation["id"])
        engagement_events = [event for event in history["events"] if event["type"] == "engagement"]

        self.assertEqual(history["limits"]["engagement_events"], 500)
        self.assertEqual(len(engagement_events), 2)
        self.assertEqual(len(history["enrolments"][0]["engagement_events"]), 2)
        self.assertEqual(engagement_events[0]["event_type"], "open")
        self.assertEqual(engagement_events[0]["contact_email"], email)
        self.assertEqual(engagement_events[0]["enrolment_id"], enrolment["id"])
        self.assertEqual(engagement_events[0]["automation_email_id"], automation_email_id)
        self.assertEqual(engagement_events[0]["automation_email_name"], "History welcome email")
        self.assertEqual(engagement_events[0]["subject"], "History welcome subject")
        self.assertEqual(engagement_events[0]["send_step_run_id"], "send-step-history-1")
        self.assertEqual(engagement_events[0]["inferred"], True)
        self.assertEqual(engagement_events[0]["inferred_from_event_type"], "click")
        self.assertEqual(engagement_events[0]["inferred_from_link_id"], "link-1")
        self.assertEqual(engagement_events[0]["inferred_from_link_index"], 2)
        self.assertNotIn("oversized_unprojected", engagement_events[0])
        self.assertEqual(engagement_events[1]["event_type"], "click")
        self.assertEqual(engagement_events[1]["link_url"], "https://example.com/history")
        self.assertEqual(engagement_events[1]["link_index"], 2)

        self.cleanup(automation["id"])

    def test_history_engagement_events_are_account_scoped(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        automation_email_id = self.create_automation_email(automation["id"])
        enrolment = self.enrol(automation["id"], email)
        self.insert_engagement_event(
            automation["id"],
            enrolment,
            automation_email_id,
            "open",
            datetime(2026, 7, 24, 21, 12, 0),
            cid="other-account-cid",
        )

        history = self.history(automation["id"])

        self.assertEqual([event for event in history["events"] if event["type"] == "engagement"], [])
        self.assertEqual(history["enrolments"][0]["engagement_events"], [])

        self.db.execute(
            "delete from automation_email_events where automation_id = %s and cid = %s",
            automation["id"],
            "other-account-cid",
        )
        self.cleanup(automation["id"])

    def test_history_events_are_chronological(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        self.run_next(automation["id"], enrolment["id"])
        self.run_next(automation["id"], enrolment["id"])

        history = self.history(automation["id"])
        created = [event["created"] for event in history["events"]]
        self.assertEqual(created, sorted(created))
        self.assertEqual(history["events"][0]["type"], "enrolment")
        self.assertEqual([event["type"] for event in history["events"]].count("step_run"), 2)

        self.cleanup(automation["id"])

    def test_repeat_run_sessions_remain_separate(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        first = self.enrol(automation["id"], email)
        self.run_next(automation["id"], first["id"])
        self.run_next(automation["id"], first["id"])
        second = self.enrol(automation["id"], email)

        history = self.history(automation["id"])

        self.assertEqual(len(history["enrolments"]), 2)
        self.assertEqual([enrolment["id"] for enrolment in history["enrolments"]], [first["id"], second["id"]])
        self.assertEqual(len(history["enrolments"][0]["step_runs"]), 2)
        self.assertEqual(history["enrolments"][1]["step_runs"], [])
        self.assertEqual(history["enrolments"][1]["status"], "ready")
        self.assertEqual(history["enrolments"][1]["current_node_id"], "node_add_tag_1")

        self.cleanup(automation["id"])

    def test_history_is_scoped_by_cid(self):
        automation = self.create_automation()

        self.db.execute(
            "update automations set cid = %s where id = %s",
            "other-account-cid",
            automation["id"],
        )

        result = self.simulate_get(
            "/api/automations/%s/history" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 403)

        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation["id"],
            "other-account-cid",
        )

    def test_history_endpoint_does_not_mutate_state(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        self.run_next(automation["id"], enrolment["id"])

        before_enrolments = self.db.execute(
            "select id, cid, automation_id, contact_id, contact_email, data from automation_enrolments where automation_id = %s order by id",
            automation["id"],
        ).fetchall()
        before_step_runs = self.db.execute(
            "select id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data from automation_step_runs where automation_id = %s order by id",
            automation["id"],
        ).fetchall()

        self.history(automation["id"])

        after_enrolments = self.db.execute(
            "select id, cid, automation_id, contact_id, contact_email, data from automation_enrolments where automation_id = %s order by id",
            automation["id"],
        ).fetchall()
        after_step_runs = self.db.execute(
            "select id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data from automation_step_runs where automation_id = %s order by id",
            automation["id"],
        ).fetchall()

        self.assertEqual(after_enrolments, before_enrolments)
        self.assertEqual(after_step_runs, before_step_runs)

        self.cleanup(automation["id"])

    def test_history_includes_wait_start_and_complete(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        wait_nodes = [
            {
                "id": "node_wait_1",
                "type": "wait_duration",
                "label": "Wait",
                "duration": {
                    "days": 0,
                    "hours": 0,
                    "minutes": 5,
                },
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit history automation",
            },
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json={
                "entry": {
                    "type": "manual",
                },
                "reentry": "multiple",
                "draft": {
                    "nodes": wait_nodes,
                },
            },
        )
        automation = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json
        enrolment = self.enrol(automation["id"], email)
        self.run_next(automation["id"], enrolment["id"])

        past = (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where id = %s
            """,
            {
                "wake_at": past,
                "wait": {
                    "node_id": "node_wait_1",
                    "duration": {"days": 0, "hours": 0, "minutes": 5},
                    "started_at": past,
                    "wake_at": past,
                    "published_revision": automation["published_revision"],
                },
            },
            enrolment["id"],
        )
        self.run_next(automation["id"], enrolment["id"])

        history = self.history(automation["id"])
        step_events = [event for event in history["events"] if event["type"] == "step_run"]
        self.assertEqual([event["action"] for event in step_events], ["wait_start", "wait_complete"])
        self.assertEqual(step_events[0]["node_type"], "wait_duration")
        self.assertEqual(step_events[0]["wake_at"], history["enrolments"][0]["step_runs"][0]["wake_at"])
        self.assertEqual(step_events[0]["duration"], {"days": 0, "hours": 0, "minutes": 5})

        self.cleanup(automation["id"])

    def test_history_marks_skipped_wait_completion(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        wait_nodes = [
            {
                "id": "node_wait_1",
                "type": "wait_duration",
                "label": "Wait",
                "duration": {
                    "days": 0,
                    "hours": 0,
                    "minutes": 5,
                },
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit history automation",
            },
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json={
                "entry": {
                    "type": "manual",
                },
                "reentry": "multiple",
                "draft": {
                    "nodes": wait_nodes,
                },
            },
        )
        automation = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json
        enrolment = self.enrol(automation["id"], email)
        self.run_next(automation["id"], enrolment["id"])
        self.run_next_skip_wait(automation["id"], enrolment["id"])

        history = self.history(automation["id"])
        step_events = [event for event in history["events"] if event["type"] == "step_run"]
        self.assertEqual(step_events[1]["action"], "wait_complete")
        self.assertEqual(step_events[1]["skipped"], True)

        self.cleanup(automation["id"])
