import shortuuid

import test_base


class TestAutomationEnrolments(test_base.TestBase):

    def setUp(self):
        super(TestAutomationEnrolments, self).setUp()
        self.created_automation_ids = []
        self.created_list_ids = []
        self.created_segment_ids = []
        self.created_emails = []
        self.created_gather_ids = []

    def tearDown(self):
        cid = self.user_cookie["cid"]
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
                    "delete from automation_step_runs where contact_id = any(%s) and cid = %s",
                    contact_ids,
                    cid,
                )
                self.db.execute(
                    "delete from automation_enrolments where contact_id = any(%s) and cid = %s",
                    contact_ids,
                    cid,
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
        if self.created_segment_ids:
            self.db.execute(
                "delete from segments where id = any(%s) and cid = %s",
                self.created_segment_ids,
                cid,
            )
        if self.created_gather_ids:
            self.db.execute(
                "delete from taskgatherdata where data->>'gatherid' = any(%s)",
                self.created_gather_ids,
            )
            self.db.execute(
                "delete from taskgather where id = any(%s)",
                self.created_gather_ids,
            )
        super(TestAutomationEnrolments, self).tearDown()

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
        self.created_list_ids.append(lst["id"])
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
        self.created_emails.append(email)
        return email, contact_id, lst["id"]

    def create_list_with_contacts(self, count):
        suffix = self.unique()
        lst = self.user_post("/api/lists", json={"name": "automation_bulk_%s" % suffix})
        self.created_list_ids.append(lst["id"])
        contacts = []
        for index in range(count):
            email = "automation-bulk-%s-%s@example.com" % (suffix, index)
            self.user_post(
                "/api/lists/%s/feed" % lst["id"],
                json={
                    "email": email,
                    "data": {
                        "First Name": "Bulk",
                    },
                },
            )
            contact_id = self.db.single(
                f"""select contact_id from contacts."contacts_{self.user_cookie['cid']}" where email = %s""",
                email,
            )
            self.created_emails.append(email)
            contacts.append((email, contact_id))
        return lst["id"], contacts

    def create_segment_for_contacts(self, contacts):
        prefix = contacts[0][0].rsplit("-", 1)[0]
        segment = self.user_post(
            "/api/segments",
            json={
                "name": "automation_segment_%s" % self.unique(),
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
            },
        )
        self.created_segment_ids.append(segment["id"])
        return segment

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
        self.created_automation_ids.append(automation["id"])
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

    def bulk_enrol(self, automation_id, list_id):
        return self.simulate_post(
            "/api/automations/%s/enrolments/list" % automation_id,
            json={"list_id": list_id},
            headers=self.headers(),
        )

    def bulk_segment_enrol(self, automation_id, segment_id):
        return self.simulate_post(
            "/api/automations/%s/enrolments/segment" % automation_id,
            json={"segment_id": segment_id},
            headers=self.headers(),
        )

    def bulk_result(self, response):
        self.assertEqual(response.status_code, 200)
        payload = response.json
        if "id" in payload:
            self.created_gather_ids.append(payload["id"])
            status = self.user_get("/api/automation-list-enrolments/%s" % payload["id"])
            self.assertTrue(status.get("complete"), status)
            return status["result"]
        self.assertTrue(payload.get("complete"), payload)
        return payload["result"]

    def bulk_segment_result(self, response):
        self.assertEqual(response.status_code, 200)
        payload = response.json
        if "id" in payload:
            self.created_gather_ids.append(payload["id"])
            status = self.user_get("/api/automation-segment-enrolments/%s" % payload["id"])
            self.assertTrue(status.get("complete"), status)
            return status["result"]
        self.assertTrue(payload.get("complete"), payload)
        return payload["result"]

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

    def test_once_blocks_after_failed_enrolment(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="once")
        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        self.set_enrolment_status(first.json["id"], "failed")

        again = self.enrol(automation["id"], email)

        self.assertEqual(again.status_code, 400)
        self.assertIn("only allows a contact to enter once", again.text)

        self.cleanup(automation["id"])

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

    def test_multiple_allows_new_enrolment_after_cancelled(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="multiple")

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        self.set_enrolment_status(first.json["id"], "cancelled")

        second = self.enrol(automation["id"], email)
        self.assertEqual(second.status_code, 201)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(len(enrolments), 2)

        self.cleanup(automation["id"])

    def test_multiple_allows_new_enrolment_after_failed(self):
        email, _, _ = self.create_contact()
        automation = self.create_automation(reentry="multiple")

        first = self.enrol(automation["id"], email)
        self.assertEqual(first.status_code, 201)
        self.set_enrolment_status(first.json["id"], "failed")

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

    def test_bulk_enrols_contacts_from_list_with_counts_and_source(self):
        list_id, contacts = self.create_list_with_contacts(3)
        automation = self.create_automation()

        result = self.bulk_result(self.bulk_enrol(automation["id"], list_id))

        self.assertEqual(result["enrolled_count"], 3)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["error_count"], 0)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(len(enrolments), 3)
        self.assertEqual(
            sorted(e["contact_email"] for e in enrolments),
            sorted(email for email, _ in contacts),
        )
        self.assertTrue(all(e["source"] == "list:%s" % list_id for e in enrolments))

    def test_bulk_enrol_unknown_or_unowned_list_is_blocked(self):
        automation = self.create_automation()

        unknown = self.bulk_enrol(automation["id"], "unknown-list-id")
        self.assertEqual(unknown.status_code, 403)

        list_id, _ = self.create_list_with_contacts(1)
        self.db.execute(
            "update lists set cid = %s where id = %s",
            "other-account-cid",
            list_id,
        )

        unowned = self.bulk_enrol(automation["id"], list_id)
        self.assertEqual(unowned.status_code, 403)

        self.db.execute(
            "delete from lists where id = %s and cid = %s",
            list_id,
            "other-account-cid",
        )

    def test_bulk_enrol_unpublished_automation_is_blocked(self):
        list_id, _ = self.create_list_with_contacts(1)
        automation = self.create_automation(publish=False)

        result = self.bulk_enrol(automation["id"], list_id)

        self.assertEqual(result.status_code, 400)
        self.assertIn("Publish the automation", result.text)

    def test_bulk_enrol_paused_automation_creates_held_enrolments(self):
        list_id, _ = self.create_list_with_contacts(2)
        automation = self.create_automation()
        paused = self.simulate_post(
            "/api/automations/%s/pause" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(paused.status_code, 200)

        result = self.bulk_result(self.bulk_enrol(automation["id"], list_id))

        self.assertEqual(result["enrolled_count"], 2)
        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(sorted(e["status"] for e in enrolments), ["held", "held"])

    def test_bulk_enrol_once_skips_previously_enrolled_contacts(self):
        list_id, contacts = self.create_list_with_contacts(2)
        automation = self.create_automation(reentry="once")
        first = self.enrol(automation["id"], contacts[0][0])
        self.assertEqual(first.status_code, 201)

        result = self.bulk_result(self.bulk_enrol(automation["id"], list_id))

        self.assertEqual(result["enrolled_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "once")
        self.assertEqual(len(self.list_enrolments(automation["id"])), 2)

    def test_bulk_enrol_multiple_skips_active_and_allows_terminal_previous_pass(self):
        list_id, contacts = self.create_list_with_contacts(3)
        automation = self.create_automation(reentry="multiple")

        active = self.enrol(automation["id"], contacts[0][0])
        self.assertEqual(active.status_code, 201)
        completed = self.enrol(automation["id"], contacts[1][0])
        self.assertEqual(completed.status_code, 201)
        self.set_enrolment_status(completed.json["id"], "completed")

        result = self.bulk_result(self.bulk_enrol(automation["id"], list_id))

        self.assertEqual(result["enrolled_count"], 2)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "active_pass")
        self.assertEqual(len(self.list_enrolments(automation["id"])), 4)

    def test_bulk_enrol_status_endpoint_returns_final_result(self):
        list_id, _ = self.create_list_with_contacts(2)
        automation = self.create_automation()
        self.db.lists.patch(list_id, {"count": 10001})

        response = self.bulk_enrol(automation["id"], list_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.json)
        self.created_gather_ids.append(response.json["id"])

        status = self.user_get("/api/automation-list-enrolments/%s" % response.json["id"])

        self.assertTrue(status.get("complete"), status)
        self.assertEqual(status["result"]["enrolled_count"], 2)
        self.assertEqual(status["result"]["skipped_count"], 0)
        self.assertEqual(status["result"]["error_count"], 0)

    def test_bulk_enrol_status_endpoint_requires_gather_ownership(self):
        list_id, _ = self.create_list_with_contacts(2)
        automation = self.create_automation()
        self.db.lists.patch(list_id, {"count": 10001})

        response = self.bulk_enrol(automation["id"], list_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.json)
        self.created_gather_ids.append(response.json["id"])
        self.db.execute(
            "update taskgather set cid = %s where id = %s",
            "other-account-cid",
            response.json["id"],
        )

        status = self.simulate_get(
            "/api/automation-list-enrolments/%s" % response.json["id"],
            headers=self.headers(),
        )

        self.assertEqual(status.status_code, 403)

    def test_bulk_enrol_endpoint_requires_automation_ownership(self):
        list_id, _ = self.create_list_with_contacts(1)
        automation = self.create_automation()
        self.db.execute(
            "update automations set cid = %s where id = %s",
            "other-account-cid",
            automation["id"],
        )

        result = self.bulk_enrol(automation["id"], list_id)

        self.assertEqual(result.status_code, 403)
        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation["id"],
            "other-account-cid",
        )

    def test_bulk_segment_enrols_matching_contacts_with_counts_and_source(self):
        _, contacts = self.create_list_with_contacts(3)
        segment = self.create_segment_for_contacts(contacts)
        automation = self.create_automation()

        result = self.bulk_segment_result(self.bulk_segment_enrol(automation["id"], segment["id"]))

        self.assertEqual(result["enrolled_count"], 3)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["error_count"], 0)

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(len(enrolments), 3)
        self.assertEqual(
            sorted(e["contact_email"] for e in enrolments),
            sorted(email for email, _ in contacts),
        )
        self.assertTrue(all(e["source"] == "segment:%s" % segment["id"] for e in enrolments))

    def test_bulk_segment_unknown_or_unowned_segment_is_blocked(self):
        automation = self.create_automation()

        unknown = self.bulk_segment_enrol(automation["id"], "unknown-segment-id")
        self.assertEqual(unknown.status_code, 403)

        _, contacts = self.create_list_with_contacts(1)
        segment = self.create_segment_for_contacts(contacts)
        self.db.execute(
            "update segments set cid = %s where id = %s",
            "other-account-cid",
            segment["id"],
        )

        unowned = self.bulk_segment_enrol(automation["id"], segment["id"])
        self.assertEqual(unowned.status_code, 403)

        self.db.execute(
            "delete from segments where id = %s and cid = %s",
            segment["id"],
            "other-account-cid",
        )

    def test_bulk_segment_unpublished_automation_is_blocked(self):
        _, contacts = self.create_list_with_contacts(1)
        segment = self.create_segment_for_contacts(contacts)
        automation = self.create_automation(publish=False)

        result = self.bulk_segment_enrol(automation["id"], segment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("Publish the automation", result.text)

    def test_bulk_segment_paused_automation_creates_held_enrolments(self):
        _, contacts = self.create_list_with_contacts(2)
        segment = self.create_segment_for_contacts(contacts)
        automation = self.create_automation()
        paused = self.simulate_post(
            "/api/automations/%s/pause" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(paused.status_code, 200)

        result = self.bulk_segment_result(self.bulk_segment_enrol(automation["id"], segment["id"]))

        self.assertEqual(result["enrolled_count"], 2)
        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(sorted(e["status"] for e in enrolments), ["held", "held"])

    def test_bulk_segment_once_skips_previously_enrolled_contacts(self):
        _, contacts = self.create_list_with_contacts(2)
        segment = self.create_segment_for_contacts(contacts)
        automation = self.create_automation(reentry="once")
        first = self.enrol(automation["id"], contacts[0][0])
        self.assertEqual(first.status_code, 201)

        result = self.bulk_segment_result(self.bulk_segment_enrol(automation["id"], segment["id"]))

        self.assertEqual(result["enrolled_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "once")
        self.assertEqual(len(self.list_enrolments(automation["id"])), 2)

    def test_bulk_segment_multiple_skips_active_and_allows_terminal_previous_pass(self):
        _, contacts = self.create_list_with_contacts(3)
        segment = self.create_segment_for_contacts(contacts)
        automation = self.create_automation(reentry="multiple")

        active = self.enrol(automation["id"], contacts[0][0])
        self.assertEqual(active.status_code, 201)
        completed = self.enrol(automation["id"], contacts[1][0])
        self.assertEqual(completed.status_code, 201)
        self.set_enrolment_status(completed.json["id"], "completed")

        result = self.bulk_segment_result(self.bulk_segment_enrol(automation["id"], segment["id"]))

        self.assertEqual(result["enrolled_count"], 2)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["skipped"][0]["reason"], "active_pass")
        self.assertEqual(len(self.list_enrolments(automation["id"])), 4)

    def test_bulk_segment_status_endpoint_returns_final_result(self):
        list_id, contacts = self.create_list_with_contacts(2)
        segment = self.create_segment_for_contacts(contacts)
        automation = self.create_automation()
        self.db.lists.patch(list_id, {"count": 10001})

        response = self.bulk_segment_enrol(automation["id"], segment["id"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.json)
        self.created_gather_ids.append(response.json["id"])

        status = self.user_get("/api/automation-segment-enrolments/%s" % response.json["id"])

        self.assertTrue(status.get("complete"), status)
        self.assertEqual(status["result"]["enrolled_count"], 2)
        self.assertEqual(status["result"]["skipped_count"], 0)
        self.assertEqual(status["result"]["error_count"], 0)

    def test_bulk_segment_status_endpoint_requires_gather_ownership(self):
        list_id, contacts = self.create_list_with_contacts(2)
        segment = self.create_segment_for_contacts(contacts)
        automation = self.create_automation()
        self.db.lists.patch(list_id, {"count": 10001})

        response = self.bulk_segment_enrol(automation["id"], segment["id"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.json)
        self.created_gather_ids.append(response.json["id"])
        self.db.execute(
            "update taskgather set cid = %s where id = %s",
            "other-account-cid",
            response.json["id"],
        )

        status = self.simulate_get(
            "/api/automation-segment-enrolments/%s" % response.json["id"],
            headers=self.headers(),
        )

        self.assertEqual(status.status_code, 403)

    def test_bulk_segment_endpoint_requires_automation_ownership(self):
        _, contacts = self.create_list_with_contacts(1)
        segment = self.create_segment_for_contacts(contacts)
        automation = self.create_automation()
        self.db.execute(
            "update automations set cid = %s where id = %s",
            "other-account-cid",
            automation["id"],
        )

        result = self.bulk_segment_enrol(automation["id"], segment["id"])

        self.assertEqual(result.status_code, 403)
        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation["id"],
            "other-account-cid",
        )
