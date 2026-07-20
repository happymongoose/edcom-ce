import shortuuid

import test_base


class TestAutomationEnrolments(test_base.TestBase):

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def create_contact(self):
        suffix = self.unique()
        email = "automation-%s@example.com" % suffix
        lst = self.user_post("/api/lists", json={"name": "automation_enrolments_%s" % suffix})
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
        return email, contact_id, lst["id"]

    def workflow(self, reentry=None):
        doc = {
            "entry": {
                "type": "manual",
            },
            "draft": {
                "nodes": [
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": "Add onboarding tag",
                        "draft_tag": "onboarding",
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }
        if reentry is not None:
            doc["reentry"] = reentry
        return doc

    def create_automation(self, reentry=None, publish=True):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_enrolments_%s" % suffix},
        )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(reentry),
        )
        if publish:
            automation = self.simulate_post(
                "/api/automations/%s/publish" % automation["id"],
                headers=self.headers(),
            ).json
        return automation

    def enrol(self, automation_id, email):
        return self.simulate_post(
            "/api/automations/%s/enrolments" % automation_id,
            json={"email": email},
            headers=self.headers(),
        )

    def set_enrolment_status(self, enrolment_id, status):
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where cid = %s and id = %s
            """,
            {"status": status},
            self.user_cookie["cid"],
            enrolment_id,
        )

    def list_enrolments(self, automation_id):
        return self.user_get("/api/automations/%s/enrolments" % automation_id)

    def cleanup(self, *automation_ids):
        self.db.execute(
            "delete from automation_enrolments where automation_id = any(%s)",
            list(automation_ids),
        )
        self.db.set_cid(self.user_cookie["cid"])
        for automation_id in automation_ids:
            self.db.automations.remove(automation_id)

    def test_cannot_enrol_into_unpublished_automation(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(publish=False)

        result = self.enrol(automation["id"], email)
        self.assertEqual(result.status_code, 400)

        self.cleanup(automation["id"])

    def test_cannot_enrol_unknown_contact(self):
        automation = self.create_automation()

        result = self.enrol(automation["id"], "unknown-%s@example.com" % self.unique())
        self.assertEqual(result.status_code, 404)

        self.cleanup(automation["id"])

    def test_successful_enrolment_stores_expected_fields(self):
        email, contact_id, _ = self.create_contact()
        automation = self.create_automation()

        result = self.enrol(automation["id"], email)
        self.assertEqual(result.status_code, 201)
        enrolment = result.json

        self.assertEqual(enrolment["cid"], self.user_cookie["cid"])
        self.assertEqual(enrolment["automation_id"], automation["id"])
        self.assertEqual(enrolment["contact_id"], contact_id)
        self.assertEqual(enrolment["contact_email"], email)
        self.assertEqual(enrolment["status"], "ready")
        self.assertEqual(enrolment["source"], "manual")
        self.assertEqual(enrolment["current_node_id"], "node_add_tag_1")
        self.assertEqual(enrolment["published_revision"], automation["published_revision"])
        self.assertIn("created", enrolment)
        self.assertIn("modified", enrolment)

        self.cleanup(automation["id"])

    def test_once_blocks_duplicate_enrolment(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="once")

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        second = self.enrol(automation["id"], email)
        self.assertEqual(second.status_code, 400)

        self.cleanup(automation["id"])

    def test_once_blocks_after_completed_or_exited_enrolment(self):
        email, _, _ = self.create_contact()
        completed_automation = self.create_automation(reentry="once")
        completed = self.enrol(completed_automation["id"], email)
        self.assertEqual(completed.status_code, 201)
        self.set_enrolment_status(completed.json["id"], "completed")

        again = self.enrol(completed_automation["id"], email)
        self.assertEqual(again.status_code, 400)
        self.assertIn("only allows a contact to enter once", again.text)

        exited_automation = self.create_automation(reentry="once")
        exited = self.enrol(exited_automation["id"], email)
        self.assertEqual(exited.status_code, 201)
        self.set_enrolment_status(exited.json["id"], "exited")

        again = self.enrol(exited_automation["id"], email)
        self.assertEqual(again.status_code, 400)
        self.assertIn("only allows a contact to enter once", again.text)

        self.cleanup(completed_automation["id"], exited_automation["id"])

    def test_multiple_blocks_duplicate_ready_enrolment(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="multiple")

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        second = self.enrol(automation["id"], email)
        self.assertEqual(second.status_code, 400)
        self.assertIn("active enrolment", second.text)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(len(enrolments), 1)

        self.cleanup(automation["id"])

    def test_multiple_blocks_duplicate_waiting_enrolment(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="multiple")

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        self.set_enrolment_status(first.json["id"], "waiting")

        second = self.enrol(automation["id"], email)
        self.assertEqual(second.status_code, 400)
        self.assertIn("active enrolment", second.text)

        self.cleanup(automation["id"])

    def test_multiple_blocks_duplicate_held_or_paused_enrolment(self):
        for status in ("held", "paused_ready", "paused_waiting"):
            email, _, _ = self.create_contact()
            automation = self.create_automation(reentry="multiple")

            first = self.enrol(automation["id"], email)
            self.assertEqual(first.status_code, 201)
            self.set_enrolment_status(first.json["id"], status)

            second = self.enrol(automation["id"], email)
            self.assertEqual(second.status_code, 400)
            self.assertIn("active enrolment", second.text)

            self.cleanup(automation["id"])

    def test_multiple_allows_new_enrolment_after_completed(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="multiple")

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        self.set_enrolment_status(first.json["id"], "completed")

        second = self.enrol(automation["id"], email)
        self.assertEqual(second.status_code, 201)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(len(enrolments), 2)

        self.cleanup(automation["id"])

    def test_multiple_allows_new_enrolment_after_exited(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="multiple")

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        self.set_enrolment_status(first.json["id"], "exited")

        second = self.enrol(automation["id"], email)
        self.assertEqual(second.status_code, 201)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(len(enrolments), 2)

        self.cleanup(automation["id"])

    def test_multiple_active_pass_check_is_scoped_by_cid(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="multiple")

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        self.db.execute(
            "update automation_enrolments set cid = %s where id = %s",
            "other-account-cid",
            first.json["id"],
        )

        second = self.enrol(automation["id"], email)
        self.assertEqual(second.status_code, 201)

        self.db.execute(
            "delete from automation_enrolments where id = %s and cid = %s",
            first.json["id"],
            "other-account-cid",
        )
        self.cleanup(automation["id"])

    def test_enrolments_are_scoped_by_cid(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation()
        result = self.enrol(automation["id"], email)
        self.assertEqual(result.status_code, 201)

        self.db.execute(
            "update automation_enrolments set cid = %s where id = %s",
            "other-account-cid",
            result.json["id"],
        )

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(enrolments, [])

        self.db.execute(
            "delete from automation_enrolments where id = %s and cid = %s",
            result.json["id"],
            "other-account-cid",
        )
        self.cleanup(automation["id"])

    def test_enrolment_endpoints_require_automation_ownership(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation()

        self.db.execute(
            "update automations set cid = %s where id = %s",
            "other-account-cid",
            automation["id"],
        )

        result = self.simulate_get(
            "/api/automations/%s/enrolments" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 403)

        result = self.enrol(automation["id"], email)
        self.assertEqual(result.status_code, 403)

        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation["id"],
            "other-account-cid",
        )

    def test_listing_enrolments_returns_current_automation_only(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation()
        other_automation = self.create_automation()

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        second = self.enrol(other_automation["id"], email)
        self.assertEqual(second.status_code, 201)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(len(enrolments), 1)
        self.assertEqual(enrolments[0]["automation_id"], automation["id"])

        self.cleanup(automation["id"], other_automation["id"])

    def test_listing_enrolments_excludes_deleted_recreated_contacts(self):
        email, contact_id, lst = self.create_contact()
        automation = self.create_automation()

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)

        self.db.execute(
            f"""delete from contacts."contacts_{self.user_cookie['cid']}" where contact_id = %s""",
            contact_id,
        )
        self.user_post(
            "/api/lists/%s/feed" % lst,
            json={
                "email": email,
                "data": {
                    "First Name": "Automation",
                },
            },
        )
        new_contact_id = self.db.single(
            f"""select contact_id from contacts."contacts_{self.user_cookie['cid']}" where email = %s""",
            email,
        )
        self.assertNotEqual(contact_id, new_contact_id)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(enrolments, [])

        second = self.enrol(automation["id"], email)
        self.assertEqual(second.status_code, 201)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(len(enrolments), 1)
        self.assertEqual(enrolments[0]["id"], second.json["id"])
        self.assertEqual(enrolments[0]["contact_id"], new_contact_id)

        self.cleanup(automation["id"])
