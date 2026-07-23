import shortuuid
from datetime import datetime, timedelta
from unittest.mock import patch

import test_base
from api.migrations import add_debug_email_tables
from api.shared.send import send_backend_mail


class TestDebugEmailBackend(test_base.TestBase):

    def setUp(self):
        super(TestDebugEmailBackend, self).setUp()
        add_debug_email_tables.run(self.db)
        self.test_id = "debug_email_%s" % shortuuid.uuid().lower()
        self.created_route_ids = []
        self.created_backend_ids = []

    def tearDown(self):
        self.db.execute(
            "delete from debug_email_logs where data->'metadata'->>'test_id' = %s",
            self.test_id,
        )
        if self.created_backend_ids:
            self.db.execute(
                "delete from debug_email_backends where id = any(%s)",
                self.created_backend_ids,
            )
            self.db.execute(
                "delete from mailgun where id = any(%s)",
                self.created_backend_ids,
            )
        if self.created_route_ids:
            self.db.execute(
                "delete from routes where id = any(%s)",
                self.created_route_ids,
            )
        super(TestDebugEmailBackend, self).tearDown()

    def backend_cid(self):
        company = self.db.companies.get(self.user_cookie["cid"])
        return company["cid"]

    def user_cid(self):
        return self.user_cookie["cid"]

    def create_route(self, backend_id):
        route_id = shortuuid.uuid()
        now = datetime.utcnow().isoformat() + "Z"
        route = {
            "name": "Debug route %s" % self.test_id,
            "dirty": False,
            "rules": [
                {
                    "splits": [{"pct": 100, "policy": backend_id}],
                    "default": True,
                    "domaingroup": "",
                }
            ],
            "modified": now,
            "published": {
                "rules": [
                    {
                        "splits": [{"pct": 100, "policy": backend_id}],
                        "default": True,
                        "domaingroup": "",
                    }
                ],
                "usedefault": False,
            },
            "usedefault": False,
        }
        self.db.execute(
            "insert into routes (id, cid, data) values (%s, %s, %s)",
            route_id,
            self.backend_cid(),
            route,
        )
        self.created_route_ids.append(route_id)
        return self.db.routes.get(route_id)

    def create_debug_backend(self):
        backend_id = shortuuid.uuid()
        self.db.execute(
            "insert into debug_email_backends (id, cid, data) values (%s, %s, %s)",
            backend_id,
            self.backend_cid(),
            {"name": "Debug Log %s" % self.test_id},
        )
        self.created_backend_ids.append(backend_id)
        return backend_id

    def send_debug_email(self):
        backend_id = self.create_debug_backend()
        route = self.create_route(backend_id)
        return send_backend_mail(
            self.db,
            self.user_cid(),
            route,
            "<p>Hello debug</p>",
            "Sender <sender@example.com>",
            "bounce@example.com",
            "example.com",
            "reply@example.com",
            "Recipient <recipient@example.com>",
            "recipient@example.com",
            "Debug subject",
            text="Hello debug",
            source_type="automation",
            source_id="automation-1",
            source_ids={"automation_id": "automation-1", "email_id": "email-1"},
            metadata={"test_id": self.test_id},
        )

    def debug_logs(self):
        return self.db.execute(
            """
            select id, cid, data
            from debug_email_logs
            where data->'metadata'->>'test_id' = %s
            order by ts desc
            """,
            self.test_id,
        ).fetchall()

    def test_debug_backend_records_send_and_returns_success(self):
        sent = self.send_debug_email()

        rows = self.debug_logs()
        self.assertEqual(sent, True)
        self.assertEqual(len(rows), 1)

    def test_debug_backend_records_expected_fields(self):
        self.send_debug_email()

        _, cid, data = self.debug_logs()[0]
        self.assertEqual(cid, self.user_cid())
        self.assertEqual(data["recipient"], "Recipient <recipient@example.com>")
        self.assertEqual(data["recipient_email"], "recipient@example.com")
        self.assertEqual(data["from"], "Sender <sender@example.com>")
        self.assertEqual(data["returnpath"], "bounce@example.com")
        self.assertEqual(data["replyto"], "reply@example.com")
        self.assertEqual(data["subject"], "Debug subject")
        self.assertEqual(data["html"], "<p>Hello debug</p>")
        self.assertEqual(data["text"], "Hello debug")
        self.assertEqual(data["source_type"], "automation")
        self.assertEqual(data["source_id"], "automation-1")
        self.assertEqual(data["source_ids"]["email_id"], "email-1")
        self.assertEqual(data["metadata"]["test_id"], self.test_id)
        self.assertIn("route_id", data)
        self.assertIn("backend_id", data)
        self.assertIn("timestamp", data)

    def test_debug_logs_are_account_scoped(self):
        self.send_debug_email()
        self.db.execute(
            """
            insert into debug_email_logs (id, cid, ts, data)
            values (%s, %s, %s, %s)
            """,
            shortuuid.uuid(),
            self.backend_cid(),
            datetime.utcnow() + timedelta(days=1),
            {
                "subject": "Wrong account",
                "metadata": {"test_id": self.test_id},
            },
        )

        result = self.user_get("/api/debug-email-logs")

        subjects = [row.get("subject") for row in result]
        self.assertIn("Debug subject", subjects)
        self.assertNotIn("Wrong account", subjects)
        self.assertTrue(all(row["cid"] == self.user_cid() for row in result))

    def test_debug_logs_endpoint_limits_results(self):
        now = datetime.utcnow() + timedelta(days=1)
        for i in range(105):
            self.db.execute(
                """
                insert into debug_email_logs (id, cid, ts, data)
                values (%s, %s, %s, %s)
                """,
                shortuuid.uuid(),
                self.user_cid(),
                now + timedelta(seconds=i),
                {
                    "subject": "Limited %03d" % i,
                    "metadata": {"test_id": self.test_id},
                },
            )

        result = self.user_get("/api/debug-email-logs?limit=999")

        matched = [
            row
            for row in result
            if row.get("metadata", {}).get("test_id") == self.test_id
        ]
        self.assertEqual(len(result), 100)
        self.assertEqual(len(matched), 100)
        self.assertEqual(matched[0]["subject"], "Limited 104")

    def test_drop_all_mail_behaviour_is_unchanged(self):
        company = self.db.companies.get(self.user_cid())
        route = self.db.routes.get(company["routes"][0])

        with self.assertRaisesRegex(Exception, "Drop All Mail"):
            send_backend_mail(
                self.db,
                self.user_cid(),
                route,
                "<p>Hello</p>",
                "Sender <sender@example.com>",
                "bounce@example.com",
                "example.com",
                "reply@example.com",
                "Recipient <recipient@example.com>",
                "recipient@example.com",
                "Subject",
            )

    @patch("api.shared.send.mailgun_send")
    def test_real_backend_behaviour_is_unchanged(self, mailgun_send):
        backend_id = shortuuid.uuid()
        self.db.execute(
            "insert into mailgun (id, cid, data) values (%s, %s, %s)",
            backend_id,
            self.backend_cid(),
            {"name": "Mailgun %s" % self.test_id},
        )
        self.created_backend_ids.append(backend_id)
        route = self.create_route(backend_id)

        result = send_backend_mail(
            self.db,
            self.user_cid(),
            route,
            "<p>Hello real</p>",
            "Sender <sender@example.com>",
            "bounce@example.com",
            "example.com",
            "reply@example.com",
            "Recipient <recipient@example.com>",
            "recipient@example.com",
            "Real subject",
            metadata={"test_id": self.test_id},
        )

        self.assertEqual(result, False)
        mailgun_send.assert_called_once()
        self.assertEqual(self.debug_logs(), [])
