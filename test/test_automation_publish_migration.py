import copy
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import falcon
import shortuuid
import test_base
from api import automations
from api.shared.db import DB


class TestAutomationPublishMigration(test_base.TestBase):
    def setUp(self):
        super().setUp()
        self.cid = self.user_cookie["cid"]
        self.db.set_cid(self.cid)
        self.automation_ids = []
        self.contact_ids = []
        self.addCleanup(self.cleanup_fixtures)

    def cleanup_fixtures(self):
        # Only this test's newly-created records, never existing server data.
        if self.automation_ids:
            for table in ("automation_email_events", "automation_step_runs", "automation_enrolments", "automation_emails", "automations"):
                key = "id" if table == "automations" else "automation_id"
                self.db.execute("delete from %s where cid = %%s and %s = any(%%s)" % (table, key), self.cid, self.automation_ids)
            self.db.execute("delete from userlogs where cid = %s and data->>'link_id' = any(%s)", self.cid, self.automation_ids)
        if self.contact_ids:
            self.db.execute('delete from contacts."contacts_%s" where contact_id = any(%%s)' % self.cid, self.contact_ids)

    def headers(self):
        return {"X-Auth-UID": self.user_cookie["uid"], "X-Auth-Cookie": self.user_cookie["id"]}

    def nodes(self):
        return [
            {"id": "old_a", "type": "wait_duration", "label": "Old A", "duration": {"days": 0, "hours": 0, "minutes": 5}},
            {"id": "old_b", "type": "add_tag", "label": "Old B", "draft_tag": "old-tag"},
            {"id": "dest", "type": "wait_duration", "label": "New wait", "duration": {"days": 2, "hours": 0, "minutes": 0}},
            {"id": "end", "type": "exit", "label": "Exit"},
        ]

    def create(self, paused=False):
        a = self.user_post("/api/automations", json={"name": "Migration test"})
        self.automation_ids.append(a["id"])
        self.user_patch(self.path(a), json={"entry": {"type": "manual"}, "reentry": "multiple", "draft": {"nodes": self.nodes()}})
        a = self.user_post(self.path(a) + "/publish")
        if paused:
            a = self.user_post(self.path(a) + "/pause")
        return a

    def path(self, a):
        return "/api/automations/" + a["id"]

    def add_enrolment(self, a, node="old_a", status="ready", **extra):
        email = "migration-%s@example.com" % shortuuid.uuid().lower()
        contact_id = self.db.single('insert into contacts."contacts_%s" (email, added, props) values (%%s, 0, %%s) returning contact_id' % self.cid, email, {})
        self.contact_ids.append(contact_id)
        eid = shortuuid.uuid()
        data = {"status": status, "current_node_id": node, "source": "manual", "created": "2026-01-01T00:00:00Z", "published_revision": 1, **extra}
        self.db.execute("insert into automation_enrolments (id, cid, automation_id, contact_id, contact_email, data) values (%s, %s, %s, %s, %s, %s)", eid, self.cid, a["id"], contact_id, email, data)
        return eid

    def state(self, eid):
        return self.db.single("select data from automation_enrolments where cid = %s and id = %s", self.cid, eid)

    def review(self, a, resolutions=None):
        self.user_patch(self.path(a), json={"draft": {"nodes": self.nodes()[2:]}})
        return {"request_id": shortuuid.uuid(), "review": self.user_get(self.path(a) + "/publish-impact")["review"], "resolutions": resolutions if resolutions is not None else {"old_a": {"action": "move", "destination_node_id": "dest"}}}

    def submit(self, a, request):
        return self.simulate_post(self.path(a) + "/publish", json=request, headers=self.headers())

    def committed(self, a, request):
        result = self.submit(a, request)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json

    def snapshot(self, a):
        return (
            self.db.automations.get(a["id"]),
            self.db.execute("select id, data from automation_enrolments where cid = %s and automation_id = %s order by id", self.cid, a["id"]).fetchall(),
            self.db.execute("select id, data from userlogs where cid = %s and data->>'link_id' = %s order by id", self.cid, a["id"]).fetchall(),
            self.db.execute("select id, data from automation_step_runs where cid = %s and automation_id = %s order by id", self.cid, a["id"]).fetchall(),
        )

    def assert_refused(self, a, request, status=409):
        before = self.snapshot(a)
        result = self.submit(a, request)
        self.assertEqual(result.status_code, status, result.text)
        self.assertEqual(self.snapshot(a), before)
        return result

    def request_context(self, db, request=None):
        return SimpleNamespace(context={"db": db, "uid": self.user_cookie["uid"], "admin": False, "api": False, "impersonating": True, "doc": request})

    def call(self, db, a, request):
        req = self.request_context(db, request)
        automations.AutomationPublish().on_post(req, SimpleNamespace(), a["id"])
        return req.context["result"]

    def new_db(self):
        db = DB()
        db.set_cid(self.cid)
        original = db.single
        def observed(sql, *args, **kwargs):
            if sql.startswith("select id from automations") and "for update" in sql:
                db.server_pid = original("select pg_backend_pid()")
                db.execute("set local statement_timeout = '8s'")
            return original(sql, *args, **kwargs)
        db.single = observed
        self.addCleanup(db.close)
        return db

    def assert_waiting(self, owner, worker):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            pid = worker.__dict__.get("server_pid")
            if pid and owner.single("select pg_backend_pid() = any(pg_blocking_pids(%s))", pid):
                return
            time.sleep(.01)
        self.fail("Independent connection did not wait on the coordination lock")

    def test_email_reservations_serialize_across_independent_connections(self):
        a = self.create()
        eid = self.add_enrolment(a)
        contact_id = self.db.single("select contact_id from automation_enrolments where id = %s", eid)
        runs = [shortuuid.uuid(), shortuuid.uuid()]
        for run in runs:
            automations._insert_step_run(self.db, self.cid, a["id"], eid, contact_id, "email", "send_email", {"id": run, "status": "running", "created": automations._utc_now()})
        owner, worker = self.new_db(), self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(owner, self.cid, a["id"]):
                self.assertTrue(automations._reserve_automation_email(owner, self.cid, a["id"], contact_id, "owned-email", runs[0]))
                future = pool.submit(automations._reserve_automation_email, worker, self.cid, a["id"], contact_id, "owned-email", runs[1])
                self.assert_waiting(owner, worker)
            with self.assertRaises(falcon.HTTPBadRequest) as raised:
                future.result(timeout=5)
            self.assertEqual(raised.exception.title, "Automation email send pending")
        automations._patch_step_run(self.db, self.cid, runs[0], {"email_delivery_status": "accepted", "email_sent_at": automations._utc_now()})
        self.assertFalse(automations._reserve_automation_email(worker, self.cid, a["id"], contact_id, "owned-email", runs[1]))
        # Different owned emails are independent, and another account cannot reserve.
        self.assertTrue(automations._reserve_automation_email(worker, self.cid, a["id"], contact_id, "another-email", runs[1]))
        with self.assertRaises(falcon.HTTPForbidden):
            automations._reserve_automation_email(worker, "other-account", a["id"], contact_id, "owned-email", runs[1])

    def test_explicit_fresh_migration_clears_visit_history_but_not_unrelated_enrolments(self):
        a = self.create()
        moved = self.add_enrolment(a, visited_node_ids=["dest", "old_a"], transitions_without_wait=10)
        retained = self.add_enrolment(a, node="dest", visited_node_ids=["dest"], transitions_without_wait=5)
        self.committed(a, self.review(a))
        self.assertEqual(self.state(moved)["visited_node_ids"], [])
        self.assertEqual(self.state(moved)["transitions_without_wait"], 0)
        self.assertEqual(self.state(retained)["visited_node_ids"], ["dest"])

    def test_move_and_immediate_exit_multiple_sources_all_supported_states(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                a = self.create(paused)
                moved = [self.add_enrolment(a, status=s) for s in ("ready", "waiting", "held", "paused_ready", "paused_waiting")]
                exited = [self.add_enrolment(a, node="old_b", status=s) for s in ("ready", "waiting", "held", "paused_ready", "paused_waiting")]
                held = self.add_enrolment(a, node="end", status="held")
                untouched = self.state(held)
                terminals = [self.add_enrolment(a, status=s) for s in automations.TERMINAL_ENROLMENT_STATUSES]
                history = {eid: self.state(eid) for eid in terminals}
                request = self.review(a, {"old_a": {"action": "move", "destination_node_id": "dest"}, "old_b": {"action": "exit"}})
                result = self.committed(a, request)
                self.assertEqual(result["status"], "paused" if paused else "published")
                self.assertEqual([x["enrolment_count"] for x in result["publication_receipt"]["outcomes"]], [5, 5])
                for eid in moved:
                    state = self.state(eid)
                    self.assertEqual(state["current_node_id"], "dest")
                    self.assertEqual(state["status"], "paused_ready" if paused else "ready")
                    self.assertEqual(state["migration_events"][0]["published_revision"], 2)
                for eid in exited:
                    self.assertEqual(self.state(eid)["status"], "exited")
                    self.assertEqual(self.state(eid)["current_node_id"], "old_b")
                self.assertEqual(self.state(held), untouched)
                self.assertEqual({eid: self.state(eid) for eid in terminals}, history)
                if paused:
                    self.user_post(self.path(a) + "/resume")
                    for eid in moved:
                        self.assertEqual(self.state(eid)["status"], "ready")
                    for eid in exited:
                        self.assertEqual(self.state(eid)["status"], "exited")

    def test_fresh_state_preserves_provenance_and_previous_history(self):
        a = self.create(paused=True)
        extra = {key: "old" for key in automations._retry_clear_patch()}
        extra.update({"wait": {"remaining_seconds": 7, "frozen_wake_at": "old"}, "wake_at": "old", "paused_at": "old", "resumed_at": "old", "claimed_at": "obsolete", "claimed_node_id": "old_a", "claimed_published_revision": 1, "running_status": "waiting", "trigger_correlation_id": "correlation", "trigger_depth": 3, "admin_recovered_at": "earlier", "admin_recovered_by_uid": "admin", "admin_recovery_action": "clear_stale_enrolment_claims"})
        eid = self.add_enrolment(a, status="paused_waiting", **extra)
        previous = self.state(eid)
        contact_id = self.db.single("select contact_id from automation_enrolments where id = %s", eid)
        sid = shortuuid.uuid()
        automations._insert_step_run(self.db, self.cid, a["id"], eid, contact_id, "old_b", "send_email", {"id": sid, "status": "succeeded", "created": "2026-01-01T00:00:00Z"})
        self.db.execute("insert into automation_email_events (id,cid,contact_id,contact_email,automation_id,automation_email_id,enrolment_id,send_node_id,send_step_run_id,event_type,ts,data) values (%s,%s,%s,'history@example.com',%s,'old-email',%s,'old_b',%s,'open',now(),%s)", shortuuid.uuid(), self.cid, contact_id, a["id"], eid, sid, {})
        events_before = self.db.execute("select * from automation_email_events where automation_id = %s", a["id"]).fetchall()
        steps_before = self.snapshot(a)[3]
        result = self.committed(a, self.review(a))
        state = self.state(eid)
        for key in list(automations._retry_clear_patch()) + list(automations._claim_clear_patch()) + ["wait", "wake_at", "resumed_at"]:
            self.assertIsNone(state[key], key)
        self.assertEqual(state["paused_at"], result["publication_receipt"]["created"])
        for key in ("created", "source", "published_revision", "trigger_correlation_id", "trigger_depth", "admin_recovered_at", "admin_recovered_by_uid", "admin_recovery_action"):
            self.assertEqual(state[key], previous[key], key)
        self.assertEqual(self.snapshot(a)[3], steps_before)
        self.assertEqual(self.db.execute("select * from automation_email_events where automation_id = %s", a["id"]).fetchall(), events_before)
        req = self.request_context(self.db)
        automations.AutomationHistory().on_get(req, SimpleNamespace(), a["id"])
        migration = [e for e in req.context["result"]["events"] if e["type"] == "migration"]
        self.assertEqual(len(migration), 1)
        self.assertNotIn("contact_email", migration[0])
        self.assertEqual(migration[0]["previous_status"], "paused_waiting")
        self.assertEqual(migration[0]["resulting_status"], "paused_ready")
        self.assertEqual(migration[0]["enrolment_id"], eid)

    def test_wait_and_exit_destinations_execute_later_not_during_publish(self):
        for destination in ("dest", "end"):
            with self.subTest(destination=destination):
                a = self.create()
                eid = self.add_enrolment(a, status="waiting", wait={"remaining_seconds": 1}, wake_at="old")
                request = self.review(a, {"old_a": {"action": "move", "destination_node_id": destination}})
                with patch.object(automations, "_run_next_automation_enrolment") as run, patch.object(automations, "send_backend_mail") as send, patch.object(automations.contacts, "add_tag") as tag:
                    self.committed(a, request)
                    run.assert_not_called(); send.assert_not_called(); tag.assert_not_called()
                self.assertEqual(self.state(eid)["status"], "ready")
                self.assertEqual(self.snapshot(a)[3], [])
                result = automations._run_next_automation_enrolment(self.db, self.cid, a["id"], eid)
                state = self.state(eid)
                if destination == "dest":
                    self.assertEqual(state["status"], "waiting")
                    self.assertEqual(state["wait"]["duration"], self.nodes()[2]["duration"])
                    self.assertEqual(result["step_run"]["action"], "wait_start")
                else:
                    self.assertEqual(state["status"], "exited")
                self.assertEqual(len(self.snapshot(a)[3]), 1)

    def test_missing_invalid_and_zero_count_resolutions(self):
        a = self.create()
        self.add_enrolment(a)
        request = self.review(a)
        for choices in ({}, {"old_a": {"action": "move", "destination_node_id": "DEST"}}, {"dest": {"action": "exit"}}, {"missing": {"action": "exit"}}):
            with self.subTest(choices=choices):
                bad = dict(request, resolutions=choices)
                self.assert_refused(a, bad, 409 if not choices else 400)
        request["resolutions"]["old_b"] = {"action": "exit"}
        result = self.committed(a, request)
        self.assertEqual(result["publication_receipt"]["outcomes"][1]["enrolment_count"], 0)

    def test_strict_request_schema(self):
        a = self.create()
        self.add_enrolment(a)
        request = self.review(a)
        for choice in ({"action": "move"}, {"action": "exit", "destination_node_id": "dest"}, {"action": "move", "destination_node_id": 7}, {"action": "exit", "extra": True}, {"action": "other"}):
            self.assert_refused(a, dict(request, resolutions={"old_a": choice}), 400)
        for bad in ({}, dict(request, extra=True), dict(request, request_id=""), dict(request, resolutions={"bad id": {"action": "exit"}})):
            self.assert_refused(a, bad, 400)

    def test_stale_reviews_and_changed_counts(self):
        for change in ("draft", "snapshot", "revision"):
            with self.subTest(change=change):
                a = self.create()
                self.add_enrolment(a)
                request = self.review(a)
                if change == "draft":
                    self.user_patch(self.path(a), json={"name": "Different"})
                elif change == "snapshot":
                    snapshot = copy.deepcopy(a["published"])
                    snapshot["nodes"][0]["label"] = "Changed"
                    self.db.automations.patch(a["id"], {"published": snapshot})
                else:
                    self.db.automations.patch(a["id"], {"published_revision": 2})
                self.assertIn("stale", self.assert_refused(a, request).json["title"])
        a = self.create()
        self.add_enrolment(a)
        request = self.review(a)
        self.add_enrolment(a)
        self.assertEqual(self.committed(a, request)["publication_receipt"]["outcomes"][0]["enrolment_count"], 2)

    def test_new_source_requires_review_and_emptied_source_is_accepted(self):
        a = self.create()
        eid = self.add_enrolment(a)
        request = self.review(a)
        other = self.add_enrolment(a, node="old_b")
        self.assertIn("old_b", self.assert_refused(a, request).text)
        self.db.execute("update automation_enrolments set data = data || %s where id = %s", {"status": "completed"}, eid)
        request["resolutions"]["old_b"] = {"action": "exit"}
        result = self.committed(a, request)
        self.assertEqual([o["enrolment_count"] for o in result["publication_receipt"]["outcomes"]], [0, 1])
        self.assertEqual(self.state(other)["status"], "exited")

    def test_existing_blockers_cannot_be_bypassed_by_resolutions(self):
        cases = [("running", "old_a", {}), ("ready", "old_a", {"claim_token": "stale", "claimed_at": "2000-01-01T00:00:00Z"}), ("held", "missing", {}), ("invalid", "old_a", {}), ("ready", None, {})]
        for status, node, extra in cases:
            with self.subTest(status=status, node=node):
                a = self.create()
                self.add_enrolment(a, node=node, status=status, **extra)
                self.assert_refused(a, self.review(a))
        a = self.create()
        self.add_enrolment(a, node="dest", status="waiting")
        request = self.review(a, {})
        nodes = self.nodes()[2:]
        nodes[0] = {"id": "dest", "type": "exit", "label": "Not a wait"}
        self.user_patch(self.path(a), json={"draft": {"nodes": nodes}})
        request["review"] = self.user_get(self.path(a) + "/publish-impact")["review"]
        self.assert_refused(a, request)

    def test_receipt_retries_and_generic_patch_protection(self):
        a = self.create()
        eid = self.add_enrolment(a)
        request = self.review(a)
        first = self.committed(a, request)
        before = self.snapshot(a)
        with patch.object(automations, "_migrate_publish_enrolments", side_effect=AssertionError("must not replay")):
            second = self.committed(a, copy.deepcopy(request))
        self.assertEqual(second["publication_receipt"], first["publication_receipt"])
        self.assertEqual(self.snapshot(a), before)
        conflict = copy.deepcopy(request)
        conflict["resolutions"]["old_a"] = {"action": "exit"}
        self.assert_refused(a, conflict)
        response = self.simulate_patch(self.path(a), json={"publication_receipt": {"request_id": "forged"}, "name": "Forged"}, headers=self.headers())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(a), before)
        self.user_post(self.path(a) + "/publish")
        self.assert_refused(a, request)
        self.assertEqual(len(self.state(eid)["migration_events"]), 1)

    def test_account_isolation_before_receipt_replay(self):
        a = self.create()
        self.add_enrolment(a)
        request = self.review(a)
        self.committed(a, request)
        foreign = self.new_db()
        foreign.set_cid("other-account-cid")
        with self.assertRaises(falcon.HTTPForbidden):
            self.call(foreign, a, request)

    def test_rollback_after_partial_migration_history_and_audit_failures(self):
        for failure in ("partial", "history", "audit"):
            with self.subTest(failure=failure):
                a = self.create()
                self.add_enrolment(a)
                self.add_enrolment(a, node="old_b")
                request = self.review(a, {"old_a": {"action": "move", "destination_node_id": "dest"}, "old_b": {"action": "exit"}})
                before = self.snapshot(a)
                original = automations._record_publish_migration
                calls = []
                def fail_history(*args, **kwargs):
                    original(*args, **kwargs)
                    calls.append(True)
                    if failure == "history" or len(calls) == 2:
                        raise RuntimeError("injected failure")
                target = "user_log" if failure == "audit" else "_record_publish_migration"
                original_audit = automations.user_log
                def fail_audit(*args, **kwargs):
                    original_audit(*args, **kwargs)
                    raise RuntimeError("injected failure after audit insert")
                effect = fail_audit if failure == "audit" else fail_history
                with patch.object(automations, target, side_effect=effect):
                    with self.assertRaises(RuntimeError):
                        self.call(self.db, a, request)
                self.assertEqual(self.snapshot(a), before)
                self.committed(a, request)

    def test_independent_connection_enrolment_is_reassessed_before_commit(self):
        a = self.create()
        eid = self.add_enrolment(a, node="end", status="completed")
        contact_id, email = self.db.row("select contact_id, contact_email from automation_enrolments where id = %s", eid)
        request = self.review(a)
        creator, publisher = self.new_db(), self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(creator, self.cid, a["id"]):
                outcome = automations._create_enrolment_for_contact(creator, self.cid, a["id"], a, contact_id, email, "manual")
                future = pool.submit(self.call, publisher, a, request)
                self.assert_waiting(creator, publisher)
            result = future.result(timeout=5)
        self.assertEqual(result["publication_receipt"]["outcomes"][0]["enrolment_count"], 1)
        self.assertEqual(self.state(outcome["enrolment_id"])["current_node_id"], "dest")

    def test_concurrent_identical_publication_and_new_enrolment(self):
        a = self.create()
        eid = self.add_enrolment(a)
        request = self.review(a)
        owner, retry = self.new_db(), self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(owner, self.cid, a["id"]):
                first = self.call(owner, a, request)
                future = pool.submit(self.call, retry, a, copy.deepcopy(request))
                self.assert_waiting(owner, retry)
            second = future.result(timeout=5)
        self.assertEqual(first["publication_receipt"], second["publication_receipt"])
        self.assertEqual(len(self.state(eid)["migration_events"]), 1)
        # A stale pre-publish object cannot start a new pass at the deleted first node.
        self.db.execute("update automation_enrolments set data = data || %s where id = %s", {"status": "completed"}, eid)
        contact_id, email = self.db.row("select contact_id, contact_email from automation_enrolments where id = %s", eid)
        outcome = automations._create_enrolment_for_contact(self.db, self.cid, a["id"], a, contact_id, email, "manual")
        self.assertEqual(self.state(outcome["enrolment_id"])["current_node_id"], "dest")

    def test_bodyless_publish_without_migration_and_occupied_refusal(self):
        a = self.create()
        self.add_enrolment(a)
        self.user_post(self.path(a) + "/publish")
        self.review(a)
        before = self.snapshot(a)
        response = self.simulate_post(self.path(a) + "/publish", headers=self.headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(a), before)

    def test_immediate_exit_clears_wait_and_retry_state_while_paused(self):
        a = self.create(paused=True)
        extra = {key: "obsolete" for key in automations._retry_clear_patch()}
        extra.update({"wait": {"remaining_seconds": 19}, "wake_at": "obsolete", "paused_at": "old", "resumed_at": "old"})
        eid = self.add_enrolment(a, status="held", **extra)
        untouched = self.add_enrolment(a, node="dest", status="paused_waiting", wait={"remaining_seconds": 72})
        before = self.state(untouched)
        self.committed(a, self.review(a, {"old_a": {"action": "exit"}}))
        state = self.state(eid)
        self.assertEqual(state["status"], "exited")
        self.assertEqual(state["current_node_id"], "old_a")
        for key in list(automations._retry_clear_patch()) + list(automations._claim_clear_patch()) + ["wait", "wake_at", "paused_at", "resumed_at"]:
            self.assertIsNone(state[key], key)
        self.assertEqual(self.state(untouched), before)
        self.assertEqual(self.snapshot(a)[3], [])

    def test_later_reviewed_publication_appends_history_and_supersedes_receipt(self):
        a = self.create()
        eid = self.add_enrolment(a)
        original_request = self.review(a)
        first = self.committed(a, original_request)
        first_event = self.state(eid)["migration_events"][0]
        self.user_patch(self.path(a), json={"draft": {"nodes": self.nodes()[3:]}})
        second_request = {"request_id": shortuuid.uuid(), "review": self.user_get(self.path(a) + "/publish-impact")["review"], "resolutions": {"dest": {"action": "move", "destination_node_id": "end"}}}
        second = self.committed(a, second_request)
        self.assertEqual(second["published_revision"], first["published_revision"] + 1)
        self.assertEqual(self.state(eid)["migration_events"][0], first_event)
        self.assertEqual(len(self.state(eid)["migration_events"]), 2)
        self.assert_refused(a, original_request)

    def test_new_enrolment_waits_for_migration_and_uses_paused_new_workflow(self):
        a = self.create(paused=True)
        self.add_enrolment(a, status="held")
        completed = self.add_enrolment(a, node="end", status="completed")
        contact_id, email = self.db.row("select contact_id, contact_email from automation_enrolments where id = %s", completed)
        request = self.review(a)
        owner, worker = self.new_db(), self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(owner, self.cid, a["id"]):
                self.call(owner, a, request)
                future = pool.submit(automations._create_enrolment_for_contact, worker, self.cid, a["id"], a, contact_id, email, "manual")
                self.assert_waiting(owner, worker)
            outcome = future.result(timeout=5)
        state = self.state(outcome["enrolment_id"])
        self.assertEqual(state["status"], "held")
        self.assertEqual(state["current_node_id"], "dest")
        self.assertEqual(state["published_revision"], 2)

    def test_reviewed_invalid_graph_still_uses_publish_validation(self):
        a = self.create()
        self.add_enrolment(a)
        request = self.review(a)
        invalid = self.nodes()[2:]
        invalid[0]["duration"]["days"] = 0
        self.user_patch(self.path(a), json={"draft": {"nodes": invalid}})
        request["review"] = self.user_get(self.path(a) + "/publish-impact")["review"]
        self.assert_refused(a, request, 400)

    def moved_review(self, a, action="follow"):
        nodes = self.nodes()
        nodes = [nodes[1], nodes[2], nodes[0], nodes[3]]
        self.user_patch(self.path(a), json={"draft": {"nodes": nodes, "moves": {
            "old_a": {"action": action, "published_revision": a["published_revision"],
                      "placement": automations._move_placement(nodes, "old_a")}
        }}})
        return {"request_id": shortuuid.uuid(), "review": self.user_get(self.path(a) + "/publish-impact")["review"], "resolutions": {}}

    def test_follow_moved_step_preserves_all_operational_state_and_replays_once(self):
        for status in ("ready", "waiting", "held", "paused_ready", "paused_waiting"):
            with self.subTest(status=status):
                a = self.create(paused=status.startswith("paused"))
                eid = self.add_enrolment(a, status=status, wait={"remaining_seconds": 73},
                                         retry_count=2, source="manual", paused_at="original")
                before = self.state(eid)
                request = self.moved_review(a)
                result = self.committed(a, request)
                after = self.state(eid)
                events = after.pop("migration_events")
                self.assertEqual(after, before)
                self.assertEqual(events[0]["action"], "follow")
                self.assertEqual(events[0]["reason"], "node_relocated")
                self.assertNotIn("moves", result["draft"])
                self.assertEqual(self.committed(a, request), result)
                self.assertEqual(len(self.state(eid)["migration_events"]), 1)
                self.assertEqual(self.snapshot(a)[3], [])

    def test_moved_exit_is_explicit_and_leaves_other_cohorts_untouched(self):
        a = self.create(paused=True)
        eid = self.add_enrolment(a, status="paused_waiting", wait={"remaining_seconds": 90})
        terminal = self.add_enrolment(a, status="completed")
        other = self.add_enrolment(a, node="dest", status="held")
        untouched = [self.state(terminal), self.state(other)]
        result = self.committed(a, self.moved_review(a, "exit"))
        self.assertEqual(result["status"], "paused")
        self.assertEqual(self.state(eid)["status"], "exited")
        self.assertIsNone(self.state(eid)["wait"])
        self.assertEqual([self.state(terminal), self.state(other)], untouched)

    def test_changed_move_placement_blocks_publication_without_mutation(self):
        a = self.create()
        self.add_enrolment(a)
        request = self.moved_review(a)
        draft = self.user_get(self.path(a))["draft"]
        draft["nodes"][0], draft["nodes"][1] = draft["nodes"][1], draft["nodes"][0]
        self.user_patch(self.path(a), json={"draft": draft})
        impact = self.user_get(self.path(a) + "/publish-impact")
        request["review"] = impact["review"]
        self.assertTrue(impact["blockers"])
        self.assert_refused(a, request)

    def test_move_decision_requires_review_and_claims_still_block(self):
        a = self.create()
        self.add_enrolment(a, claim_token="busy", claimed_at="2000-01-01T00:00:00Z")
        request = self.moved_review(a)
        self.assert_refused(a, request)
        before = self.snapshot(a)
        response = self.simulate_post(self.path(a) + "/publish", headers=self.headers())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(a), before)

    def test_moved_step_history_failure_rolls_back_decision_snapshot_and_contacts(self):
        a = self.create()
        self.add_enrolment(a)
        request = self.moved_review(a, "exit")
        before = self.snapshot(a)
        record = automations._record_publish_migration
        def fail(*args, **kwargs):
            record(*args, **kwargs)
            raise RuntimeError("injected history failure")
        with patch.object(automations, "_record_publish_migration", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.call(self.db, a, request)
        self.assertEqual(self.snapshot(a), before)
        self.committed(a, request)

    def test_moved_step_reassesses_concurrent_enrolment_under_same_lock(self):
        a = self.create()
        eid = self.add_enrolment(a, node="end", status="completed")
        contact_id, email = self.db.row("select contact_id, contact_email from automation_enrolments where id = %s", eid)
        request = self.moved_review(a, "exit")
        creator, publisher = self.new_db(), self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(creator, self.cid, a["id"]):
                outcome = automations._create_enrolment_for_contact(creator, self.cid, a["id"], a, contact_id, email, "manual")
                future = pool.submit(self.call, publisher, a, request)
                self.assert_waiting(creator, publisher)
            future.result(timeout=5)
        self.assertEqual(self.state(outcome["enrolment_id"])["status"], "exited")

    def test_follow_paused_wait_resumes_with_original_remaining_time(self):
        a = self.create(paused=True)
        eid = self.add_enrolment(a, status="paused_waiting",
                                 wait={"kind": "duration", "remaining_seconds": 73})
        self.committed(a, self.moved_review(a))
        self.user_post(self.path(a) + "/resume")
        state = self.state(eid)
        self.assertEqual(state["status"], "waiting")
        self.assertEqual(state["wait"]["last_remaining_seconds"], 73)
        self.assertEqual(state["current_node_id"], "old_a")

    def test_draft_move_decision_rejects_unknown_fields_and_actions(self):
        a = self.create()
        self.moved_review(a)
        draft = self.user_get(self.path(a))["draft"]
        for bad in ({"action": "move"}, {"destination_node_id": "end"}):
            invalid = copy.deepcopy(draft)
            invalid["moves"]["old_a"].update(bad)
            before = self.snapshot(a)
            response = self.simulate_patch(self.path(a), json={"draft": invalid}, headers=self.headers())
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.snapshot(a), before)
