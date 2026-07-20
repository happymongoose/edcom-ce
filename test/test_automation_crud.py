import test_base


class TestAutomationCRUD(test_base.TestBase):

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

    def test_go_to_backward_target_fails_publish_validation(self):
        go_to = {
            "id": "node_go_to_1",
            "type": "go_to",
            "label": "Go to previous step",
            "target_node_id": "node_add_tag_1",
        }
        self.assert_go_to_publish_fails(go_to, "later node")

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
