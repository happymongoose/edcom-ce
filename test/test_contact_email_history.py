import json
import shortuuid
from datetime import datetime, timedelta

import test_base
from api.migrations import add_automation_step_runs_table


class TestContactEmailHistory(test_base.TestBase):

    def setUp(self):
        super(TestContactEmailHistory, self).setUp()
        add_automation_step_runs_table.run(self.db)
        self.test_id = "contact_email_history_%s" % shortuuid.uuid().lower()
        self.created_emails = []
        self.created_list_ids = []

    def tearDown(self):
        cid = self.user_cookie["cid"]
        self.db.execute(
            "delete from automation_step_runs where data->>'test_id' = %s",
            self.test_id,
        )
        self.db.execute(
            "delete from txnsends where data->>'test_id' = %s",
            self.test_id,
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
        if self.created_list_ids:
            self.db.execute(
                "delete from lists where id = any(%s) and cid = %s",
                self.created_list_ids,
                cid,
            )
        super(TestContactEmailHistory, self).tearDown()

    def create_contact(self):
        suffix = shortuuid.uuid().lower()
        email = "contact-history-%s@example.com" % suffix
        lst = self.user_post(
            "/api/lists",
            json={"name": "contact_email_history_%s" % suffix},
        )
        self.created_list_ids.append(lst["id"])
        self.created_emails.append(email)
        self.user_post(
            "/api/lists/%s/feed" % lst["id"],
            json={"email": email, "data": {"First Name": "History"}},
        )
        contact_id = self.db.single(
            f"""select contact_id from contacts."contacts_{self.user_cookie['cid']}" where email = %s""",
            email,
        )
        return email, contact_id

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def get_history(self, email, page=1):
        result = self.simulate_get(
            "/api/contactdata/%s/email-history?page=%s" % (email, page),
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 200)
        return result.json

    def insert_automation_send(self, contact_id, created, subject="Automation subject", cid=None):
        cid = cid or self.user_cookie["cid"]
        step_run_id = shortuuid.uuid()
        self.db.execute(
            """
            insert into automation_step_runs
                (id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            step_run_id,
            cid,
            "automation-%s" % self.test_id,
            "enrolment-%s" % self.test_id,
            contact_id,
            "node-send-email",
            "send_email",
            {
                "test_id": self.test_id,
                "created": created.isoformat() + "Z",
                "sent": True,
                "status": "succeeded",
                "automation_email_id": "automation-email-%s" % self.test_id,
                "automation_email_name": "Welcome automation email",
                "subject": subject,
                "route_id": "route-%s" % self.test_id,
                "published_revision": 1,
                "html": "<p>body should not leak</p>",
            },
        )
        return step_run_id

    def insert_transactional_send(self, email, sent_at, subject="Transactional subject", cid=None):
        cid = cid or self.user_cookie["cid"]
        send_id = shortuuid.uuid()
        self.db.execute(
            """
            insert into txnsends (id, cid, ts, msgid, data)
            values (%s, %s, %s, %s, %s)
            """,
            send_id,
            cid,
            sent_at,
            "txn-msg-%s" % self.test_id,
            {
                "test_id": self.test_id,
                "event": "Delivery",
                "status": "OK",
                "subject": subject,
                "tag": "receipt",
                "to": email,
                "fromemail": "sender@example.com",
                "html": "<p>transactional body should not leak</p>",
            },
        )
        return send_id

    def test_automation_send_appears_in_contact_history(self):
        email, contact_id = self.create_contact()
        self.insert_automation_send(contact_id, datetime.utcnow())

        history = self.get_history(email)

        self.assertEqual(history["total"], 1)
        record = history["records"][0]
        self.assertEqual(record["source_type"], "automation")
        self.assertEqual(record["source_name"], "Welcome automation email")
        self.assertEqual(record["subject"], "Automation subject")
        self.assertEqual(record["status"], "sent")
        self.assertEqual(record["metadata"]["automation_email_id"], "automation-email-%s" % self.test_id)

    def test_transactional_send_appears_in_contact_history(self):
        email, _ = self.create_contact()
        self.insert_transactional_send(email, datetime.utcnow())

        history = self.get_history(email)

        self.assertEqual(history["total"], 1)
        record = history["records"][0]
        self.assertEqual(record["source_type"], "transactional")
        self.assertEqual(record["source_name"], "receipt")
        self.assertEqual(record["subject"], "Transactional subject")
        self.assertEqual(record["status"], "OK")
        self.assertEqual(record["metadata"]["tag"], "receipt")

    def test_contact_history_is_newest_first_and_paginated(self):
        email, contact_id = self.create_contact()
        base = datetime.utcnow() - timedelta(days=1)
        for i in range(12):
            if i % 2:
                self.insert_automation_send(
                    contact_id,
                    base + timedelta(minutes=i),
                    subject="Automation %02d" % i,
                )
            else:
                self.insert_transactional_send(
                    email,
                    base + timedelta(minutes=i),
                    subject="Transactional %02d" % i,
                )

        first_page = self.get_history(email, 1)
        second_page = self.get_history(email, 2)

        self.assertEqual(first_page["total"], 12)
        self.assertEqual(first_page["page_size"], 10)
        self.assertEqual(len(first_page["records"]), 10)
        self.assertEqual(len(second_page["records"]), 2)
        self.assertEqual(first_page["records"][0]["subject"], "Automation 11")
        self.assertEqual(first_page["records"][9]["subject"], "Transactional 02")
        self.assertEqual(second_page["records"][0]["subject"], "Automation 01")
        self.assertEqual(second_page["records"][1]["subject"], "Transactional 00")

    def test_contact_history_is_current_account_scoped(self):
        email, contact_id = self.create_contact()
        self.insert_automation_send(contact_id, datetime.utcnow(), subject="Visible automation")
        self.insert_automation_send(contact_id, datetime.utcnow(), subject="Other account automation", cid="other-account")
        self.insert_transactional_send(email, datetime.utcnow(), subject="Visible transactional")
        self.insert_transactional_send(email, datetime.utcnow(), subject="Other account transactional", cid="other-account")

        history = self.get_history(email)
        subjects = [record["subject"] for record in history["records"]]

        self.assertIn("Visible automation", subjects)
        self.assertIn("Visible transactional", subjects)
        self.assertNotIn("Other account automation", subjects)
        self.assertNotIn("Other account transactional", subjects)

    def test_contact_history_does_not_return_body_content(self):
        email, contact_id = self.create_contact()
        self.insert_automation_send(contact_id, datetime.utcnow())
        self.insert_transactional_send(email, datetime.utcnow())

        history = self.get_history(email)
        encoded = json.dumps(history)

        self.assertNotIn("body should not leak", encoded)
        self.assertNotIn("transactional body should not leak", encoded)
        self.assertNotIn("html", encoded)
