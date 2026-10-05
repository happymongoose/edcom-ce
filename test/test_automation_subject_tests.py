import copy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import shortuuid
import test_base
from api import automations as a, automation_subject_tests as ab, events
from api.shared.db import DB
from api.migrations import add_automation_subject_tests


class TestAutomationSubjectTests(test_base.TestBase):
    def setUp(self):
        super().setUp()
        self.cid = self.user_cookie["cid"]
        self.db.set_cid(self.cid)
        add_automation_subject_tests.run(self.db)
        self.a = self.user_post(
            "/api/automations",
            json={"name": "Disposable subject test " + shortuuid.uuid()},
        )["id"]
        self.e = self.user_post(
            "/api/automations/" + self.a + "/emails",
            json={
                "subject": "Baseline",
                "fromemail": "sender@example.invalid",
                "returnpath": "sender@example.invalid",
                "fromname": "Test",
                "rawText": "<p>Same body</p>",
            },
        )["id"]
        self.contacts = []
        self.provider_event_ids = []
        self.addCleanup(self.cleanup)
        self.path = (
            "/api/automations/" + self.a + "/emails/" + self.e + "/subject-tests"
        )
        self.user_patch(
            "/api/automations/" + self.a,
            json={
                "entry": {"type": "manual"},
                "reentry": "multiple",
                "draft": {
                    "nodes": [
                        {
                            "id": "send",
                            "type": "send_email",
                            "label": "Send",
                            "automation_email_id": self.e,
                        },
                        {"id": "end", "type": "exit", "label": "Exit"},
                    ]
                },
            },
        )
        self.user_post("/api/automations/" + self.a + "/publish")
        self.mail = patch("api.automations.send_backend_mail").start()
        self.addCleanup(patch.stopall)
        patch(
            "api.automations._automation_execution_route",
            return_value={"id": "fake-only"},
        ).start()
        patch(
            "api.automations.generate_html", return_value=("<p>Same body</p>", None)
        ).start()

    def cleanup(self):
        self.db.execute(
            "delete from sparkpost_events where id=any(%s)", self.provider_event_ids
        )
        for table in (
            "automation_subject_sends",
            "automation_subject_tests",
            "automation_email_events",
            "automation_step_runs",
            "automation_enrolments",
            "automation_emails",
            "automations",
        ):
            key = "id" if table == "automations" else "automation_id"
            self.db.execute(
                "delete from " + table + " where cid=%s and " + key + "=%s",
                self.cid,
                self.a,
            )
        for table in ("contact_values", "contact_lists", "contacts"):
            self.db.execute(
                'delete from contacts."'
                + table
                + "_"
                + self.cid
                + '" where contact_id=any(%s)',
                self.contacts,
            )
        self.db.execute(
            "delete from userlogs where data->>'link_id'=any(%s)", [self.a, self.e]
        )

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def request(self, doc):
        return self.simulate_post(self.path, json=doc, headers=self.headers())

    def start(self, **extra):
        doc = {
            "action": "start",
            "previous_id": None,
            "maximum_sends": 2,
            "hours": 24,
            "metric": "ctr",
            "variants": [
                {"subject": "A", "weight": 50},
                {"subject": "B", "weight": 50},
            ],
        }
        doc.update(extra)
        r = self.request(doc)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json

    def current(self):
        return ab.active(self.db, self.cid, self.a, self.e)

    def enrol(self, suppressed=False):
        email = shortuuid.uuid().lower() + "@example.invalid"
        cid = self.db.single(
            'insert into contacts."contacts_'
            + self.cid
            + '"(email,added,props) values(%s,0,%s) returning contact_id',
            email,
            {"Unsubscribed": ["true"]} if suppressed else {},
        )
        self.contacts.append(cid)
        e = self.user_post(
            "/api/automations/" + self.a + "/enrolments", json={"email": email}
        )
        return e

    def execute_step(self, e):
        return a._run_next_automation_enrolment(self.db, self.cid, self.a, e["id"])

    def expire(self):
        t = self.current()
        t["deadline"] = "2000-01-01T00:00:00Z"
        ab.save(self.db, self.cid, t)

    def choose(self, t, variant):
        return self.request(
            {
                "action": "winner",
                "experiment_id": t["id"],
                "version": t["version"],
                "variant_id": variant,
            }
        )

    def sends(self):
        return self.db.execute(
            "select id,data from automation_subject_sends where cid=%s and automation_id=%s",
            self.cid,
            self.a,
        ).fetchall()

    def test_no_experiment_preserves_single_subject(self):
        r = self.execute_step(self.enrol())
        self.assertEqual(r["step_run"]["subject"], "Baseline")
        self.assertEqual(self.mail.call_count, 1)
        self.assertEqual(self.sends(), [])

    def test_cap_gates_without_claim_or_loop_mutation(self):
        t = self.start(maximum_sends=1)
        self.execute_step(self.enrol())
        e = self.enrol()
        r = self.execute_step(e)
        self.assertEqual(self.mail.call_count, 1)
        self.assertEqual(r["enrolment"]["current_node_id"], "send")
        self.assertEqual(r["enrolment"]["status"], "ready")
        self.assertIsNone(r["enrolment"].get("claim_token"))
        self.assertEqual(r["enrolment"]["subject_gate"], t["id"])
        self.assertFalse(r["enrolment"].get("visited_node_ids"))
        self.assertEqual(r["step_run"]["status"], "deferred")
        self.assertNotIn(
            e["id"],
            [
                x["enrolment_id"]
                for x in a._eligible_automation_enrolments(
                    self.db, self.cid, 25, self.a
                )
            ],
        )
        chosen = self.choose(self.current(), t["variants"][1]["id"])
        self.assertEqual(chosen.status_code, 200)
        r = self.execute_step(e)
        self.assertEqual(r["step_run"]["subject"], "B")
        self.assertEqual(r["enrolment"]["current_node_id"], "end")
        self.assertEqual(len(self.sends()), 2)

    def test_underfilled_deadline_and_zero_engagement_control(self):
        t = self.start(maximum_sends=2000)
        self.execute_step(self.enrol())
        self.expire()
        a.check_automation_subject_tests()
        c = self.current()
        self.assertEqual(c["winner_id"], t["control_id"])
        self.assertEqual(c["decision"]["reason"], "no_clear_winner_control")
        self.assertEqual(sum(v["assigned"] for v in c["decision"]["statistics"]), 1)

    def test_unused_experiment_does_not_start_clock(self):
        self.start()
        a.check_automation_subject_tests()
        self.assertFalse(self.current().get("deadline"))
        self.assertEqual(self.current()["status"], "collecting")

    def test_suppressed_does_not_consume_sample_or_start_clock(self):
        self.start()
        self.execute_step(self.enrol(True))
        self.assertFalse(self.current().get("deadline"))
        self.assertEqual(self.sends(), [])
        self.mail.assert_not_called()

    def test_delivery_metrics_deduplicate_and_freeze_decision(self):
        t = self.start()
        e = self.enrol()
        r = self.execute_step(e)
        run = r["step_run"]["id"]
        for _ in range(2):
            for kind in ("send", "open", "click"):
                self.assertTrue(
                    ab.record_event(self.db, self.cid, run, e["contact_email"], kind)
                )
        stats = ab.statistics(self.db, self.cid, self.current())
        v = next(v for v in stats if v["assigned"])
        self.assertEqual(
            (
                v["deliveries"],
                v["opens"],
                v["clicks"],
                v["ctr"],
                v["or_rate"],
                v["ctor"],
            ),
            (1, 1, 1, 1, 1, 1),
        )
        self.expire()
        a.check_automation_subject_tests()
        c = self.current()
        snapshot = copy.deepcopy(c["decision"])
        self.assertEqual(c["winner_id"], v["id"])
        self.choose(
            c, next(v["id"] for v in c["variants"] if v["id"] != c["winner_id"])
        )
        self.assertEqual(self.current()["decision"], snapshot)

    def test_acceptance_is_not_confirmed_delivery(self):
        self.start()
        r = self.execute_step(self.enrol())
        stats = ab.statistics(self.db, self.cid, self.current())
        v = next(v for v in stats if v["assigned"])
        self.assertEqual(v["accepted"], 1)
        self.assertEqual(v["deliveries"], 0)
        self.assertIsNone(v["ctr"])

    def test_retries_keep_assignment(self):
        self.start()
        e = self.enrol()
        self.mail.side_effect = a.MailNotSentError("definite failure")
        with self.assertRaises(Exception):
            self.execute_step(e)
        first = self.sends()[0][1]
        self.mail.side_effect = None
        self.db.execute(
            "update automation_enrolments set data=data||%s where id=%s",
            {"status": "ready", "retry_after": None},
            e["id"],
        )
        r = self.execute_step(e)
        self.assertEqual(len(self.sends()), 1)
        self.assertEqual(r["step_run"]["subject"], first["subject"])

    def test_uncertain_delivery_holds_without_retry(self):
        self.start()
        e = self.enrol()
        self.mail.side_effect = RuntimeError("uncertain")
        with self.assertRaises(Exception):
            self.execute_step(e)
        self.assertEqual(self.sends()[0][1]["status"], "uncertain")
        self.assertEqual(
            self.db.single(
                "select data->>'status' from automation_enrolments where id=%s", e["id"]
            ),
            "held",
        )

    def test_paused_gate_release_does_not_resume(self):
        t = self.start(maximum_sends=1)
        self.execute_step(self.enrol())
        e = self.enrol()
        self.execute_step(e)
        self.user_post("/api/automations/" + self.a + "/pause")
        self.expire()
        a.check_automation_subject_tests()
        self.assertEqual(self.db.automations.get(self.a)["status"], "paused")
        d = self.db.single(
            "select data from automation_enrolments where id=%s", e["id"]
        )
        self.assertEqual(d["status"], "paused_ready")
        self.assertIsNone(d["retry_after"])
        self.user_post("/api/automations/" + self.a + "/resume")
        r = self.execute_step(e)
        self.assertEqual(r["step_run"]["subject"], "A")

    def test_wrong_account_recipient_and_unknown_send_ignored(self):
        self.start()
        e = self.enrol()
        r = self.execute_step(e)
        self.assertFalse(
            ab.record_event(
                self.db, "foreign", r["step_run"]["id"], e["contact_email"], "send"
            )
        )
        self.assertFalse(
            ab.record_event(
                self.db, self.cid, r["step_run"]["id"], "wrong@example.invalid", "send"
            )
        )
        self.assertFalse(
            ab.delivery(self.db, r["step_run"]["id"], e["contact_email"], "foreign")
        )
        self.assertEqual(
            self.simulate_get(
                self.path.replace(self.a, "foreign"), headers=self.headers()
            ).status_code,
            403,
        )

    def test_strict_configuration_and_server_owned_fields(self):
        for change in (
            {"maximum_sends": True},
            {"maximum_sends": 0},
            {"hours": 0},
            {"metric": "ctor"},
            {"winner_id": "fake"},
            {
                "variants": [
                    {"subject": "A", "weight": 0},
                    {"subject": "B", "weight": 0},
                ]
            },
            {
                "variants": [
                    {"subject": "bad\nheader", "weight": 1},
                    {"subject": "B", "weight": 1},
                ]
            },
        ):
            doc = {
                "action": "start",
                "previous_id": None,
                "maximum_sends": 2,
                "hours": 24,
                "metric": "ctr",
                "variants": [
                    {"subject": "A", "weight": 50},
                    {"subject": "B", "weight": 50},
                ],
            }
            doc.update(change)
            self.assertEqual(self.request(doc).status_code, 400)
        r = self.simulate_patch(
            "/api/automations/" + self.a + "/emails/" + self.e,
            json={"subject_test": {"winner_id": "fake"}},
            headers=self.headers(),
        )
        self.assertEqual(r.status_code, 400)

    def test_pause_variant_add_challenger_and_stale_update(self):
        t = self.start()
        weights = {v["id"]: 0 if i else 100 for i, v in enumerate(t["variants"])}
        r = self.request(
            {
                "action": "allocation",
                "experiment_id": t["id"],
                "version": t["version"],
                "weights": weights,
            }
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.choose(t, t["control_id"]).status_code, 409)
        t = r.json
        r = self.request(
            {
                "action": "challenger",
                "experiment_id": t["id"],
                "version": t["version"],
                "subject": "C",
                "weight": 10,
            }
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json["variants"]), 3)

    def test_restart_archives_previous_results(self):
        t = self.start()
        self.choose(t, t["control_id"])
        new = self.start(previous_id=t["id"])
        self.assertNotEqual(new["id"], t["id"])
        rows = self.user_get(self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(t["status"] == "archived" for t in rows), 1)

    def test_concurrent_sample_cap_independent_connections(self):
        self.start(maximum_sends=1)

        def reserve(i):
            db = DB()
            db.set_cid(self.cid)
            try:
                with a._locked_automation(db, self.cid, self.a):
                    return ab.reserve(
                        db,
                        self.cid,
                        self.a,
                        self.e,
                        "fake" + str(i),
                        "send",
                        i,
                        "run" + str(i),
                    )
            except ab.Gate:
                return None
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve, range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.sends()), 1)

    def test_or_and_ctr_choose_different_highest_rates(self):
        for metric, expected in [("or", "A"), ("ctr", "B")]:
            current = self.current()
            if current:
                self.choose(current, current["control_id"])
            t = self.start(
                metric=metric,
                maximum_sends=20,
                previous_id=current["id"] if current else None,
            )
            for index, v in enumerate(t["variants"]):
                for n in range(4):
                    data = {
                        "variant_id": v["id"],
                        "sample": True,
                        "status": "accepted",
                        "delivered_at": ab.stamp(),
                    }
                    if n < (4 if index == 0 else 2):
                        data["opened_at"] = ab.stamp()
                    if n < (1 if index == 0 else 2):
                        data["clicked_at"] = ab.stamp()
                    self.db.execute(
                        "insert into automation_subject_sends values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        shortuuid.uuid(),
                        self.cid,
                        self.a,
                        self.e,
                        t["id"],
                        "fake",
                        "send",
                        n,
                        data,
                    )
            self.expire()
            a.check_automation_subject_tests()
            c = self.current()
            winner = next(v for v in c["variants"] if v["id"] == c["winner_id"])
            self.assertEqual(winner["subject"], expected)

    def test_tied_positive_rates_choose_control(self):
        t = self.start()
        for v in t["variants"]:
            self.db.execute(
                "insert into automation_subject_sends values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                shortuuid.uuid(),
                self.cid,
                self.a,
                self.e,
                t["id"],
                "fake",
                "send",
                1,
                {
                    "variant_id": v["id"],
                    "sample": True,
                    "delivered_at": ab.stamp(),
                    "clicked_at": ab.stamp(),
                    "status": "accepted",
                },
            )
        self.expire()
        a.check_automation_subject_tests()
        self.assertEqual(self.current()["winner_id"], t["control_id"])

    def test_live_content_locked_but_name_edit_allowed(self):
        self.start()
        path = "/api/automations/" + self.a + "/emails/" + self.e
        self.assertEqual(
            self.simulate_patch(
                path, json={"rawText": "changed body"}, headers=self.headers()
            ).status_code,
            400,
        )
        self.assertEqual(
            self.simulate_patch(
                path, json={"name": "New name"}, headers=self.headers()
            ).status_code,
            200,
        )

    def test_future_gate_rows_do_not_starve_runnable_contact(self):
        t = self.start(maximum_sends=1)
        self.execute_step(self.enrol())
        for _ in range(6):
            self.execute_step(self.enrol())
        latest = self.enrol()
        # Remove the completed sample sender so the remaining earliest candidates are gates.
        self.db.execute(
            "update automation_enrolments set data=data||%s where cid=%s and automation_id=%s and data->>'current_node_id'='end'",
            {"status": "completed"},
            self.cid,
            self.a,
        )
        rows = a._eligible_automation_enrolments(self.db, self.cid, 1, self.a)
        self.assertEqual([r["enrolment_id"] for r in rows], [latest["id"]])

    def test_slot_randomised_again_for_new_eligible_send(self):
        t = self.start(maximum_sends=5)
        with patch("api.automation_subject_tests.random.SystemRandom") as rng:
            rng.return_value.choices.side_effect = [
                [t["variants"][0]],
                [t["variants"][1]],
            ]
            with a._locked_automation(self.db, self.cid, self.a):
                one = ab.reserve(
                    self.db, self.cid, self.a, self.e, "enrol", "send", 7, "run"
                )
                self.db.execute(
                    "update automation_subject_sends set data=data||%s where id=%s",
                    {"status": "accepted"},
                    one["assignment_id"],
                )
                two = ab.reserve(
                    self.db, self.cid, self.a, self.e, "enrol", "send", 7, "next"
                )
            self.assertNotEqual(one["variant_id"], two["variant_id"])

    def test_slot_transaction_rollback(self):
        self.start()
        with self.assertRaises(RuntimeError):
            with a._locked_automation(self.db, self.cid, self.a):
                ab.reserve(self.db, self.cid, self.a, self.e, "enrol", "send", 7, "run")
                raise RuntimeError("rollback")
        self.assertEqual(self.sends(), [])
        self.assertFalse(self.current().get("deadline"))

    def test_deliveries_from_provider_handlers_and_sink_are_attributed(self):
        self.start(maximum_sends=10)
        for provider in ("ses", "sp", "mg", "sink"):
            e = self.enrol()
            r = self.execute_step(e)
            run = r["step_run"]["id"]
            if provider == "sink":
                self.assertTrue(ab.delivery(self.db, run, e["contact_email"], self.cid))
                continue
            obj = {
                "eventtype": {"ses": "Delivery", "sp": "delivery", "mg": "delivered"}[
                    provider
                ],
                "email": e["contact_email"],
                "domain": "example.invalid",
                "sinkid": provider,
                "ip": "test",
                "ts": "2026-01-01T00:00:00Z" if provider == "ses" else 1767225600,
                "msg": "ok",
                "settingsid": "fake",
                "usercid": self.cid,
                "campid": run,
                "is_camp": True,
                "trackingid": "fake",
                "event_id": shortuuid.uuid(),
                "bounceclass": "",
                "severity": "",
                "reason": "",
                "hardbounce": False,
                "messageid": "fake",
            }
            if provider == "ses":
                original = self.db.row

                def row(sql, *args, **kwargs):
                    if "from sesmessages" in sql:
                        return ("fake", self.cid, run, True, "fake", None)
                    return original(sql, *args, **kwargs)

                with patch.object(self.db, "row", side_effect=row):
                    events.process_ses_webhook(self.db, obj)
            elif provider == "sp":
                self.provider_event_ids.append(obj["event_id"])
                events.process_sp_webhook(self.db, None, obj)
            else:
                events.process_mg_webhook(self.db, None, obj)
        self.assertEqual(
            sum(
                v["deliveries"]
                for v in ab.statistics(self.db, self.cid, self.current())
            ),
            4,
        )

    def test_existing_click_tracking_updates_experiment(self):
        self.start()
        e = self.enrol()
        r = self.execute_step(e)
        self.assertTrue(
            events.write_automation_engagement_event(
                self.db,
                e["contact_email"],
                "click",
                r["step_run"]["id"],
                "test",
                "test",
                "test",
                None,
                0,
                True,
                "",
                "",
                link_url="https://example.invalid",
            )
        )
        self.assertTrue(self.sends()[0][1].get("clicked_at"))

    def test_gate_publication_refuses_occupied_deletion(self):
        self.start(maximum_sends=1)
        self.execute_step(self.enrol())
        e = self.enrol()
        self.execute_step(e)
        self.user_patch(
            "/api/automations/" + self.a,
            json={"draft": {"nodes": [{"id": "end", "type": "exit", "label": "Exit"}]}},
        )
        r = self.simulate_post(
            "/api/automations/" + self.a + "/publish", headers=self.headers()
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(
            self.db.single(
                "select data->>'current_node_id' from automation_enrolments where id=%s",
                e["id"],
            ),
            "send",
        )

    def test_gate_contacts_remain_subject_to_exit_rules(self):
        self.start(maximum_sends=1)
        self.execute_step(self.enrol())
        e = self.enrol()
        self.execute_step(e)
        self.db.execute(
            'insert into contacts."contact_values_'
            + self.cid
            + '"(contact_id,type,value) values(%s,%s,%s)',
            e["contact_id"],
            "tag",
            "ab_exit_test",
        )
        automation = self.db.automations.get(self.a)
        automation["published"]["exit_rules"] = [
            {"type": "has_tag", "tags": ["ab_exit_test"]}
        ]
        self.db.automations.patch(self.a, {"published": automation["published"]})
        result = self.execute_step(e)
        self.assertEqual(result["enrolment"]["status"], "exited")
        self.assertIsNone(result["enrolment"].get("subject_gate"))

    def test_selection_does_not_mutate_terminal_gate_rows(self):
        t = self.start(maximum_sends=1)
        self.execute_step(self.enrol())
        e = self.enrol()
        self.execute_step(e)
        self.db.execute(
            "update automation_enrolments set data=data||%s where id=%s",
            {"status": "cancelled"},
            e["id"],
        )
        before = self.db.single(
            "select data from automation_enrolments where id=%s", e["id"]
        )
        self.choose(self.current(), t["control_id"])
        self.assertEqual(
            self.db.single(
                "select data from automation_enrolments where id=%s", e["id"]
            ),
            before,
        )

    def test_late_events_update_report_not_decision(self):
        self.start()
        e = self.enrol()
        r = self.execute_step(e)
        self.expire()
        a.check_automation_subject_tests()
        before = copy.deepcopy(self.current()["decision"])
        for kind in ("send", "open", "click"):
            ab.record_event(
                self.db, self.cid, r["step_run"]["id"], e["contact_email"], kind
            )
        self.assertEqual(self.current()["decision"], before)
        self.assertEqual(
            sum(v["clicks"] for v in ab.statistics(self.db, self.cid, self.current())),
            1,
        )

    def test_throttled_send_does_not_take_another_sample_slot(self):
        self.start(maximum_sends=10)
        e = self.enrol()
        self.execute_step(e)
        self.execute_step(e)
        again = self.user_post(
            "/api/automations/" + self.a + "/enrolments",
            json={"email": e["contact_email"]},
        )
        result = self.execute_step(again)
        self.assertTrue(result["step_run"]["throttled"])
        self.assertEqual(len(self.sends()), 1)

    def test_abandoned_failure_not_reused_after_fresh_transition(self):
        self.start()
        e = self.enrol()
        self.mail.side_effect = a.MailNotSentError("definite failure")
        with self.assertRaises(Exception):
            self.execute_step(e)
        first = self.sends()[0][0]
        self.mail.side_effect = None
        # A successful advance or explicit migration clears failure provenance.
        self.db.execute(
            "update automation_enrolments set data=data||%s where id=%s",
            dict(a._retry_clear_patch(), status="ready"),
            e["id"],
        )
        self.execute_step(e)
        self.assertEqual(len(self.sends()), 2)
        self.assertNotEqual(self.sends()[-1][0], first)

    def migrate_gate(self, choice):
        self.start(maximum_sends=1)
        self.execute_step(self.enrol())
        e = self.enrol()
        self.execute_step(e)
        self.user_post("/api/automations/" + self.a + "/pause")
        path = "/api/automations/" + self.a
        self.user_patch(
            path,
            json={"draft": {"nodes": [{"id": "end", "type": "exit", "label": "Exit"}]}},
        )
        review = self.user_get(path + "/publish-impact")["review"]
        self.user_post(
            path + "/publish",
            json={
                "request_id": shortuuid.uuid(),
                "review": review,
                "resolutions": {"send": choice},
            },
        )
        data = self.db.single(
            "select data from automation_enrolments where id=%s", e["id"]
        )
        self.assertIsNone(data.get("subject_gate"))
        self.assertIsNone(data.get("retry_after"))
        self.assertEqual(self.mail.call_count, 1)
        self.assertEqual(self.db.automations.get(self.a)["status"], "paused")
        return data

    def test_gate_migration_moves_fresh_without_executing_destination(self):
        d = self.migrate_gate({"action": "move", "destination_node_id": "end"})
        self.assertEqual(d["status"], "paused_ready")
        self.assertEqual(d["current_node_id"], "end")

    def test_gate_migration_immediately_exits_while_paused(self):
        d = self.migrate_gate({"action": "exit"})
        self.assertEqual(d["status"], "exited")
        self.assertEqual(d["current_node_id"], "send")
