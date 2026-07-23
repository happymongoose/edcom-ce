import shortuuid
from unittest.mock import patch

import test_base


class TestAutomationEmails(test_base.TestBase):

    def setUp(self):
        super(TestAutomationEmails, self).setUp()
        self.created_automation_ids = []
        self.created_email_ids = []

    def tearDown(self):
        cid = self.user_cookie["cid"]
        if self.created_email_ids:
            self.db.execute(
                "delete from automation_emails where id = any(%s) and cid = %s",
                self.created_email_ids,
                cid,
            )
        if self.created_automation_ids:
            self.db.execute(
                "delete from automation_emails where automation_id = any(%s) and cid = %s",
                self.created_automation_ids,
                cid,
            )
            self.db.execute(
                "delete from automations where id = any(%s) and cid = %s",
                self.created_automation_ids,
                cid,
            )
        super(TestAutomationEmails, self).tearDown()

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def create_automation(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_emails_%s" % self.unique()},
        )
        self.created_automation_ids.append(automation["id"])
        return automation

    def create_email(self, automation_id, **overrides):
        doc = {
            "name": "Email %s" % self.unique(),
            "subject": "Subject",
            "preheader": "Preview",
            "rawText": "<p>Hello</p>",
        }
        doc.update(overrides)
        email = self.user_post(
            "/api/automations/%s/emails" % automation_id,
            json=doc,
        )
        self.created_email_ids.append(email["id"])
        return email

    def route_id(self):
        company = self.db.companies.get(self.user_cookie["cid"])
        return company["routes"][0]

    def test_create_list_get_patch_duplicate_and_delete_email(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        self.assertEqual(email["automation_id"], automation["id"])
        self.assertEqual(email["name"].startswith("Email "), True)
        self.assertEqual(email["subject"], "Subject")
        self.assertEqual(email["preheader"], "Preview")
        self.assertEqual(email["type"], "raw")
        self.assertEqual(email["rawText"], "<p>Hello</p>")
        self.assertEqual(email["parts"], [])
        self.assertEqual(email["bodyStyle"], {})
        self.assertIn("created", email)
        self.assertIn("modified", email)

        emails = self.user_get("/api/automations/%s/emails" % automation["id"])
        self.assertEqual([item["id"] for item in emails], [email["id"]])

        fetched = self.user_get(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"])
        )
        self.assertEqual(fetched["id"], email["id"])

        patched = self.user_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={
                "name": "Updated name",
                "subject": "Updated subject",
                "preheader": "Updated preview",
                "rawText": "<p>Updated</p>",
            },
        )
        self.assertEqual(patched["name"], "Updated name")
        self.assertEqual(patched["subject"], "Updated subject")
        self.assertEqual(patched["rawText"], "<p>Updated</p>")

        duplicated = self.user_post(
            "/api/automations/%s/emails/%s/duplicate" % (automation["id"], email["id"]),
            json={},
        )
        self.created_email_ids.append(duplicated["id"])
        self.assertNotEqual(duplicated["id"], email["id"])
        self.assertEqual(duplicated["subject"], "Updated subject")
        self.assertEqual(duplicated["rawText"], "<p>Updated</p>")
        self.assertEqual(duplicated["name"], "Updated name (2)")

        self.user_delete(
            "/api/automations/%s/emails/%s" % (automation["id"], duplicated["id"])
        )
        emails = self.user_get("/api/automations/%s/emails" % automation["id"])
        self.assertEqual([item["id"] for item in emails], [email["id"]])

    def test_default_email_shape(self):
        automation = self.create_automation()

        email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={},
        )
        self.created_email_ids.append(email["id"])

        self.assertEqual(email["name"], "New automation email")
        self.assertEqual(email["subject"], "Click Here to Edit")
        self.assertEqual(email["type"], "raw")
        self.assertEqual(email["rawText"], "<p>Hello</p>")

    def test_editor_type_is_set_at_creation(self):
        automation = self.create_automation()

        for email_type in ("beefree", "", "wysiwyg", "raw"):
            email = self.user_post(
                "/api/automations/%s/emails" % automation["id"],
                json={"type": email_type},
            )
            self.created_email_ids.append(email["id"])
            self.assertEqual(email["type"], email_type)

    def test_editor_compatible_fields_can_be_saved(self):
        automation = self.create_automation()
        email = self.create_email(
            automation["id"],
            type="beefree",
            rawText='{"page": {"body": {}}}',
        )

        beefree = self.user_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={
                "type": "beefree",
                "rawText": '{"page": {"body": {}}}',
                "parts": [],
                "bodyStyle": {},
            },
        )
        self.assertEqual(beefree["type"], "beefree")
        self.assertEqual(beefree["rawText"], '{"page": {"body": {}}}')

    def test_legacy_editor_fields_can_be_saved(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"], type="")

        legacy = self.user_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={
                "type": "",
                "parts": [{"type": "text"}],
                "bodyStyle": {"version": 3},
            },
        )
        self.assertEqual(legacy["type"], "")
        self.assertEqual(legacy["parts"], [{"type": "text"}])
        self.assertEqual(legacy["bodyStyle"], {"version": 3})

    def test_editor_type_cannot_be_changed_after_creation(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"], type="raw")

        result = self.simulate_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={"type": "wysiwyg"},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("editor type is fixed", result.text)

    def test_invalid_editor_type_is_rejected(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        result = self.simulate_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={"type": "broadcast"},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)

    @patch("api.automations.send_backend_mail")
    def test_send_test_email_requires_to_address(self, send_backend_mail):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        result = self.simulate_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={"route": self.route_id()},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        send_backend_mail.assert_not_called()

    @patch("api.automations.check_test_limit")
    @patch("api.automations.send_backend_mail")
    def test_send_test_email_uses_automation_email(self, send_backend_mail, check_test_limit):
        automation = self.create_automation()
        email = self.create_email(
            automation["id"],
            subject="Automation Test Subject",
            rawText="<h1>Automation Test Body</h1>",
        )

        result = self.user_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={"to": "recipient@example.com", "route": self.route_id()},
        )

        self.assertEqual(result, {})
        check_test_limit.assert_called_once()
        send_backend_mail.assert_called_once()
        args = send_backend_mail.call_args[0]
        self.assertEqual(args[1], self.user_cookie["cid"])
        self.assertIn("Automation Test Body", args[3])
        self.assertEqual(args[8], "recipient@example.com")
        self.assertEqual(args[10], "Automation Test Subject")

        user = self.db.users.get(self.user_cookie["uid"])
        self.assertEqual(user["lasttest"]["to"], "recipient@example.com")
        self.assertEqual(user["lasttest"]["route"], self.route_id())

    @patch("api.automations.add_test_txn_log")
    @patch("api.automations.check_test_limit")
    @patch("api.automations.send_backend_mail")
    def test_send_test_email_can_be_included_in_transactional_log(
        self,
        send_backend_mail,
        check_test_limit,
        add_test_txn_log,
    ):
        automation = self.create_automation()
        email = self.create_email(
            automation["id"],
            subject="Logged Automation Test Subject",
        )

        result = self.user_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={
                "to": "recipient@example.com",
                "route": self.route_id(),
                "include_in_log": True,
            },
        )

        self.assertEqual(result, {})
        send_backend_mail.assert_called_once()
        check_test_limit.assert_called_once()
        add_test_txn_log.assert_called_once()
        args = add_test_txn_log.call_args[0]
        self.assertEqual(args[1], self.user_cookie["cid"])
        self.assertEqual(args[2], "recipient@example.com")
        self.assertEqual(args[3], "Logged Automation Test Subject")
        self.assertEqual(args[4], "automation:%s" % automation["id"])
        self.assertEqual(args[8], self.route_id())
        self.assertEqual(add_test_txn_log.call_args[1]["status"], "Sent")

    @patch("api.automations.add_test_txn_log")
    @patch("api.automations.check_test_limit")
    @patch("api.automations.send_backend_mail")
    def test_send_test_email_does_not_log_by_default(
        self,
        send_backend_mail,
        check_test_limit,
        add_test_txn_log,
    ):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        result = self.user_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={"to": "recipient@example.com", "route": self.route_id()},
        )

        self.assertEqual(result, {})
        send_backend_mail.assert_called_once()
        check_test_limit.assert_called_once()
        add_test_txn_log.assert_not_called()

    @patch("api.automations.send_backend_mail")
    def test_send_test_email_rejects_invalid_include_in_log(self, send_backend_mail):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        result = self.simulate_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={
                "to": "recipient@example.com",
                "route": self.route_id(),
                "include_in_log": "yes",
            },
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        send_backend_mail.assert_not_called()

    @patch("api.automations.send_backend_mail")
    def test_send_test_email_requires_email_ownership(self, send_backend_mail):
        first = self.create_automation()
        second = self.create_automation()
        email = self.create_email(first["id"])

        result = self.simulate_post(
            "/api/automations/%s/emails/%s/test" % (second["id"], email["id"]),
            json={"to": "recipient@example.com", "route": self.route_id()},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)
        send_backend_mail.assert_not_called()

    def test_email_endpoints_require_automation_ownership(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])
        self.db.execute(
            "update automations set cid = %s where id = %s",
            "other-account-cid",
            automation["id"],
        )

        listed = self.simulate_get(
            "/api/automations/%s/emails" % automation["id"],
            headers=self.headers(),
        )
        fetched = self.simulate_get(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(listed.status_code, 403)
        self.assertEqual(fetched.status_code, 403)
        self.db.execute(
            "delete from automation_emails where id = %s and cid = %s",
            email["id"],
            self.user_cookie["cid"],
        )
        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation["id"],
            "other-account-cid",
        )

    def test_email_must_belong_to_automation(self):
        first = self.create_automation()
        second = self.create_automation()
        email = self.create_email(first["id"])

        result = self.simulate_get(
            "/api/automations/%s/emails/%s" % (second["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)

    def test_delete_rejects_draft_reference(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])
        self.db.automations.patch(
            automation["id"],
            {
                "draft": {
                    "nodes": [
                        {
                            "id": "node_send_email_1",
                            "type": "send_email",
                            "label": "Send email",
                            "automation_email_id": email["id"],
                        }
                    ]
                }
            },
        )

        result = self.simulate_delete(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("referenced by draft step 1", result.text)

    def test_delete_rejects_published_reference(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])
        self.db.automations.patch(
            automation["id"],
            {
                "published": {
                    "nodes": [
                        {
                            "id": "node_send_email_1",
                            "type": "send_email",
                            "label": "Send email",
                            "automation_email_id": email["id"],
                        }
                    ]
                }
            },
        )

        result = self.simulate_delete(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("referenced by published step 1", result.text)
