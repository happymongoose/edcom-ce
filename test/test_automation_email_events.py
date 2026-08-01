from datetime import datetime

import shortuuid

import test_base
from api.migrations import add_automation_email_events_table, add_automation_step_runs_table
from api.shared.send import encrypt
from api.shared.utils import clickletters, openletters, randomwords


class TestAutomationEmailEvents(test_base.TestBase):

    def setUp(self):
        super(TestAutomationEmailEvents, self).setUp()
        add_automation_step_runs_table.run(self.db)
        add_automation_email_events_table.run(self.db)
        self.test_id = "automation_email_events_%s" % shortuuid.uuid().lower()
        self.created_emails = []
        self.created_list_ids = []
        self.created_mailgun_ids = []
        self.created_tracking_ids = []
        self.created_sink_ids = []
        self.created_link_ids = []
        self.created_automation_ids = []
        self.created_campaign_ids = []
        self.created_enrolment_ids = []
        self.created_step_run_ids = []

    def tearDown(self):
        cid = self.user_cookie["cid"]
        if self.created_step_run_ids:
            self.db.execute(
                "delete from automation_email_events where send_step_run_id = any(%s)",
                self.created_step_run_ids,
            )
            self.db.execute(
                "delete from automation_step_runs where id = any(%s)",
                self.created_step_run_ids,
            )
        if self.created_enrolment_ids:
            self.db.execute(
                "delete from automation_enrolments where id = any(%s)",
                self.created_enrolment_ids,
            )
        if self.created_automation_ids:
            self.db.execute(
                "delete from automations where id = any(%s)",
                self.created_automation_ids,
            )
        if self.created_campaign_ids:
            self.db.execute(
                "delete from campaigns where id = any(%s)",
                self.created_campaign_ids,
            )
        if self.created_link_ids:
            self.db.execute("delete from links where id = any(%s)", self.created_link_ids)
        if self.created_tracking_ids:
            self.db.execute(
                "delete from mgtracking where id = any(%s)",
                self.created_tracking_ids,
            )
        if self.created_mailgun_ids:
            self.db.execute(
                "delete from mailgun where id = any(%s)",
                self.created_mailgun_ids,
            )
        if self.created_sink_ids:
            self.db.execute("delete from sinks where id = any(%s)", self.created_sink_ids)
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
                    f"""delete from contacts."contact_open_logs_{cid}" where contact_id = any(%s)""",
                    contact_ids,
                )
                self.db.execute(
                    f"""delete from contacts."contact_click_logs_{cid}" where contact_id = any(%s)""",
                    contact_ids,
                )
                self.db.execute(
                    f"""delete from contacts."contact_send_logs_{cid}" where contact_id = any(%s)""",
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
        super(TestAutomationEmailEvents, self).tearDown()

    def create_contact(self):
        suffix = shortuuid.uuid().lower()
        email = "automation-email-events-%s@example.com" % suffix
        lst = self.user_post(
            "/api/lists",
            json={"name": "automation_email_events_%s" % suffix},
        )
        self.created_list_ids.append(lst["id"])
        self.created_emails.append(email)
        self.user_post(
            "/api/lists/%s/feed" % lst["id"],
            json={"email": email, "data": {"First Name": "Automation"}},
        )
        contact_id = self.db.single(
            f"""select contact_id from contacts."contacts_{self.user_cookie['cid']}" where email = %s""",
            email,
        )
        return email, contact_id

    def create_mailgun_tracking(self):
        mailgun_id = shortuuid.uuid()
        tracking_id = shortuuid.uuid()
        self.db.execute(
            "insert into mailgun (id, cid, data) values (%s, %s, %s)",
            mailgun_id,
            self.user_cookie["cid"],
            {"name": "Automation email event backend %s" % self.test_id},
        )
        self.db.execute(
            "insert into mgtracking (id, ip, settingsid, ts) values (%s, %s, %s, %s)",
            tracking_id,
            "127.0.0.1",
            mailgun_id,
            datetime.utcnow(),
        )
        self.created_mailgun_ids.append(mailgun_id)
        self.created_tracking_ids.append(tracking_id)
        return tracking_id

    def create_sink(self):
        sink_id = shortuuid.uuid()
        access_key = "access-%s" % shortuuid.uuid()
        self.db.execute(
            "insert into sinks (id, cid, data) values (%s, %s, %s)",
            sink_id,
            self.user_cookie["cid"],
            {
                "name": "Automation event sink %s" % self.test_id,
                "accesskey": access_key,
            },
        )
        self.created_sink_ids.append(sink_id)
        return sink_id, access_key

    def create_automation_send_step_run(self, contact_id, contact_email):
        automation_id = "automation-%s" % shortuuid.uuid()
        enrolment_id = "enrolment-%s" % shortuuid.uuid()
        step_run_id = shortuuid.uuid()
        automation_email_id = "automation-email-%s" % shortuuid.uuid()
        node_id = "node_send_email_1"
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            automation_id,
            self.user_cookie["cid"],
            {"name": "Automation email events %s" % self.test_id},
        )
        self.db.execute(
            "insert into automation_enrolments (id, cid, automation_id, contact_id, contact_email, data) values (%s, %s, %s, %s, %s, %s)",
            enrolment_id,
            self.user_cookie["cid"],
            automation_id,
            contact_id,
            contact_email,
            {"status": "ready"},
        )
        self.db.execute(
            """
            insert into automation_step_runs
                (id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data)
            values (%s, %s, %s, %s, %s, %s, 'send_email', %s)
            """,
            step_run_id,
            self.user_cookie["cid"],
            automation_id,
            enrolment_id,
            contact_id,
            node_id,
            {
                "id": step_run_id,
                "created": datetime.utcnow().isoformat() + "Z",
                "automation_email_id": automation_email_id,
                "subject": "Automation tracked subject",
                "sent": True,
            },
        )
        self.created_automation_ids.append(automation_id)
        self.created_enrolment_ids.append(enrolment_id)
        self.created_step_run_ids.append(step_run_id)
        return {
            "automation_id": automation_id,
            "automation_email_id": automation_email_id,
            "enrolment_id": enrolment_id,
            "node_id": node_id,
            "step_run_id": step_run_id,
        }

    def track(self, event_type, step_run_id, email, tracking_id, link_id=None):
        letters = openletters if event_type == "open" else clickletters
        path = "/api/track?t=%s&c=%s&u=%s&r=%s" % (
            randomwords.random_word(self.user_cookie["cid"], letters),
            step_run_id,
            encrypt(email),
            tracking_id,
        )
        if link_id:
            path += "&l=%s" % link_id
        return self.simulate_get(
            path,
            headers={"User-Agent": "AutomationEventTest/1.0"},
        )

    def event_rows(self, step_run_id):
        return self.db.execute(
            """
            select event_type, cid, contact_id, contact_email, automation_id,
                   automation_email_id, enrolment_id, send_node_id, send_step_run_id, data
            from automation_email_events
            where send_step_run_id = %s
            order by ts, id
            """,
            step_run_id,
        ).fetchall()

    def test_automation_open_tracking_writes_event(self):
        email, contact_id = self.create_contact()
        send = self.create_automation_send_step_run(contact_id, email)
        tracking_id = self.create_mailgun_tracking()

        result = self.track("open", send["step_run_id"], email, tracking_id)

        self.assertEqual(result.status_code, 200)
        rows = self.event_rows(send["step_run_id"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[0], "open")
        self.assertEqual(row[1], self.user_cookie["cid"])
        self.assertEqual(row[2], contact_id)
        self.assertEqual(row[3], email)
        self.assertEqual(row[4], send["automation_id"])
        self.assertEqual(row[5], send["automation_email_id"])
        self.assertEqual(row[6], send["enrolment_id"])
        self.assertEqual(row[7], send["node_id"])
        self.assertEqual(row[8], send["step_run_id"])
        self.assertEqual(row[9]["provider"], "mailgun")
        self.assertEqual(row[9]["tracking_id"], tracking_id)
        self.assertEqual(row[9]["user_agent"], "AutomationEventTest/1.0")
        self.assertIsNone(
            self.db.single(
                f"""select ts from contacts."contact_open_logs_{self.user_cookie['cid']}" where contact_id = %s and campid = %s""",
                contact_id,
                send["step_run_id"],
            )
        )

    def test_automation_click_tracking_writes_event_with_link_metadata(self):
        email, contact_id = self.create_contact()
        send = self.create_automation_send_step_run(contact_id, email)
        tracking_id = self.create_mailgun_tracking()
        link_id = shortuuid.uuid()
        self.db.execute(
            "insert into links (id, url, campaign, index, track) values (%s, %s, %s, %s, %s)",
            link_id,
            "https://example.com/offer",
            send["step_run_id"],
            2,
            True,
        )
        self.created_link_ids.append(link_id)

        result = self.track("click", send["step_run_id"], email, tracking_id, link_id)

        self.assertEqual(result.status_code, 301)
        self.assertEqual(result.headers["location"], "https://example.com/offer")
        rows = self.event_rows(send["step_run_id"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[0], "click")
        self.assertEqual(row[2], contact_id)
        self.assertEqual(row[5], send["automation_email_id"])
        self.assertEqual(row[9]["link_id"], link_id)
        self.assertEqual(row[9]["link_index"], 2)
        self.assertEqual(row[9]["link_url"], "https://example.com/offer")
        self.assertIsNone(
            self.db.single(
                f"""select ts from contacts."contact_click_logs_{self.user_cookie['cid']}" where contact_id = %s and campid = %s""",
                contact_id,
                send["step_run_id"],
            )
        )

    def test_duplicate_automation_opens_are_idempotent(self):
        email, contact_id = self.create_contact()
        send = self.create_automation_send_step_run(contact_id, email)
        tracking_id = self.create_mailgun_tracking()

        self.assertEqual(self.track("open", send["step_run_id"], email, tracking_id).status_code, 200)
        self.assertEqual(self.track("open", send["step_run_id"], email, tracking_id).status_code, 200)

        self.assertEqual(len(self.event_rows(send["step_run_id"])), 1)

    def test_duplicate_automation_clicks_are_idempotent_by_link(self):
        email, contact_id = self.create_contact()
        send = self.create_automation_send_step_run(contact_id, email)
        tracking_id = self.create_mailgun_tracking()
        link_id = shortuuid.uuid()
        self.db.execute(
            "insert into links (id, url, campaign, index, track) values (%s, %s, %s, %s, %s)",
            link_id,
            "https://example.com/offer",
            send["step_run_id"],
            2,
            True,
        )
        self.created_link_ids.append(link_id)

        self.assertEqual(self.track("click", send["step_run_id"], email, tracking_id, link_id).status_code, 301)
        self.assertEqual(self.track("click", send["step_run_id"], email, tracking_id, link_id).status_code, 301)

        self.assertEqual(len(self.event_rows(send["step_run_id"])), 1)

    def test_provider_event_endpoint_captures_automation_open(self):
        email, contact_id = self.create_contact()
        send = self.create_automation_send_step_run(contact_id, email)
        sink_id, access_key = self.create_sink()

        result = self.simulate_post(
            "/api/events/%s" % sink_id,
            json={
                "accesskey": access_key,
                "events": [
                    {
                        "t": "open",
                        "c": send["step_run_id"],
                        "e": email,
                        "s": "provider-settings-id",
                        "i": "127.0.0.1",
                        "d": "example.com",
                        "k": sink_id,
                        "ts": 0,
                        "p": "203.0.113.10",
                        "a": "ProviderEventTest/1.0",
                    }
                ],
                "statevents": [],
            },
        )

        self.assertEqual(result.status_code, 200)
        rows = self.event_rows(send["step_run_id"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[0], "open")
        self.assertEqual(row[2], contact_id)
        self.assertEqual(row[4], send["automation_id"])
        self.assertEqual(row[5], send["automation_email_id"])
        self.assertEqual(row[6], send["enrolment_id"])
        self.assertEqual(row[9]["provider"], sink_id)
        self.assertEqual(row[9]["settings_id"], "provider-settings-id")
        self.assertEqual(row[9]["ip"], "203.0.113.10")
        self.assertEqual(row[9]["user_agent"], "ProviderEventTest/1.0")

    def test_non_automation_tracking_still_uses_existing_contact_logs(self):
        email, contact_id = self.create_contact()
        campid = "campaign-%s" % shortuuid.uuid()
        tracking_id = self.create_mailgun_tracking()
        self.db.execute(
            "insert into campaigns (id, cid, data) values (%s, %s, %s)",
            campid,
            self.user_cookie["cid"],
            {
                "name": "Automation event regression %s" % self.test_id,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        self.created_campaign_ids.append(campid)

        result = self.track("open", campid, email, tracking_id)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            self.db.single(
                f"""select count(*) from contacts."contact_open_logs_{self.user_cookie['cid']}" where contact_id = %s and campid = %s""",
                contact_id,
                campid,
            ),
            1,
        )
        self.assertEqual(
            self.db.single(
                "select count(*) from automation_email_events where send_step_run_id = %s",
                campid,
            ),
            0,
        )
