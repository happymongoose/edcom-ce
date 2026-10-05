import copy
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import shortuuid
import test_base
from api import automations
from api.shared.db import DB


class TestAutomationPublishImpact(test_base.TestBase):

    def setUp(self):
        super().setUp()
        self.cid = self.user_cookie["cid"]
        self.db.set_cid(self.cid)
        self.created_ids = []
        self.addCleanup(self.cleanup_impact_fixtures)

    def cleanup_impact_fixtures(self):
        # Only rows created by this test; never reset existing server fixtures.
        if self.created_ids:
            for table in ("automation_enrolments", "automation_step_runs", "automations"):
                key = "id" if table == "automations" else "automation_id"
                self.db.execute("delete from %s where %s = any(%%s) and cid = %%s" % (table, key), self.created_ids, self.cid)
            self.db.execute("delete from userlogs where cid = %s and data->>'link_id' = any(%s)", self.cid, self.created_ids)

    def nodes(self):
        return [
            {"id": "old_wait", "type": "wait_duration", "label": "Published wait", "duration": {"days": 0, "hours": 0, "minutes": 5}},
            {"id": "old_tag", "type": "add_tag", "label": "Published tag", "draft_tag": "example"},
            {"id": "keep", "type": "exit", "label": "Keep"},
        ]

    def create_workflow(self, publish=True):
        a = self.user_post("/api/automations", json={"name": "Publish impact test"})
        self.created_ids.append(a["id"])
        a = self.user_patch("/api/automations/" + a["id"], json={
            "entry": {"type": "manual"}, "reentry": "multiple", "draft": {"nodes": self.nodes()},
        })
        return self.user_post("/api/automations/" + a["id"] + "/publish") if publish else a

    def headers(self):
        return {"X-Auth-UID": self.user_cookie["uid"], "X-Auth-Cookie": self.user_cookie["id"]}

    def impact(self, a):
        return self.user_get("/api/automations/" + a["id"] + "/publish-impact")

    def enrolment(self, a, node_id="old_wait", status="ready", **extra):
        data = {"current_node_id": node_id, "status": status, **extra}
        self.db.execute(
            "insert into automation_enrolments (id, cid, automation_id, contact_id, contact_email, data) values (%s, %s, %s, 1, 'not-in-preview@example.com', %s)",
            shortuuid.uuid(), self.cid, a["id"], data,
        )

    def patch(self, a, **data):
        self.db.automations.patch(a["id"], data)

    def codes(self, impact):
        return [item["code"] for item in impact["blockers"]]

    def test_first_publication_and_no_impact(self):
        a = self.create_workflow(publish=False)
        first = self.impact(a)
        self.assertEqual(first["review"]["published_revision"], 0)
        self.assertEqual(first["review"]["published_fingerprint"], automations._automation_fingerprint(None))
        self.assertEqual(first["automation_status"], "draft")
        self.assertEqual(first["sources"], [])
        self.assertEqual(first["blockers"], [])
        self.assertEqual([n["node_id"] for n in first["destinations"]], ["old_wait", "old_tag", "keep"])
        self.user_post("/api/automations/" + a["id"] + "/publish")
        self.enrolment(a)
        current = self.impact(a)
        self.assertEqual(current["sources"], [])
        self.assertEqual(current["blockers"], [])
        self.assertEqual(current["review"]["published_revision"], 1)
        self.assertEqual(first["review"]["draft_fingerprint"], current["review"]["draft_fingerprint"])
        self.assertNotEqual(first["review"]["published_fingerprint"], current["review"]["published_fingerprint"])

    def test_account_isolation(self):
        a = self.create_workflow()
        other = DB()
        try:
            other.set_cid("other-account-cid")
            request = SimpleNamespace(context={"db": other, "admin": False, "api": False})
            import falcon
            with self.assertRaises(falcon.HTTPForbidden):
                automations.AutomationPublishImpact().on_get(request, SimpleNamespace(), a["id"])
        finally:
            other.close()
        response = self.simulate_get("/api/automations/missing-impact-automation/publish-impact", headers=self.headers())
        self.assertEqual(response.status_code, 403)
        # A foreign enrolment with the same automation ID cannot affect counts.
        foreign_id = shortuuid.uuid()
        try:
            self.db.execute("insert into automation_enrolments (id, cid, automation_id, contact_id, contact_email, data) values (%s, 'other-account-cid', %s, 1, 'foreign@example.com', %s)", foreign_id, a["id"], {"status": "running", "current_node_id": "old_wait"})
            self.assertEqual(self.impact(a)["blockers"], [])
        finally:
            self.db.execute("delete from automation_enrolments where id = %s and cid = 'other-account-cid'", foreign_id)

    def test_deleted_sources_use_stable_ids_and_published_labels(self):
        a = self.create_workflow()
        for state in ("ready", "waiting", "held", "paused_ready", "paused_waiting"):
            self.enrolment(a, status=state)
        self.enrolment(a, status="ready")
        self.enrolment(a, node_id="old_tag", status="held")
        self.enrolment(a, node_id="keep")
        self.patch(a, draft={"nodes": [dict(self.nodes()[2], label="Draft renamed"), {"id": "new", "type": "exit", "label": "New"}]})
        result = self.impact(a)
        self.assertEqual(result["sources"], [
            {"node_id": "old_wait", "label": "Published wait", "type": "wait_duration", "enrolment_count": 6,
             "states": {"ready": 2, "waiting": 1, "held": 1, "paused_ready": 1, "paused_waiting": 1}},
            {"node_id": "old_tag", "label": "Published tag", "type": "add_tag", "enrolment_count": 1, "states": {"held": 1}},
        ])
        self.assertEqual(result["blockers"], [])
        self.assertEqual([n["node_id"] for n in result["destinations"]], ["keep", "new"])
        self.patch(a, draft={"nodes": list(reversed(self.nodes()))})
        reordered = self.impact(a)
        self.assertEqual(reordered["sources"], [])
        self.assertEqual([n["node_id"] for n in reordered["destinations"]], ["keep", "old_tag", "old_wait"])

    def test_terminal_history_is_excluded_but_remaining_claims_block(self):
        a = self.create_workflow()
        for status in automations.TERMINAL_ENROLMENT_STATUSES:
            self.enrolment(a, status=status)
        self.patch(a, draft={"nodes": self.nodes()[2:]})
        self.assertEqual(self.impact(a)["sources"], [])
        self.assertEqual(self.impact(a)["blockers"], [])
        self.enrolment(a, status="completed", claim_token="remaining-claim")
        result = self.impact(a)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["blockers"][0]["code"], "execution_claims")
        self.assertEqual(result["blockers"][0]["enrolment_count"], 1)

    def test_stranded_invalid_and_malformed_positions_are_separate(self):
        a = self.create_workflow()
        self.enrolment(a, node_id="OLD_wait", status="held")
        for invalid in (None, "", 7, {"sensitive": "not-returned"}):
            self.enrolment(a, node_id=invalid)
        self.enrolment(a, status="unexpected-state")
        self.enrolment(a, status={"private": "not-returned"})
        result = self.impact(a)
        self.assertEqual(result["sources"], [])
        self.assertEqual(self.codes(result).count("already_stranded"), 1)
        self.assertEqual(self.codes(result).count("invalid_current_position"), 4)
        self.assertEqual(self.codes(result).count("unsupported_enrolment_state"), 2)
        self.assertNotIn("not-returned", str(result))
        self.assertNotIn("not-in-preview@example.com", str(result))
        # Reintroducing a missing position in the proposal does not reclassify it as a new deletion.
        self.patch(a, draft={"nodes": self.nodes() + [{"id": "OLD_wait", "type": "exit", "label": "Reintroduced"}, {"id": "7", "type": "exit", "label": "String ID"}]})
        self.assertIn("already_stranded", self.codes(self.impact(a)))
        self.assertEqual(self.codes(self.impact(a)).count("invalid_current_position"), 4)

    def test_claims_running_states_and_retained_waits(self):
        a = self.create_workflow()
        self.enrolment(a, status="running", running_status="waiting", claimed_at="2000-01-01T00:00:00Z")
        self.enrolment(a, node_id="keep", claim_token="stale-token", claimed_at="2000-01-01T00:00:00Z")
        self.enrolment(a, status="waiting")
        self.enrolment(a, status="paused_waiting")
        self.patch(a, draft={"nodes": [{"id": "old_wait", "type": "exit", "label": "Changed"}] + self.nodes()[1:]})
        result = self.impact(a)
        self.assertEqual(next(b for b in result["blockers"] if b["code"] == "execution_claims")["enrolment_count"], 2)
        self.assertEqual(self.codes(result).count("incompatible_retained_wait"), 2)
        self.patch(a, draft={"nodes": self.nodes()[1:]})
        result = self.impact(a)
        self.assertNotIn("incompatible_retained_wait", self.codes(result))
        self.assertEqual(result["sources"][0]["states"]["running"], 1)

    def test_invalid_proposal_uses_authoritative_validation_and_no_destinations(self):
        a = self.create_workflow()
        examples = [
            [self.nodes()[0], self.nodes()[0]],
            [{"id": "jump", "type": "go_to", "label": "Jump", "target_node_id": "missing"}],
            [dict(self.nodes()[0], duration={"days": 0, "hours": 0, "minutes": 1})],
            [{"id": "condition", "type": "if_has_tag", "label": "Condition", "draft_tag": "x", "yes_node_id": "condition", "no_node_id": "condition"}],
        ]
        for nodes in examples:
            with self.subTest(nodes=nodes):
                self.patch(a, draft={"nodes": nodes})
                result = self.impact(a)
                self.assertEqual(result["destinations"], [])
                self.assertEqual(result["sources"], [])
                self.assertIn("invalid_proposed_workflow", self.codes(result))
                publish = self.simulate_post("/api/automations/" + a["id"] + "/publish", headers=self.headers())
                self.assertEqual(publish.status_code, 400)
                blocker = next(b for b in result["blockers"] if b["code"] == "invalid_proposed_workflow")
                self.assertEqual(blocker["title"], publish.json["title"])
                self.assertEqual(blocker["description"], automations._bounded_error_text(publish.json["description"]))

    def test_malformed_published_nodes_are_unsupported_without_ambiguous_mapping(self):
        a = self.create_workflow()
        self.enrolment(a)
        self.patch(a, published={"nodes": [self.nodes()[0], self.nodes()[0]]})
        result = self.impact(a)
        self.assertIn("unsupported_published_workflow", self.codes(result))
        self.assertEqual(result["sources"], [])

    def test_fingerprints_sort_objects_preserve_arrays_and_meaningful_values(self):
        left = {"entry": {"type": "manual", "other": False}, "draft": {"nodes": [{"id": "A", "label": "One"}, {"id": "a", "label": "Two"}]}}
        right = {"draft": {"nodes": [{"label": "One", "id": "A"}, {"label": "Two", "id": "a"}]}, "entry": {"other": False, "type": "manual"}}
        fingerprint = automations._automation_fingerprint
        self.assertEqual(fingerprint(left), fingerprint(right))
        for value in (None, 0, "false", ""):
            changed = copy.deepcopy(left)
            changed["entry"]["other"] = value
            self.assertNotEqual(fingerprint(left), fingerprint(changed))
        right["draft"]["nodes"].reverse()
        self.assertNotEqual(fingerprint(left), fingerprint(right))

    def test_review_tracks_all_saved_publish_inputs_but_not_unrelated_metadata(self):
        a = self.create_workflow()
        before = self.impact(a)["review"]
        changes = {
            "name": "Changed", "entry": {"type": "tag_added", "tag": "different"},
            "reentry": "once", "draft": {"nodes": list(reversed(self.nodes()))},
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                self.patch(a, **{field: value})
                changed = self.impact(a)["review"]
                self.assertNotEqual(before["draft_fingerprint"], changed["draft_fingerprint"])
                self.assertEqual(before["published_fingerprint"], changed["published_fingerprint"])
                self.patch(a, **{field: a[field]})
        self.patch(a, modified="unrelated", published_at="unrelated", status="paused", custom_metadata={"value": 1})
        self.assertEqual(before, self.impact(a)["review"])
        snapshot = copy.deepcopy(a["published"])
        snapshot["nodes"][0]["label"] = "Different snapshot"
        self.patch(a, published=snapshot, published_revision=2)
        changed = self.impact(a)["review"]
        self.assertEqual(before["draft_fingerprint"], changed["draft_fingerprint"])
        self.assertNotEqual(before["published_fingerprint"], changed["published_fingerprint"])
        self.assertEqual(changed["published_revision"], 2)

    def test_preview_does_not_mutate_persistence_or_write_history(self):
        a = self.create_workflow()
        self.enrolment(a, status="paused_waiting", wait={"remaining_seconds": 41}, retry_count=3)
        self.patch(a, draft={"nodes": self.nodes()[1:]}, status="paused")
        def persisted():
            return (
                self.db.automations.get(a["id"]),
                self.db.execute("select id, data from automation_enrolments where cid = %s and automation_id = %s order by id", self.cid, a["id"]).fetchall(),
                self.db.execute("select id, data from userlogs where cid = %s and data->>'link_id' = %s order by id", self.cid, a["id"]).fetchall(),
                self.db.execute("select id, data from automation_step_runs where cid = %s and automation_id = %s order by id", self.cid, a["id"]).fetchall(),
            )
        before = persisted()
        first = self.impact(a)
        second = self.impact(a)
        self.assertEqual(first, second)
        self.assertEqual(persisted(), before)

    def test_preview_waits_for_publication_and_reads_one_committed_workflow(self):
        a = self.create_workflow()
        publisher, worker = DB(), DB()
        for db in (publisher, worker):
            db.set_cid(self.cid)
            self.addCleanup(db.close)
        original_single = worker.single
        def observed_single(sql, *args, **kwargs):
            if sql.startswith("select id from automations") and "for update" in sql:
                worker.server_pid = original_single("select pg_backend_pid()")
                worker.execute("set local statement_timeout = '8s'")
            return original_single(sql, *args, **kwargs)
        worker.single = observed_single
        def request(db):
            return SimpleNamespace(context={"db": db, "uid": self.user_cookie["uid"], "admin": False, "api": False})
        def preview():
            req = request(worker)
            automations.AutomationPublishImpact().on_get(req, SimpleNamespace(), a["id"])
            return req.context["result"]
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(publisher, self.cid, a["id"]):
                future = pool.submit(preview)
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    pid = worker.__dict__.get("server_pid")
                    if pid and publisher.single("select pg_backend_pid() = any(pg_blocking_pids(%s))", pid):
                        break
                    time.sleep(0.01)
                else:
                    self.fail("Preview did not wait for the independent publication transaction")
                publisher.automations.patch(a["id"], {"draft": {"nodes": self.nodes()[2:]}})
                automations.AutomationPublish().on_post(request(publisher), SimpleNamespace(), a["id"])
            result = future.result(timeout=5)
        self.assertEqual(result, self.impact(a))
        self.assertEqual(result["review"]["published_revision"], 2)
        self.assertEqual([n["node_id"] for n in result["destinations"]], ["keep"])
