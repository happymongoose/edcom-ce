"""Exit-rule configuration, review binding and publication validation."""
import copy

import falcon
import test_base
from api import automations


class TestAutomationExitRules(test_base.TestBase):
    def setUp(self):
        super().setUp()
        self.cid = self.user_cookie["cid"]
        self.db.set_cid(self.cid)
        self.ids = []
        self.lists = []
        self.addCleanup(self.cleanup_fixtures)

    def cleanup_fixtures(self):
        for table in ("automation_step_runs", "automation_enrolments", "automation_emails", "automations"):
            key = "id" if table == "automations" else "automation_id"
            self.db.execute("delete from %s where %s = any(%%s) and cid = %%s" % (table, key), self.ids, self.cid)
        self.db.execute("delete from userlogs where cid = %s and data->>'link_id' = any(%s)", self.cid, self.ids + self.lists)
        for lid in self.lists:
            self.db.execute(f'delete from contacts."contact_lists_{self.cid}" where list_id = %s', lid)
            self.db.execute("delete from list_domains where list_id = %s", lid)
            self.db.execute("delete from lists where id = %s", lid)

    def headers(self):
        return {"X-Auth-UID": self.user_cookie["uid"], "X-Auth-Cookie": self.user_cookie["id"]}

    def create(self, publish=False):
        a = self.user_post("/api/automations", json={"name": "Disposable exit rule contract test"})
        self.ids.append(a["id"])
        a = self.user_patch("/api/automations/" + a["id"], json={
            "entry": {"type": "manual"},
            "draft": {"nodes": [{"id": "end", "type": "exit", "label": "Exit"}]},
        })
        if publish:
            a = self.user_post("/api/automations/" + a["id"] + "/publish")
        return a

    def patch_rules(self, a, rules):
        return self.user_patch("/api/automations/" + a["id"], json={"exit_rules": rules})

    def rules(self):
        return [{"type": "has_tag", "tags": ["purchased"]}]

    def fingerprint(self, a):
        return automations._automation_fingerprint(automations._automation_publish_inputs(a))

    def test_save_normalizes_tags_without_mutating_live_snapshot(self):
        a = self.create(publish=True)
        original = copy.deepcopy(a["published"])
        saved = self.patch_rules(a, [{"type": "has_tag", "tags": [" Purchased ", "purchased", "VIP"]}])
        self.assertEqual(saved["exit_rules"], [{"type": "has_tag", "tags": ["purchased", "vip"]}])
        self.assertEqual(saved["published"], original)
        self.assertEqual(saved["published_revision"], a["published_revision"])
        self.assertEqual(saved["status"], a["status"])
        reloaded = self.user_get("/api/automations/" + a["id"])
        self.assertEqual(reloaded["exit_rules"], saved["exit_rules"])

    def test_all_four_rule_types_round_trip(self):
        a = self.create()
        rules = [
            {"type": "has_tag", "tags": ["paid"]},
            {"type": "missing_tag", "tags": ["subscribed", "vip"]},
            {"type": "in_list", "list_ids": ["ListA", "lista"]},
            {"type": "not_in_list", "list_ids": ["ListB"]},
        ]
        self.assertEqual(self.patch_rules(a, rules)["exit_rules"], rules)

    def test_invalid_rule_shapes_rejected_without_saving(self):
        a = self.patch_rules(self.create(), self.rules())
        invalid = [None, {}, [None], [{"type": "tag_added", "tags": ["paid"]}],
            [{"type": "has_tag", "tags": []}], [{"type": "missing_tag", "tags": ["   "]}],
            [{"type": "has_tag", "tags": [123]}], [{"type": "has_tag", "tags": ["paid"], "action": "exit"}],
            [{"type": "in_list", "list_ids": [123]}], [{"type": "in_list", "list_ids": ["x", "x"]}],
            [{"type": "not_in_list", "list_ids": [" "]}], [{"type": "in_list", "list_ids": [], "tags": ["x"]}],
            self.rules() * 21, [{"type": "has_tag", "tags": ["x"] * 101}],
        ]
        for rules in invalid:
            with self.subTest(rules=rules):
                result = self.simulate_patch("/api/automations/" + a["id"], json={"exit_rules": rules}, headers=self.headers())
                self.assertEqual(result.status_code, 400, result.text)
                self.assertEqual(self.db.automations.get(a["id"])["exit_rules"], a["exit_rules"])

    def test_list_ids_are_exact_and_case_sensitive(self):
        rules = [{"type": "in_list", "list_ids": ["ABC", "abc", "01", "1"]}]
        self.assertEqual(automations._prepare_exit_rules(rules), rules)

    def test_preparation_does_not_mutate_input(self):
        rules = [{"type": "has_tag", "tags": [" Purchased "]}]
        original = copy.deepcopy(rules)
        automations._prepare_exit_rules(rules)
        self.assertEqual(rules, original)

    def test_publish_requires_review_of_rules_atomically(self):
        a = self.patch_rules(self.create(publish=True), self.rules())
        before = copy.deepcopy(self.db.automations.get(a["id"]))
        result = self.simulate_post("/api/automations/" + a["id"] + "/publish", headers=self.headers())
        self.assertEqual(result.status_code, 409, result.text)
        self.assertIn("requires review", result.text)
        self.assertEqual(self.db.automations.get(a["id"]), before)

    def test_impact_returns_required_review_without_mutation(self):
        a = self.patch_rules(self.create(), self.rules())
        before = copy.deepcopy(self.db.automations.get(a["id"]))
        impact = self.user_get("/api/automations/" + a["id"] + "/publish-impact")
        self.assertEqual(impact["blockers"], [])
        self.assertTrue(impact["exit_review_required"])
        self.assertEqual(impact["rule_exits"]["enrolment_count"], 0)
        self.assertEqual(impact["destinations"][0]["node_id"], "end")
        self.assertEqual(impact["review"]["draft_fingerprint"], self.fingerprint(a))
        self.assertEqual(self.db.automations.get(a["id"]), before)

    def test_legacy_and_explicit_empty_rules_publish_unchanged(self):
        a = self.create()
        fingerprint = self.fingerprint(a)
        saved = self.patch_rules(a, [])
        self.assertEqual(self.fingerprint(saved), fingerprint)
        published = self.user_post("/api/automations/" + a["id"] + "/publish")
        self.assertNotIn("exit_rules", published["published"])
        self.assertEqual(published["published"]["nodes"], a["draft"]["nodes"])

    def test_removing_rules_restores_normal_publication(self):
        a = self.patch_rules(self.create(), self.rules())
        self.patch_rules(a, [])
        result = self.user_post("/api/automations/" + a["id"] + "/publish")
        self.assertEqual(result["published_revision"], 1)

    def test_review_fingerprints_include_rule_content_and_order(self):
        base = self.create()
        a = {**base, "exit_rules": self.rules()}
        self.assertNotEqual(self.fingerprint(base), self.fingerprint(a))
        same = {**base, "exit_rules": [{"tags": ["purchased"], "type": "has_tag"}]}
        self.assertEqual(self.fingerprint(a), self.fingerprint(same))
        self.assertEqual(self.fingerprint(a), self.fingerprint({**a, "modified": "unrelated"}))
        for changed in ([{"type": "missing_tag", "tags": ["purchased"]}], [{"type": "has_tag", "tags": ["other"]}]):
            self.assertNotEqual(self.fingerprint(a), self.fingerprint({**a, "exit_rules": changed}))
        rules = self.rules() + [{"type": "in_list", "list_ids": ["a", "b"]}]
        self.assertNotEqual(self.fingerprint({**base, "exit_rules": rules}), self.fingerprint({**base, "exit_rules": list(reversed(rules))}))

    def test_publish_independently_validates_stored_rules(self):
        a = self.create()
        self.db.automations.patch(a["id"], {"exit_rules": [{"type": "has_tag", "tags": []}]})
        result = self.simulate_post("/api/automations/" + a["id"] + "/publish", headers=self.headers())
        self.assertEqual(result.status_code, 400, result.text)
        self.assertFalse(self.db.automations.get(a["id"]).get("published"))

    def test_list_ownership_checked_at_publication(self):
        lst = self.user_post("/api/lists", json={"name": "Disposable exit rule list"})
        self.lists.append(lst["id"])
        a = self.patch_rules(self.create(), [{"type": "in_list", "list_ids": [lst["id"]]}])
        self.assertEqual(automations._published_snapshot(self.db, a)["exit_rules"], a["exit_rules"])
        self.db.execute("update lists set cid = 'exit-rule-foreign-account' where id = %s", lst["id"])
        with self.assertRaises(falcon.HTTPBadRequest) as context:
            automations._published_snapshot(self.db, a)
        self.assertIn("from this account", context.exception.description)

    def test_patch_cannot_configure_another_accounts_automation(self):
        a = self.create()
        self.db.execute("update automations set cid = 'exit-rule-foreign-account' where id = %s", a["id"])
        try:
            result = self.simulate_patch("/api/automations/" + a["id"], json={"exit_rules": self.rules()}, headers=self.headers())
            self.assertEqual(result.status_code, 403, result.text)
        finally:
            self.db.execute("update automations set cid = %s where id = %s", self.cid, a["id"])
