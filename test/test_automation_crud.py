import test_base


class TestAutomationCRUD(test_base.TestBase):

    def test_draft_lifecycle(self):
        created = self.user_post("/api/automations", json={"name": "Welcome Series"})

        self.assertEqual(created["name"], "Welcome Series")
        self.assertEqual(created["status"], "draft")
        self.assertIn("created", created)
        self.assertIn("modified", created)

        automation_id = created["id"]

        found = self.user_get("/api/automations/%s" % automation_id)
        self.assertEqual(found["id"], automation_id)
        self.assertEqual(found["name"], "Welcome Series")

        automations = self.user_get("/api/automations")
        self.assertTrue(any(a["id"] == automation_id for a in automations))

        patched = self.user_patch(
            "/api/automations/%s" % automation_id,
            json={"name": "Updated Welcome Series"},
        )
        self.assertEqual(patched["name"], "Updated Welcome Series")
        self.assertEqual(patched["status"], "draft")

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
