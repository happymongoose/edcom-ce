import test_base


class TestAutomationCRUD(test_base.TestBase):

    def setUp(self):
        super(TestAutomationCRUD, self).setUp()
        self.created_automation_ids = []
        self.created_email_ids = []
        self.created_list_ids = []
        self.created_segment_ids = []

    def tearDown(self):
        cid = self.user_cookie["cid"]
        if self.created_email_ids:
            self.db.execute(
                "delete from automation_emails where id = any(%s) and cid in (%s, %s)",
                self.created_email_ids,
                cid,
                "other-account-cid",
            )
        if self.created_automation_ids:
            self.db.execute(
                "delete from automation_emails where automation_id = any(%s) and cid in (%s, %s)",
                self.created_automation_ids,
                cid,
                "other-account-cid",
            )
            self.db.execute(
                "delete from automation_step_runs where automation_id = any(%s)",
                self.created_automation_ids,
            )
            self.db.execute(
                "delete from automation_enrolments where automation_id = any(%s)",
                self.created_automation_ids,
            )
            self.db.execute(
                "delete from automations where id = any(%s) and cid in (%s, %s)",
                self.created_automation_ids,
                cid,
                "other-account-cid",
            )
        if self.created_list_ids:
            self.db.execute(
                f"""delete from contacts."contact_lists_{cid}" where list_id = any(%s)""",
                self.created_list_ids,
            )
            self.db.execute(
                "delete from list_domains where list_id = any(%s)",
                self.created_list_ids,
            )
            self.db.execute(
                "delete from lists where id = any(%s) and cid in (%s, %s)",
                self.created_list_ids,
                cid,
                "other-account-cid",
            )
        if self.created_segment_ids:
            self.db.execute(
                "delete from segments where id = any(%s) and cid in (%s, %s)",
                self.created_segment_ids,
                cid,
                "other-account-cid",
            )
        super(TestAutomationCRUD, self).tearDown()

    def valid_workflow(self, label="Add onboarding tag", draft_tag="onboarding", reentry=None):
        workflow = {
            "entry": {
                "type": "manual",
            },
            "draft": {
                "nodes": [
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": label,
                        "draft_tag": draft_tag,
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
            workflow["reentry"] = reentry

        return workflow

    def valid_published_workflow(self, label="Add onboarding tag", draft_tag="onboarding", reentry="once"):
        return {
            "entry": {
                "type": "manual",
            },
            "reentry": reentry,
            "nodes": [
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": label,
                    "draft_tag": draft_tag,
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ],
        }

    def wait_workflow(self, duration=None):
        if duration is None:
            duration = {
                "days": 0,
                "hours": 0,
                "minutes": 5,
            }
        return {
            "entry": {
                "type": "manual",
            },
            "draft": {
                "nodes": [
                    {
                        "id": "node_wait_1",
                        "type": "wait_duration",
                        "label": "Wait",
                        "duration": duration,
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

    def condition_workflow(self, condition=None):
        if condition is None:
            condition = {
                "id": "node_condition_1",
                "type": "if_has_tag",
                "label": "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            }
        return {
            "entry": {
                "type": "manual",
            },
            "draft": {
                "nodes": [
                    condition,
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": "Add tagged branch",
                        "draft_tag": "tagged-branch",
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

    def workflow_with_nodes(self, nodes):
        return {
            "entry": {
                "type": "manual",
            },
            "draft": {
                "nodes": nodes,
            },
        }

    def create_contact_list(self, name="automation_crud_list"):
        lst = self.user_post("/api/lists", json={"name": name})
        self.created_list_ids.append(lst["id"])
        return lst

    def create_segment(self, name="automation_crud_segment"):
        segment = self.user_post(
            "/api/segments",
            json={
                "name": name,
                "parts": [],
            },
        )
        self.created_segment_ids.append(segment["id"])
        return segment

    def go_to_workflow(self, go_to=None):
        if go_to is None:
            go_to = {
                "id": "node_go_to_1",
                "type": "go_to",
                "label": "Go to shared step",
                "target_node_id": "node_exit_1",
            }
        return {
            "entry": {
                "type": "manual",
            },
            "draft": {
                "nodes": [
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": "Add branch tag",
                        "draft_tag": "branch-tag",
                    },
                    go_to,
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

    def user_publish(self, automation_id):
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        if result.status_code < 200 or result.status_code >= 300:
            print(result.status)
            print(result.text)
            assert False, "API request failed"

        return result.json

    def create_tracked_automation(self, name="Send Email Node"):
        automation = self.user_post("/api/automations", json={"name": name})
        self.created_automation_ids.append(automation["id"])
        return automation

    def create_automation_email(self, automation_id, **overrides):
        doc = {
            "name": "Email for automation node",
            "subject": "Subject for automation node",
            "rawText": "<p>Hello</p>",
        }
        doc.update(overrides)
        email = self.user_post(
            "/api/automations/%s/emails" % automation_id,
            json=doc,
        )
        self.created_email_ids.append(email["id"])
        return email

    def send_email_workflow(self, email_id=None):
        node = {
            "id": "node_send_email_1",
            "type": "send_email",
            "label": "Send email",
        }
        if email_id is not None:
            node["automation_email_id"] = email_id
        return self.workflow_with_nodes(
            [
                node,
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )

    def email_engagement_condition_workflow(self, email_id=None, node_type="if_opened_email", condition=None):
        if condition is None:
            condition = {
                "id": "node_email_condition_1",
                "type": node_type,
                "label": "If opened email" if node_type == "if_opened_email" else "If clicked email",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            }
            if email_id is not None:
                condition["automation_email_id"] = email_id
        return self.workflow_with_nodes(
            [
                condition,
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add engaged branch",
                    "draft_tag": "engaged-branch",
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )

    def assert_existing_publish_fails(self, automation_id, message):
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn(message, result.text)

    def test_plural_tag_schema_preserves_legacy_and_rejects_ambiguous_values(self):
        for action in ("add_tag", "remove_tag"):
            for config, expected in (({"draft_tag": "legacy"}, 200), ({"draft_tags": ["one", "two"]}, 200),
                                     ({"draft_tag": "one", "draft_tags": ["two"]}, 400),
                                     ({"draft_tags": ["one", "one"]}, 400), ({"draft_tags": [1]}, 400)):
                with self.subTest(action=action, config=config):
                    a = self.create_tracked_automation("Tag schema")
                    node = {"id": "tag", "type": action, "label": "Tags", **config}
                    result = self.simulate_patch("/api/automations/%s" % a["id"], json=self.workflow_with_nodes([node]), headers={"X-Auth-UID":self.user_cookie["uid"], "X-Auth-Cookie":self.user_cookie["id"]})
                    self.assertEqual(result.status_code, expected, result.text)
                    if expected == 200:
                        self.assertEqual(self.user_publish(a["id"])["published"]["nodes"][0], node)
        self.assert_publish_fails(self.workflow_with_nodes([{"id":"tag","type":"add_tag","label":"Tags","draft_tags":[]}]), "tag configuration")
        self.assert_publish_fails(self.workflow_with_nodes([{"id":"tag","type":"add_tag","label":"Tags","draft_tags":["valid", ""]}]), "tag configuration")

    def test_date_wait_requires_an_exact_offset_and_preserves_incomplete_drafts(self):
        for value in ("", "not a date", "2026-10-25T01:30:00"):
            self.assert_publish_fails(self.workflow_with_nodes([{"id":"wait","type":"wait_duration","label":"Wait","wait_until":value}]), "UTC offset")
        a = self.create_tracked_automation("Exact deadline")
        node = {"id":"wait","type":"wait_duration","label":"Wait","wait_until":"2026-10-25T01:30:00+01:00"}
        self.user_patch("/api/automations/%s" % a["id"], json=self.workflow_with_nodes([node]))
        self.assertEqual(self.user_publish(a["id"])["published"]["nodes"][0], node)

    def test_draft_lifecycle(self):
        created = self.user_post("/api/automations", json={"name": "Welcome Series"})

        self.assertEqual(created["name"], "Welcome Series")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["reentry"], "once")
        self.assertIn("created", created)
        self.assertIn("modified", created)

        automation_id = created["id"]

        found = self.user_get("/api/automations/%s" % automation_id)
        self.assertEqual(found["id"], automation_id)
        self.assertEqual(found["name"], "Welcome Series")
        self.assertEqual(found["reentry"], "once")

        automations = self.user_get("/api/automations")
        self.assertTrue(any(a["id"] == automation_id for a in automations))

        patched = self.user_patch(
            "/api/automations/%s" % automation_id,
            json={"name": "Updated Welcome Series"},
        )
        self.assertEqual(patched["name"], "Updated Welcome Series")
        self.assertEqual(patched["status"], "draft")
        self.assertEqual(patched["reentry"], "once")

        self.user_delete("/api/automations/%s" % automation_id)

        result = self.simulate_get(
            "/api/automations/%s" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 403)

    def test_delete_blocks_previously_published_automation(self):
        created = self.user_post("/api/automations", json={"name": "Do Not Delete"})
        automation_id = created["id"]

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation_id, {"published_at": "2026-07-20T00:00:00Z"})

        result = self.simulate_delete(
            "/api/automations/%s" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)

        self.db.automations.remove(automation_id)

    def test_accepts_valid_draft_workflow(self):
        created = self.user_post("/api/automations", json={"name": "Draft Workflow"})
        automation_id = created["id"]

        draft = {
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

        patched = self.user_patch("/api/automations/%s" % automation_id, json=draft)

        self.assertEqual(patched["entry"], draft["entry"])
        self.assertEqual(patched["draft"], draft["draft"])

        found = self.user_get("/api/automations/%s" % automation_id)
        self.assertEqual(found["draft"]["nodes"][0]["id"], "node_add_tag_1")
        self.assertEqual(found["draft"]["nodes"][0]["draft_tag"], "onboarding")

        patched = self.user_patch(
            "/api/automations/%s" % automation_id,
            json={
                "entry": {
                    "type": "manual",
                },
                "draft": {
                    "nodes": [
                        {
                            "id": "node_add_tag_1",
                            "type": "add_tag",
                            "label": "Add renamed onboarding tag",
                            "draft_tag": "onboarding",
                        },
                        {
                            "id": "node_exit_1",
                            "type": "exit",
                            "label": "Exit renamed automation",
                        },
                    ],
                },
            },
        )

        self.assertEqual(patched["draft"]["nodes"][0]["id"], "node_add_tag_1")
        self.assertEqual(patched["draft"]["nodes"][0]["label"], "Add renamed onboarding tag")
        self.assertEqual(patched["draft"]["nodes"][1]["id"], "node_exit_1")

        self.user_delete("/api/automations/%s" % automation_id)

    def test_rejects_invalid_draft_node_type(self):
        created = self.user_post("/api/automations", json={"name": "Bad Node Type"})
        automation_id = created["id"]

        result = self.simulate_patch(
            "/api/automations/%s" % automation_id,
            json={
                "entry": {
                    "type": "manual",
                },
                "draft": {
                    "nodes": [
                        {
                            "id": "node_wait_1",
                            "type": "wait",
                            "label": "Wait",
                        },
                    ],
                },
            },
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_accepts_valid_reentry_values(self):
        created = self.user_post("/api/automations", json={"name": "Reentry Values"})
        automation_id = created["id"]

        patched = self.user_patch(
            "/api/automations/%s" % automation_id,
            json={"reentry": "multiple"},
        )
        self.assertEqual(patched["reentry"], "multiple")

        patched = self.user_patch(
            "/api/automations/%s" % automation_id,
            json={"reentry": "once"},
        )
        self.assertEqual(patched["reentry"], "once")

        self.user_delete("/api/automations/%s" % automation_id)

    def test_rejects_invalid_reentry_value(self):
        created = self.user_post("/api/automations", json={"name": "Bad Reentry"})
        automation_id = created["id"]

        result = self.simulate_patch(
            "/api/automations/%s" % automation_id,
            json={"reentry": "sometimes"},
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_blocks_other_account_access(self):
        created = self.user_post("/api/automations", json={"name": "Other Account"})
        automation_id = created["id"]
        other_cid = "other-account-cid"

        self.db.execute(
            "update automations set cid = %s where id = %s",
            other_cid,
            automation_id,
        )

        automations = self.user_get("/api/automations")
        self.assertFalse(any(a["id"] == automation_id for a in automations))

        headers = {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

        result = self.simulate_get(
            "/api/automations/%s" % automation_id,
            headers=headers,
        )
        self.assertEqual(result.status_code, 403)

        result = self.simulate_patch(
            "/api/automations/%s" % automation_id,
            json={"name": "Should Not Update"},
            headers=headers,
        )
        self.assertEqual(result.status_code, 403)

        result = self.simulate_delete(
            "/api/automations/%s" % automation_id,
            headers=headers,
        )
        self.assertEqual(result.status_code, 403)

        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation_id,
            other_cid,
        )

    def test_successful_publish(self):
        created = self.user_post("/api/automations", json={"name": "Publish Me"})
        automation_id = created["id"]

        draft = self.valid_workflow()
        self.user_patch("/api/automations/%s" % automation_id, json=draft)

        published = self.user_publish(automation_id)

        self.assertEqual(published["status"], "published")
        self.assertEqual(published["reentry"], "once")
        self.assertEqual(published["published"], self.valid_published_workflow())
        self.assertEqual(published["published_revision"], 1)
        self.assertIn("published_at", published)
        self.assertEqual(published["published_by"], self.user_cookie["uid"])

        result = self.simulate_delete(
            "/api/automations/%s" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_manual_entry_publishes_as_before(self):
        automation = self.create_tracked_automation("Manual Entry Publish")

        self.user_patch("/api/automations/%s" % automation["id"], json=self.valid_workflow())
        published = self.user_publish(automation["id"])

        self.assertEqual(published["published"]["entry"], {"type": "manual"})

    def test_tag_added_entry_with_tag_publishes(self):
        automation = self.create_tracked_automation("Tag Added Entry Publish")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "tag_added",
            "tag": "automation-entry-vip",
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(
            published["published"]["entry"],
            {
                "type": "tag_added",
                "tag": "automation-entry-vip",
            },
        )

    def test_tag_added_entry_missing_tag_fails_publish_validation(self):
        automation = self.create_tracked_automation("Tag Added Entry Missing Tag")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "tag_added",
            "tag": "",
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Tag added entry trigger requires a tag", result.text)

    def test_tag_removed_entry_with_tag_publishes(self):
        automation = self.create_tracked_automation("Tag Removed Entry Publish")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "tag_removed",
            "tag": "automation-entry-lapsed",
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(
            published["published"]["entry"],
            {
                "type": "tag_removed",
                "tag": "automation-entry-lapsed",
            },
        )

    def test_tag_removed_entry_missing_tag_fails_publish_validation(self):
        automation = self.create_tracked_automation("Tag Removed Entry Missing Tag")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "tag_removed",
            "tag": "",
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Tag removed entry trigger requires a tag", result.text)

    def test_list_joined_entry_with_list_publishes(self):
        automation = self.create_tracked_automation("List Joined Entry Publish")
        lst = self.create_contact_list("automation_crud_joined_entry")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "list_joined",
            "list_id": lst["id"],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(
            published["published"]["entry"],
            {
                "type": "list_joined",
                "list_id": lst["id"],
            },
        )

    def test_list_left_entry_with_list_publishes(self):
        automation = self.create_tracked_automation("List Left Entry Publish")
        lst = self.create_contact_list("automation_crud_left_entry")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "list_left",
            "list_id": lst["id"],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(
            published["published"]["entry"],
            {
                "type": "list_left",
                "list_id": lst["id"],
            },
        )

    def test_list_entry_missing_list_id_fails_publish_validation(self):
        automation = self.create_tracked_automation("List Entry Missing List")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "list_joined",
            "list_id": "",
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Joined list entry trigger requires a contact list", result.text)

    def test_list_entry_unknown_list_fails_publish_validation(self):
        automation = self.create_tracked_automation("List Entry Unknown List")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "list_left",
            "list_id": "missing-list-id",
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("List entry trigger must reference a contact list from this account", result.text)

    def test_list_entry_unowned_list_fails_publish_validation(self):
        automation = self.create_tracked_automation("List Entry Unowned List")
        lst = self.create_contact_list("automation_crud_unowned_entry")
        self.db.execute(
            "update lists set cid = %s where id = %s",
            "other-account-cid",
            lst["id"],
        )
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "list_joined",
            "list_id": lst["id"],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("List entry trigger must reference a contact list from this account", result.text)

    def test_segment_entered_entry_with_segment_publishes(self):
        automation = self.create_tracked_automation("Segment Entered Entry Publish")
        segment = self.create_segment("automation_crud_entered_entry")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "segment_entered",
            "segment_id": segment["id"],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(
            published["published"]["entry"],
            {
                "type": "segment_entered",
                "segment_id": segment["id"],
            },
        )

    def test_segment_left_entry_with_segment_publishes(self):
        automation = self.create_tracked_automation("Segment Left Entry Publish")
        segment = self.create_segment("automation_crud_left_segment_entry")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "segment_left",
            "segment_id": segment["id"],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(
            published["published"]["entry"],
            {
                "type": "segment_left",
                "segment_id": segment["id"],
            },
        )

    def test_segment_entry_missing_segment_id_fails_publish_validation(self):
        automation = self.create_tracked_automation("Segment Entry Missing Segment")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "segment_entered",
            "segment_id": "",
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Entered segment entry trigger requires a segment", result.text)

    def test_segment_entry_unknown_segment_fails_publish_validation(self):
        automation = self.create_tracked_automation("Segment Entry Unknown Segment")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "segment_left",
            "segment_id": "missing-segment-id",
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Segment entry trigger must reference a segment from this account", result.text)

    def test_segment_entry_unowned_segment_fails_publish_validation(self):
        automation = self.create_tracked_automation("Segment Entry Unowned Segment")
        segment = self.create_segment("automation_crud_unowned_segment_entry")
        self.db.execute(
            "update segments set cid = %s where id = %s",
            "other-account-cid",
            segment["id"],
        )
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "segment_entered",
            "segment_id": segment["id"],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Segment entry trigger must reference a segment from this account", result.text)

    def test_multi_manual_and_tag_entry_publishes(self):
        automation = self.create_tracked_automation("Multi Manual Tag Entry Publish")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "manual"},
                {"type": "tag_added", "tag": "automation-entry-multi-vip"},
            ],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(published["published"]["entry"], workflow["entry"])

    def test_multi_tag_list_segment_entry_publishes(self):
        automation = self.create_tracked_automation("Multi Entry Publish")
        lst = self.create_contact_list("automation_crud_multi_entry")
        segment = self.create_segment("automation_crud_multi_segment_entry")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "automation-entry-multi-added"},
                {"type": "tag_removed", "tag": "automation-entry-multi-removed"},
                {"type": "list_left", "list_id": lst["id"]},
                {"type": "segment_entered", "segment_id": segment["id"]},
            ],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(published["published"]["entry"], workflow["entry"])

    def test_multi_single_trigger_publishes_as_single_shape(self):
        automation = self.create_tracked_automation("Multi Single Entry Publish")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "automation-entry-single-shape"},
            ],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        published = self.user_publish(automation["id"])

        self.assertEqual(
            published["published"]["entry"],
            {"type": "tag_added", "tag": "automation-entry-single-shape"},
        )

    def test_multi_entry_missing_required_selector_fails(self):
        automation = self.create_tracked_automation("Multi Entry Missing Selector")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "manual"},
                {"type": "tag_removed", "tag": ""},
            ],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Tag removed entry trigger requires a tag", result.text)

    def test_multi_entry_unknown_or_unowned_list_and_segment_fail(self):
        automation = self.create_tracked_automation("Multi Entry Unknown List")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "automation-entry-multi-known"},
                {"type": "list_joined", "list_id": "missing-list-id"},
            ],
        }
        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("List entry trigger must reference a contact list from this account", result.text)

        segment_automation = self.create_tracked_automation("Multi Entry Unknown Segment")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "automation-entry-multi-known"},
                {"type": "segment_left", "segment_id": "missing-segment-id"},
            ],
        }
        self.user_patch("/api/automations/%s" % segment_automation["id"], json=workflow)
        result = self.simulate_post(
            "/api/automations/%s/publish" % segment_automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("Segment entry trigger must reference a segment from this account", result.text)

        unowned_list_automation = self.create_tracked_automation("Multi Entry Unowned List")
        lst = self.create_contact_list("automation_crud_multi_unowned_list")
        self.db.execute(
            "update lists set cid = %s where id = %s",
            "other-account-cid",
            lst["id"],
        )
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "automation-entry-multi-known"},
                {"type": "list_left", "list_id": lst["id"]},
            ],
        }
        self.user_patch("/api/automations/%s" % unowned_list_automation["id"], json=workflow)
        result = self.simulate_post(
            "/api/automations/%s/publish" % unowned_list_automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("List entry trigger must reference a contact list from this account", result.text)

        unowned_segment_automation = self.create_tracked_automation("Multi Entry Unowned Segment")
        segment = self.create_segment("automation_crud_multi_unowned_segment")
        self.db.execute(
            "update segments set cid = %s where id = %s",
            "other-account-cid",
            segment["id"],
        )
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "automation-entry-multi-known"},
                {"type": "segment_entered", "segment_id": segment["id"]},
            ],
        }
        self.user_patch("/api/automations/%s" % unowned_segment_automation["id"], json=workflow)
        result = self.simulate_post(
            "/api/automations/%s/publish" % unowned_segment_automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("Segment entry trigger must reference a segment from this account", result.text)

    def test_multi_entry_duplicate_trigger_fails(self):
        automation = self.create_tracked_automation("Multi Entry Duplicate")
        workflow = self.valid_workflow()
        workflow["entry"] = {
            "type": "multi",
            "triggers": [
                {"type": "tag_added", "tag": "automation-entry-duplicate"},
                {"type": "tag_added", "tag": "automation-entry-duplicate"},
            ],
        }

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Automation entry contains duplicate triggers", result.text)

    def test_publish_validation_failure_does_not_modify_existing_published_data(self):
        created = self.user_post("/api/automations", json={"name": "Publish Failure"})
        automation_id = created["id"]

        draft = self.valid_workflow()
        self.user_patch("/api/automations/%s" % automation_id, json=draft)
        published = self.user_publish(automation_id)

        invalid_draft = self.valid_workflow(draft_tag="")
        self.user_patch("/api/automations/%s" % automation_id, json=invalid_draft)
        before_failed_publish = self.user_get("/api/automations/%s" % automation_id)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)

        found = self.user_get("/api/automations/%s" % automation_id)
        self.assertEqual(found, before_failed_publish)
        self.assertEqual(found["published"], published["published"])
        self.assertEqual(found["published_revision"], published["published_revision"])
        self.assertEqual(found["published_at"], published["published_at"])

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_republish_increments_revision(self):
        created = self.user_post("/api/automations", json={"name": "Republish"})
        automation_id = created["id"]

        self.user_patch(
            "/api/automations/%s" % automation_id,
            json=self.valid_workflow(reentry="multiple"),
        )
        first = self.user_publish(automation_id)

        self.user_patch(
            "/api/automations/%s" % automation_id,
            json=self.valid_workflow(label="Add updated tag", draft_tag="updated", reentry="once"),
        )
        second = self.user_publish(automation_id)

        self.assertEqual(first["published_revision"], 1)
        self.assertEqual(first["published"]["reentry"], "multiple")
        self.assertEqual(second["published_revision"], 2)
        self.assertEqual(second["published"]["reentry"], "once")
        self.assertEqual(second["published"]["nodes"][0]["label"], "Add updated tag")
        self.assertEqual(second["published"]["nodes"][0]["draft_tag"], "updated")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_published_snapshot_is_not_mutated_by_later_draft_edits(self):
        created = self.user_post("/api/automations", json={"name": "Snapshot"})
        automation_id = created["id"]

        self.user_patch("/api/automations/%s" % automation_id, json=self.valid_workflow())
        published = self.user_publish(automation_id)

        self.user_patch(
            "/api/automations/%s" % automation_id,
            json=self.valid_workflow(label="Draft-only change", draft_tag="draft-only"),
        )

        found = self.user_get("/api/automations/%s" % automation_id)
        self.assertEqual(found["published"], published["published"])
        self.assertEqual(found["published"]["nodes"][0]["label"], "Add onboarding tag")
        self.assertEqual(found["draft"]["nodes"][0]["label"], "Draft-only change")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_invalid_stored_reentry_fails_publish_validation(self):
        created = self.user_post("/api/automations", json={"name": "Bad Stored Reentry"})
        automation_id = created["id"]

        self.user_patch("/api/automations/%s" % automation_id, json=self.valid_workflow())

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation_id, {"reentry": "sometimes"})

        before_failed_publish = self.db.automations.get(automation_id)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 400)

        after_failed_publish = self.db.automations.get(automation_id)
        self.assertEqual(after_failed_publish, before_failed_publish)

        self.db.automations.remove(automation_id)

    def test_cross_account_publish_is_blocked(self):
        created = self.user_post("/api/automations", json={"name": "No Publish Access"})
        automation_id = created["id"]
        other_cid = "other-account-cid"

        self.db.execute(
            "update automations set cid = %s where id = %s",
            other_cid,
            automation_id,
        )

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        self.assertEqual(result.status_code, 403)

        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation_id,
            other_cid,
        )

    def test_rejects_extra_draft_node_fields(self):
        created = self.user_post("/api/automations", json={"name": "Extra Field"})
        automation_id = created["id"]

        result = self.simulate_patch(
            "/api/automations/%s" % automation_id,
            json={
                "entry": {
                    "type": "manual",
                },
                "draft": {
                    "nodes": [
                        {
                            "id": "node_exit_1",
                            "type": "exit",
                            "label": "Exit automation",
                            "next": "unexpected",
                        },
                    ],
                },
            },
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_valid_wait_duration_publishes(self):
        created = self.user_post("/api/automations", json={"name": "Wait Duration"})
        automation_id = created["id"]

        self.user_patch("/api/automations/%s" % automation_id, json=self.wait_workflow())
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][0]["type"], "wait_duration")
        self.assertEqual(
            published["published"]["nodes"][0]["duration"],
            {
                "days": 0,
                "hours": 0,
                "minutes": 5,
            },
        )

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_publish_does_not_require_explicit_exit_node(self):
        created = self.user_post("/api/automations", json={"name": "Implicit Completion"})
        automation_id = created["id"]
        workflow = self.valid_workflow()
        workflow["draft"]["nodes"] = [workflow["draft"]["nodes"][0]]

        self.user_patch("/api/automations/%s" % automation_id, json=workflow)
        published = self.user_publish(automation_id)

        self.assertEqual(len(published["published"]["nodes"]), 1)
        self.assertEqual(published["published"]["nodes"][0]["type"], "add_tag")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_valid_remove_tag_node_publishes(self):
        created = self.user_post("/api/automations", json={"name": "Remove Tag"})
        automation_id = created["id"]
        workflow = self.workflow_with_nodes([
            {
                "id": "node_remove_tag_1",
                "type": "remove_tag",
                "label": "Remove old tag",
                "draft_tag": "old-tag",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.user_patch("/api/automations/%s" % automation_id, json=workflow)
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][0]["type"], "remove_tag")
        self.assertEqual(published["published"]["nodes"][0]["draft_tag"], "old-tag")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_remove_tag_missing_tag_fails_publish_validation(self):
        workflow = self.workflow_with_nodes([
            {
                "id": "node_remove_tag_1",
                "type": "remove_tag",
                "label": "Remove old tag",
                "draft_tag": "",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_publish_fails(workflow, "Remove tag nodes must have draft tag configuration.")

    def test_plural_list_schema_and_publish_ownership(self):
        from jsonschema import validate, ValidationError
        from api import automations
        ids = [self.create_contact_list("plural_one")["id"], self.create_contact_list("plural_two")["id"]]
        for action, schema in (("add_to_list", automations.ADD_TO_LIST_NODE_SCHEMA), ("remove_from_list", automations.REMOVE_FROM_LIST_NODE_SCHEMA)):
            node = {"id": "lists", "type": action, "label": "Lists", "list_ids": ids}
            validate(node, schema)
            for fields in ({"list_ids": [ids[0], ids[0]]}, {"list_ids": [7]}, {"list_ids": [""]}, {"list_ids": ids, "list_id": ids[0]}, {"list_ids": [str(i) for i in range(101)]}):
                with self.subTest(action=action, fields=fields), self.assertRaises(ValidationError):
                    validate({**node, **fields}, schema)
            created = self.user_post("/api/automations", json={"name": "Plural lists"})
            self.addCleanup(self.db.automations.remove, created["id"])
            for fields in ({"list_ids": [ids[0], ids[0]]}, {"list_ids": [7]}, {"list_ids": ids, "list_id": ids[0]}):
                result = self.simulate_patch("/api/automations/" + created["id"],
                    headers={"X-Auth-UID": self.user_cookie["uid"], "X-Auth-Cookie": self.user_cookie["id"]},
                    json=self.workflow_with_nodes([{**node, **fields}]))
                self.assertEqual(result.status_code, 400, result.text)
                self.assertEqual(automations._action_lists({**node, **fields}), [])
            self.user_patch("/api/automations/" + created["id"], json=self.workflow_with_nodes([node]))
            published = self.user_publish(created["id"])
            self.assertEqual(published["published"]["nodes"][0], node)
            self.assert_publish_fails(self.workflow_with_nodes([{**node, "list_ids": []}]), "must select a contact list")
            self.assert_publish_fails(self.workflow_with_nodes([{**node, "list_ids": [ids[0], "missing-list"]}]), "from this account")
        foreign = self.create_contact_list("plural_foreign")["id"]
        self.db.execute("update lists set cid = 'other-account' where id = %s", foreign)
        try:
            self.assert_publish_fails(self.workflow_with_nodes([{**node, "list_ids": [ids[0], foreign]}]), "from this account")
        finally:
            self.db.execute("update lists set cid = %s where id = %s", self.user_cookie["cid"], foreign)

    def test_valid_add_to_list_node_publishes(self):
        lst = self.create_contact_list("automation_crud_add_to_list")
        created = self.user_post("/api/automations", json={"name": "Add To List"})
        automation_id = created["id"]
        workflow = self.workflow_with_nodes([
            {
                "id": "node_add_to_list_1",
                "type": "add_to_list",
                "label": "Add to list",
                "list_id": lst["id"],
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.user_patch("/api/automations/%s" % automation_id, json=workflow)
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][0]["type"], "add_to_list")
        self.assertEqual(published["published"]["nodes"][0]["list_id"], lst["id"])

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_valid_remove_from_list_node_publishes(self):
        lst = self.create_contact_list("automation_crud_remove_from_list")
        created = self.user_post("/api/automations", json={"name": "Remove From List"})
        automation_id = created["id"]
        workflow = self.workflow_with_nodes([
            {
                "id": "node_remove_from_list_1",
                "type": "remove_from_list",
                "label": "Remove from list",
                "list_id": lst["id"],
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.user_patch("/api/automations/%s" % automation_id, json=workflow)
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][0]["type"], "remove_from_list")
        self.assertEqual(published["published"]["nodes"][0]["list_id"], lst["id"])

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_list_action_missing_list_id_fails_publish_validation(self):
        workflow = self.workflow_with_nodes([
            {
                "id": "node_add_to_list_1",
                "type": "add_to_list",
                "label": "Add to list",
                "list_id": "",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_publish_fails(workflow, "add_to_list nodes must select a contact list.")

    def test_list_action_unknown_list_fails_publish_validation(self):
        workflow = self.workflow_with_nodes([
            {
                "id": "node_remove_from_list_1",
                "type": "remove_from_list",
                "label": "Remove from list",
                "list_id": "missing-list-id",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_publish_fails(workflow, "must reference a contact list from this account")

    def test_list_action_unowned_list_fails_publish_validation(self):
        lst = self.create_contact_list("automation_crud_unowned_list")
        self.db.execute(
            "update lists set cid = %s where id = %s",
            "other-account-cid",
            lst["id"],
        )
        workflow = self.workflow_with_nodes([
            {
                "id": "node_add_to_list_1",
                "type": "add_to_list",
                "label": "Add to list",
                "list_id": lst["id"],
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_publish_fails(workflow, "must reference a contact list from this account")

    def test_wait_duration_below_five_minutes_fails_publish_validation(self):
        created = self.user_post("/api/automations", json={"name": "Short Wait"})
        automation_id = created["id"]

        self.user_patch(
            "/api/automations/%s" % automation_id,
            json=self.wait_workflow({"days": 0, "hours": 0, "minutes": 4}),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("at least 5 minutes", result.text)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_wait_duration_above_365_days_fails_publish_validation(self):
        created = self.user_post("/api/automations", json={"name": "Long Wait"})
        automation_id = created["id"]

        self.user_patch(
            "/api/automations/%s" % automation_id,
            json=self.wait_workflow({"days": 365, "hours": 0, "minutes": 1}),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("365 days", result.text)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_wait_duration_rejects_extra_duration_fields(self):
        created = self.user_post("/api/automations", json={"name": "Bad Wait Duration"})
        automation_id = created["id"]

        result = self.simulate_patch(
            "/api/automations/%s" % automation_id,
            json=self.wait_workflow(
                {
                    "days": 0,
                    "hours": 0,
                    "minutes": 5,
                    "seconds": 1,
                }
            ),
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_valid_condition_node_publishes(self):
        created = self.user_post("/api/automations", json={"name": "Condition"})
        automation_id = created["id"]

        self.user_patch("/api/automations/%s" % automation_id, json=self.condition_workflow())
        published = self.user_publish(automation_id)

        condition = published["published"]["nodes"][0]
        self.assertEqual(condition["type"], "if_has_tag")
        self.assertEqual(condition["draft_tag"], "vip")
        self.assertEqual(condition["yes_node_id"], "node_add_tag_1")
        self.assertEqual(condition["no_node_id"], "node_exit_1")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_condition_branch_target_can_point_to_explicit_exit(self):
        created = self.user_post("/api/automations", json={"name": "Condition Exit Target"})
        automation_id = created["id"]
        condition = {
            "id": "node_condition_1",
            "type": "if_has_tag",
            "label": "If contact has tag",
            "draft_tag": "vip",
            "yes_node_id": "node_exit_1",
            "no_node_id": "node_exit_1",
        }

        self.user_patch("/api/automations/%s" % automation_id, json=self.condition_workflow(condition))
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][0]["yes_node_id"], "node_exit_1")
        self.assertEqual(published["published"]["nodes"][0]["no_node_id"], "node_exit_1")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_valid_go_to_node_publishes(self):
        created = self.user_post("/api/automations", json={"name": "Go To"})
        automation_id = created["id"]

        self.user_patch("/api/automations/%s" % automation_id, json=self.go_to_workflow())
        published = self.user_publish(automation_id)

        go_to = published["published"]["nodes"][1]
        self.assertEqual(go_to["type"], "go_to")
        self.assertEqual(go_to["label"], "Go to shared step")
        self.assertEqual(go_to["target_node_id"], "node_exit_1")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_go_to_target_can_point_to_explicit_exit(self):
        created = self.user_post("/api/automations", json={"name": "Go To Exit Target"})
        automation_id = created["id"]

        self.user_patch("/api/automations/%s" % automation_id, json=self.go_to_workflow())
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][1]["target_node_id"], "node_exit_1")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_valid_send_email_node_publishes(self):
        automation = self.create_tracked_automation("Valid Send Email")
        email = self.create_automation_email(automation["id"])

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.send_email_workflow(email["id"]),
        )
        published = self.user_publish(automation["id"])

        send_email = published["published"]["nodes"][0]
        self.assertEqual(send_email["type"], "send_email")
        self.assertEqual(send_email["label"], "Send email")
        self.assertEqual(send_email["automation_email_id"], email["id"])

    def test_send_email_missing_email_id_fails_validation(self):
        automation = self.create_tracked_automation("Missing Send Email")

        result = self.simulate_patch(
            "/api/automations/%s" % automation["id"],
            json=self.send_email_workflow(),
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("automation_email_id", result.text)

    def test_send_email_unknown_or_deleted_email_fails_publish_validation(self):
        automation = self.create_tracked_automation("Unknown Send Email")

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.send_email_workflow("missing-email-id"),
        )

        self.assert_existing_publish_fails(automation["id"], "must reference an email from this automation")

    def test_send_email_from_another_automation_fails_publish_validation(self):
        automation = self.create_tracked_automation("Send Email Owner")
        other = self.create_tracked_automation("Send Email Other Automation")
        other_email = self.create_automation_email(other["id"])

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.send_email_workflow(other_email["id"]),
        )

        self.assert_existing_publish_fails(automation["id"], "must reference an email from this automation")

    def test_send_email_from_another_account_fails_publish_validation(self):
        automation = self.create_tracked_automation("Send Email Other Account")
        email = self.create_automation_email(automation["id"])
        self.db.execute(
            "update automation_emails set cid = %s where id = %s",
            "other-account-cid",
            email["id"],
        )

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.send_email_workflow(email["id"]),
        )

        self.assert_existing_publish_fails(automation["id"], "must reference an email from this automation")

    def test_valid_if_opened_email_node_publishes(self):
        automation = self.create_tracked_automation("Valid If Opened Email")
        email = self.create_automation_email(automation["id"])

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.email_engagement_condition_workflow(email["id"], "if_opened_email"),
        )
        published = self.user_publish(automation["id"])

        condition = published["published"]["nodes"][0]
        self.assertEqual(condition["type"], "if_opened_email")
        self.assertEqual(condition["automation_email_id"], email["id"])
        self.assertEqual(condition["yes_node_id"], "node_add_tag_1")
        self.assertEqual(condition["no_node_id"], "node_exit_1")

    def test_valid_if_clicked_email_node_publishes(self):
        automation = self.create_tracked_automation("Valid If Clicked Email")
        email = self.create_automation_email(automation["id"])

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.email_engagement_condition_workflow(email["id"], "if_clicked_email"),
        )
        published = self.user_publish(automation["id"])

        condition = published["published"]["nodes"][0]
        self.assertEqual(condition["type"], "if_clicked_email")
        self.assertEqual(condition["automation_email_id"], email["id"])
        self.assertEqual(condition["yes_node_id"], "node_add_tag_1")
        self.assertEqual(condition["no_node_id"], "node_exit_1")

    def test_email_engagement_condition_missing_email_fails_validation(self):
        automation = self.create_tracked_automation("Missing Email Engagement Email")

        result = self.simulate_patch(
            "/api/automations/%s" % automation["id"],
            json=self.email_engagement_condition_workflow(node_type="if_opened_email"),
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("automation_email_id", result.text)

    def test_email_engagement_condition_unknown_or_deleted_email_fails_publish_validation(self):
        automation = self.create_tracked_automation("Unknown Email Engagement Email")

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.email_engagement_condition_workflow("missing-email-id", "if_opened_email"),
        )

        self.assert_existing_publish_fails(automation["id"], "must reference an email from this automation")

    def test_email_engagement_condition_email_from_another_automation_fails_publish_validation(self):
        automation = self.create_tracked_automation("Email Engagement Owner")
        other = self.create_tracked_automation("Email Engagement Other Automation")
        other_email = self.create_automation_email(other["id"])

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.email_engagement_condition_workflow(other_email["id"], "if_clicked_email"),
        )

        self.assert_existing_publish_fails(automation["id"], "must reference an email from this automation")

    def test_email_engagement_condition_email_from_another_account_fails_publish_validation(self):
        automation = self.create_tracked_automation("Email Engagement Other Account")
        email = self.create_automation_email(automation["id"])
        self.db.execute(
            "update automation_emails set cid = %s where id = %s",
            "other-account-cid",
            email["id"],
        )

        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.email_engagement_condition_workflow(email["id"], "if_opened_email"),
        )

        self.assert_existing_publish_fails(automation["id"], "must reference an email from this automation")

    def assert_email_engagement_condition_publish_fails(self, condition, message):
        automation = self.create_tracked_automation("Invalid Email Engagement Condition")
        email = self.create_automation_email(automation["id"])
        condition = dict(condition)
        condition.setdefault("automation_email_id", email["id"])
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.email_engagement_condition_workflow(condition=condition),
        )

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn(message, result.text)

    def test_email_engagement_condition_missing_yes_or_no_target_fails_publish_validation(self):
        missing_yes = {
            "id": "node_email_condition_1",
            "type": "if_opened_email",
            "label": "If opened email",
            "yes_node_id": "",
            "no_node_id": "node_exit_1",
        }
        self.assert_email_engagement_condition_publish_fails(missing_yes, "yes target")

        missing_no = {
            "id": "node_email_condition_1",
            "type": "if_clicked_email",
            "label": "If clicked email",
            "yes_node_id": "node_add_tag_1",
            "no_node_id": "",
        }
        self.assert_email_engagement_condition_publish_fails(missing_no, "no target")

    def test_email_engagement_condition_target_id_not_found_fails_publish_validation(self):
        condition = {
            "id": "node_email_condition_1",
            "type": "if_opened_email",
            "label": "If opened email",
            "yes_node_id": "missing_node",
            "no_node_id": "node_exit_1",
        }
        self.assert_email_engagement_condition_publish_fails(condition, "yes target")

    def test_email_engagement_condition_self_target_fails_publish_validation(self):
        condition = {
            "id": "node_email_condition_1",
            "type": "if_clicked_email",
            "label": "If clicked email",
            "yes_node_id": "node_email_condition_1",
            "no_node_id": "node_exit_1",
        }
        self.assert_email_engagement_condition_publish_fails(condition, "cannot target themselves")

    def test_email_engagement_condition_branch_cycle_publishes_for_runtime_guard(self):
        automation = self.create_tracked_automation("Email Engagement Cycle")
        email = self.create_automation_email(automation["id"])
        workflow = self.workflow_with_nodes([
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add before condition",
                "draft_tag": "before-condition",
            },
            {
                "id": "node_email_condition_1",
                "type": "if_opened_email",
                "label": "If opened email",
                "automation_email_id": email["id"],
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["published"]["nodes"], workflow["draft"]["nodes"])

    def test_condition_branch_target_can_point_to_go_to_node(self):
        created = self.user_post("/api/automations", json={"name": "Condition Go To Target"})
        automation_id = created["id"]
        workflow = {
            "entry": {
                "type": "manual",
            },
            "draft": {
                "nodes": [
                    {
                        "id": "node_condition_1",
                        "type": "if_has_tag",
                        "label": "If contact has tag",
                        "draft_tag": "vip",
                        "yes_node_id": "node_go_to_1",
                        "no_node_id": "node_exit_1",
                    },
                    {
                        "id": "node_go_to_1",
                        "type": "go_to",
                        "label": "Go to exit",
                        "target_node_id": "node_exit_1",
                    },
                    {
                        "id": "node_exit_1",
                        "type": "exit",
                        "label": "Exit automation",
                    },
                ],
            },
        }

        self.user_patch("/api/automations/%s" % automation_id, json=workflow)
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][0]["yes_node_id"], "node_go_to_1")
        self.assertEqual(published["published"]["nodes"][1]["type"], "go_to")

        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def assert_publish_fails(self, workflow, message):
        created = self.user_post("/api/automations", json={"name": "Invalid Workflow"})
        automation_id = created["id"]
        self.user_patch("/api/automations/%s" % automation_id, json=workflow)

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn(message, result.text)
        self.user_delete("/api/automations/%s" % automation_id)
        return result

    def assert_loop_publishes(self, workflow):
        automation = self.create_tracked_automation("Runtime guarded loop")
        self.user_patch("/api/automations/%s" % automation["id"], json=workflow)
        result = self.user_publish(automation["id"])
        self.assertEqual(result["published"]["nodes"], workflow["draft"]["nodes"])

    def test_condition_yes_branch_cycle_publishes_for_runtime_guard(self):
        workflow = self.workflow_with_nodes([
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add before condition",
                "draft_tag": "before-condition",
            },
            {
                "id": "node_condition_1",
                "type": "if_has_tag",
                "label": "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_loop_publishes(workflow)

    def test_condition_no_branch_cycle_publishes_for_runtime_guard(self):
        workflow = self.workflow_with_nodes([
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add before condition",
                "draft_tag": "before-condition",
            },
            {
                "id": "node_condition_1",
                "type": "if_has_tag",
                "label": "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_exit_1",
                "no_node_id": "node_add_tag_1",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_loop_publishes(workflow)

    def test_linear_cycle_publishes_for_runtime_guard(self):
        workflow = self.workflow_with_nodes([
            {
                "id": "node_wait_1",
                "type": "add_tag",
                "label": "Action before condition",
                "draft_tag": "before-condition",
            },
            {
                "id": "node_condition_1",
                "type": "if_has_tag",
                "label": "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_wait_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_loop_publishes(workflow)

    def test_remove_tag_cycle_publishes_for_runtime_guard(self):
        workflow = self.workflow_with_nodes([
            {
                "id": "node_remove_tag_1",
                "type": "remove_tag",
                "label": "Remove before condition",
                "draft_tag": "before-condition",
            },
            {
                "id": "node_condition_1",
                "type": "if_has_tag",
                "label": "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_remove_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_loop_publishes(workflow)

    def test_list_action_cycle_publishes_for_runtime_guard(self):
        lst = self.create_contact_list("automation_crud_cycle_list")
        workflow = self.workflow_with_nodes([
            {
                "id": "node_add_to_list_1",
                "type": "add_to_list",
                "label": "Add to list before condition",
                "list_id": lst["id"],
            },
            {
                "id": "node_condition_1",
                "type": "if_has_tag",
                "label": "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_add_to_list_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ])

        self.assert_loop_publishes(workflow)

    def test_exit_breaks_cycle_detection_paths(self):
        created = self.user_post("/api/automations", json={"name": "Exit Breaks Paths"})
        automation_id = created["id"]
        workflow = self.workflow_with_nodes([
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add before exit",
                "draft_tag": "before-exit",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
            {
                "id": "node_condition_1",
                "type": "if_has_tag",
                "label": "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
        ])

        self.user_patch("/api/automations/%s" % automation_id, json=workflow)
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][2]["yes_node_id"], "node_add_tag_1")
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def test_implicit_completion_has_no_outgoing_cycle_edge(self):
        created = self.user_post("/api/automations", json={"name": "Implicit Completion No Cycle"})
        automation_id = created["id"]
        workflow = self.workflow_with_nodes([
            {
                "id": "node_condition_1",
                "type": "if_has_tag",
                "label": "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_add_tag_1",
            },
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add final tag",
                "draft_tag": "final-tag",
            },
        ])

        self.user_patch("/api/automations/%s" % automation_id, json=workflow)
        published = self.user_publish(automation_id)

        self.assertEqual(published["published"]["nodes"][-1]["id"], "node_add_tag_1")
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.remove(automation_id)

    def assert_go_to_publish_fails(self, go_to, message):
        created = self.user_post("/api/automations", json={"name": "Invalid Go To"})
        automation_id = created["id"]
        self.user_patch("/api/automations/%s" % automation_id, json=self.go_to_workflow(go_to))

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn(message, result.text)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_go_to_missing_target_fails_publish_validation(self):
        go_to = {
            "id": "node_go_to_1",
            "type": "go_to",
            "label": "Go to shared step",
            "target_node_id": "",
        }
        self.assert_go_to_publish_fails(go_to, "target")

    def test_go_to_unknown_target_fails_publish_validation(self):
        go_to = {
            "id": "node_go_to_1",
            "type": "go_to",
            "label": "Go to shared step",
            "target_node_id": "missing_node",
        }
        self.assert_go_to_publish_fails(go_to, "target must exist")

    def test_go_to_self_target_fails_publish_validation(self):
        go_to = {
            "id": "node_go_to_1",
            "type": "go_to",
            "label": "Go to shared step",
            "target_node_id": "node_go_to_1",
        }
        self.assert_go_to_publish_fails(go_to, "cannot target themselves")

    def test_go_to_backward_cycle_without_wait_publishes_for_runtime_guard(self):
        go_to = {
            "id": "node_go_to_1",
            "type": "go_to",
            "label": "Go to previous step",
            "target_node_id": "node_add_tag_1",
        }
        self.assert_loop_publishes(self.go_to_workflow(go_to))

    def test_backward_cross_branch_go_to_publishes(self):
        automation = self.create_tracked_automation("Cross branch Go to")
        nodes = [
            {"id": "if", "type": "if_has_tag", "label": "Branch", "draft_tag": "vip", "yes_node_id": "yes", "no_node_id": "no"},
            {"id": "yes", "type": "add_tag", "label": "Yes", "draft_tag": "yes"},
            {"id": "end", "type": "exit", "label": "End"},
            {"id": "no", "type": "go_to", "label": "Join Yes", "target_node_id": "yes"},
        ]
        self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow_with_nodes(nodes))
        published = self.user_post("/api/automations/%s/publish" % automation["id"])
        self.assertEqual(published["published"]["nodes"], nodes)

    def test_loop_bypassing_a_wait_publishes_for_runtime_guard(self):
        nodes = [
            {"id": "if", "type": "if_has_tag", "label": "Branch", "draft_tag": "vip", "yes_node_id": "wait", "no_node_id": "go"},
            {"id": "wait", "type": "wait_duration", "label": "Wait", "duration": {"days": 0, "hours": 0, "minutes": 5}},
            {"id": "go", "type": "go_to", "label": "Repeat", "target_node_id": "if"},
        ]
        self.assert_loop_publishes(self.workflow_with_nodes(nodes))

    def assert_condition_publish_fails(self, condition, message):
        created = self.user_post("/api/automations", json={"name": "Invalid Condition"})
        automation_id = created["id"]
        self.user_patch("/api/automations/%s" % automation_id, json=self.condition_workflow(condition))

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation_id,
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn(message, result.text)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_condition_missing_tag_fails_publish_validation(self):
        condition = {
            "id": "node_condition_1",
            "type": "if_has_tag",
            "label": "If contact has tag",
            "draft_tag": "",
            "yes_node_id": "node_add_tag_1",
            "no_node_id": "node_exit_1",
        }
        self.assert_condition_publish_fails(condition, "draft tag")

    def test_condition_missing_yes_or_no_target_fails_publish_validation(self):
        missing_yes = {
            "id": "node_condition_1",
            "type": "if_has_tag",
            "label": "If contact has tag",
            "draft_tag": "vip",
            "yes_node_id": "",
            "no_node_id": "node_exit_1",
        }
        self.assert_condition_publish_fails(missing_yes, "yes target")

        missing_no = {
            "id": "node_condition_1",
            "type": "if_has_tag",
            "label": "If contact has tag",
            "draft_tag": "vip",
            "yes_node_id": "node_add_tag_1",
            "no_node_id": "",
        }
        self.assert_condition_publish_fails(missing_no, "no target")

    def test_condition_target_id_not_found_fails_publish_validation(self):
        condition = {
            "id": "node_condition_1",
            "type": "if_has_tag",
            "label": "If contact has tag",
            "draft_tag": "vip",
            "yes_node_id": "missing_node",
            "no_node_id": "node_exit_1",
        }
        self.assert_condition_publish_fails(condition, "yes target")

    def test_condition_self_target_fails_publish_validation(self):
        condition = {
            "id": "node_condition_1",
            "type": "if_has_tag",
            "label": "If contact has tag",
            "draft_tag": "vip",
            "yes_node_id": "node_condition_1",
            "no_node_id": "node_exit_1",
        }
        self.assert_condition_publish_fails(condition, "cannot target themselves")

    def test_condition_extra_fields_fail_schema_validation(self):
        created = self.user_post("/api/automations", json={"name": "Extra Condition Field"})
        automation_id = created["id"]
        condition = {
            "id": "node_condition_1",
            "type": "if_has_tag",
            "label": "If contact has tag",
            "draft_tag": "vip",
            "yes_node_id": "node_add_tag_1",
            "no_node_id": "node_exit_1",
            "extra": True,
        }

        result = self.simulate_patch(
            "/api/automations/%s" % automation_id,
            json=self.condition_workflow(condition),
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )

        self.assertEqual(result.status_code, 400)
        self.user_delete("/api/automations/%s" % automation_id)

    def test_duplicate_node_ids_rejected_on_draft_save(self):
        automation = self.create_tracked_automation("Node ID integrity")
        path = "/api/automations/%s" % automation["id"]
        saved = self.user_patch(path, json=self.valid_workflow())
        variants = [
            {"type": "add_tag", "draft_tag": "private-tag-value"},
            {"type": "if_has_tag", "draft_tag": "private-tag-value", "yes_node_id": "", "no_node_id": "missing"},
            {"type": "go_to", "target_node_id": ""},
            {"type": "exit"},
        ]
        for variant in variants:
            with self.subTest(node_type=variant["type"]):
                nodes = [
                    {"id": "duplicate_1", "label": "private-label-value", **variant},
                    {"id": "duplicate_1", "type": "exit", "label": "private-other-label"},
                ]
                result = self.simulate_patch(path, json=self.workflow_with_nodes(nodes), headers={
                    "X-Auth-UID": self.user_cookie["uid"], "X-Auth-Cookie": self.user_cookie["id"],
                })
                self.assertEqual(result.status_code, 400, result.text)
                self.assertEqual(result.json["title"], "Input validation error")
                self.assertIn('"duplicate_1"', result.json["description"])
                self.assertNotIn("private-", result.text)
                self.assertEqual(self.user_get(path), saved)

    def test_unique_node_ids_remain_exact_case_sensitive_strings(self):
        automation = self.create_tracked_automation("Exact node IDs")
        nodes = [{"id": node_id, "type": "exit", "label": "Exit"}
                 for node_id in ("Node_A", "node_a", "007", "7")]
        saved = self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow_with_nodes(nodes))
        self.assertEqual(saved["draft"]["nodes"], nodes)
        self.assertEqual(self.user_publish(automation["id"])["published"]["nodes"], nodes)

    def test_unique_incomplete_draft_and_duplicate_repair_remain_saveable(self):
        automation = self.create_tracked_automation("Repair node IDs")
        path = "/api/automations/%s" % automation["id"]
        nodes = [
            {"id": "condition", "type": "if_has_tag", "label": "Condition", "draft_tag": "",
             "yes_node_id": "", "no_node_id": "deleted-target"},
            {"id": "jump", "type": "go_to", "label": "Jump", "target_node_id": ""},
            {"id": "end", "type": "exit", "label": "Exit"},
        ]
        self.assertEqual(self.user_patch(path, json=self.workflow_with_nodes(nodes))["draft"]["nodes"], nodes)
        # Historical corruption remains readable, but even metadata-only saves
        # must not persist an effective draft with duplicate IDs.
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation["id"], {"draft": {"nodes": nodes + [dict(nodes[-1])]}})
        result = self.simulate_patch(path, json={"name": "Changed"}, headers={
            "X-Auth-UID": self.user_cookie["uid"], "X-Auth-Cookie": self.user_cookie["id"],
        })
        self.assertEqual(result.status_code, 400)
        self.assertIn('"end"', result.json["description"])
        self.assertEqual(self.user_get(path)["name"], "Repair node IDs")
        # Equivalent to deleting one duplicate array entry in the existing editor.
        repaired = self.user_patch(path, json={"draft": {"nodes": nodes}})
        self.assertEqual(repaired["draft"]["nodes"], nodes)

    def test_publish_independently_rejects_duplicate_ids_before_target_validation(self):
        automation = self.create_tracked_automation("Historical duplicate IDs")
        path = "/api/automations/%s" % automation["id"]
        self.user_patch(path, json=self.valid_workflow())
        nodes = [
            {"id": "stop", "type": "exit", "label": "Exit"},
            # Unreachable duplicates must be rejected too. Without the ID check,
            # this would first fail as a self-targeting Go to node.
            {"id": "ambiguous", "type": "go_to", "label": "private-label", "target_node_id": "ambiguous"},
            {"id": "ambiguous", "type": "exit", "label": "private-label"},
            {"id": "another", "type": "exit", "label": "Exit"},
            {"id": "another", "type": "exit", "label": "Exit"},
        ]
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation["id"], {"draft": {"nodes": nodes}})
        before = self.user_get(path)
        result = self.simulate_post(path + "/publish", headers={
            "X-Auth-UID": self.user_cookie["uid"], "X-Auth-Cookie": self.user_cookie["id"],
        })
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(result.json["title"], "Automation publish validation failed")
        self.assertIn('"ambiguous"', result.json["description"])
        self.assertIn('"another"', result.json["description"])
        self.assertNotIn("private-label", result.text)
        self.assertEqual(self.user_get(path), before)
