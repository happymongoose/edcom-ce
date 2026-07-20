import dateutil.parser
import shortuuid
from datetime import datetime

import test_base


class TestAutomationPause(test_base.TestBase):

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def create_contact(self):
        suffix = self.unique()
        email = "automation-pause-%s@example.com" % suffix
        lst = self.user_post("/api/lists", json={"name": "automation_pause_%s" % suffix})
        self.user_post(
            "/api/lists/%s/feed" % lst["id"],
            json={
                "email": email,
                "data": {
                    "First Name": "Automation",
                },
            },
        )
        return email

    def workflow(self, nodes=None, reentry="multiple"):
        if nodes is None:
            nodes = [
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
            ]
        return {
            "entry": {
                "type": "manual",
            },
            "reentry": reentry,
            "draft": {
                "nodes": nodes,
            },
        }

    def wait_nodes(self):
        return [
            {
                "id": "node_wait_1",
                "type": "wait_duration",
                "label": "Wait",
                "duration": {
                    "days": 0,
                    "hours": 0,
                    "minutes": 5,
                },
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]

    def create_automation(self, nodes=None):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_pause_%s" % suffix},
        )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        return self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

    def enrol(self, automation_id, email):
        result = self.simulate_post(
            "/api/automations/%s/enrolments" % automation_id,
            json={"email": email},
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 201, result.text)
        return result.json

    def list_enrolments(self, automation_id):
        return self.user_get("/api/automations/%s/enrolments" % automation_id)

    def pause(self, automation_id):
        return self.simulate_post(
            "/api/automations/%s/pause" % automation_id,
            headers=self.headers(),
        )

    def resume(self, automation_id):
        return self.simulate_post(
            "/api/automations/%s/resume" % automation_id,
            headers=self.headers(),
        )

    def run_next(self, automation_id, enrolment_id):
        return self.simulate_post(
            "/api/automations/%s/enrolments/%s/run-next" % (automation_id, enrolment_id),
            headers=self.headers(),
        )

    def history(self, automation_id):
        return self.user_get("/api/automations/%s/history" % automation_id)

    def cleanup(self, *automation_ids):
        self.db.execute(
            "delete from automation_step_runs where automation_id = any(%s)",
            list(automation_ids),
        )
        self.db.execute(
            "delete from automation_enrolments where automation_id = any(%s)",
            list(automation_ids),
        )
        self.db.set_cid(self.user_cookie["cid"])
        for automation_id in automation_ids:
            self.db.automations.remove(automation_id)

    def test_pause_sets_status_and_pauses_ready_enrolments(self):
        email = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.pause(automation["id"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["status"], "paused")

        enrolments = self.list_enrolments(automation["id"])
        self.assertEqual(enrolments[0]["id"], enrolment["id"])
        self.assertEqual(enrolments[0]["status"], "paused_ready")
        self.assertIn("paused_at", enrolments[0])

        self.cleanup(automation["id"])

    def test_pause_waiting_enrolments_stores_remaining_time_and_clears_wake_at(self):
        email = self.create_contact()
        automation = self.create_automation(nodes=self.wait_nodes())
        enrolment = self.enrol(automation["id"], email)
        waiting = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(waiting.status_code, 200, waiting.text)

        result = self.pause(automation["id"])
        self.assertEqual(result.status_code, 200, result.text)
        paused = self.list_enrolments(automation["id"])[0]

        self.assertEqual(paused["status"], "paused_waiting")
        self.assertEqual(paused["wake_at"], None)
        self.assertEqual(paused["wait"]["frozen_wake_at"], waiting.json["enrolment"]["wake_at"])
        self.assertGreater(paused["wait"]["remaining_seconds"], 250)
        self.assertLessEqual(paused["wait"]["remaining_seconds"], 300)

        self.cleanup(automation["id"])

    def test_history_includes_pause_wait_metadata(self):
        email = self.create_contact()
        automation = self.create_automation(nodes=self.wait_nodes())
        enrolment = self.enrol(automation["id"], email)
        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 200)
        self.assertEqual(self.pause(automation["id"]).status_code, 200)

        history = self.history(automation["id"])
        enrolment_event = [event for event in history["events"] if event["type"] == "enrolment"][0]
        self.assertEqual(enrolment_event["status"], "paused_waiting")
        self.assertEqual(enrolment_event["wake_at"], None)
        self.assertIn("paused_at", enrolment_event)
        self.assertGreater(enrolment_event["remaining_seconds"], 250)

        self.cleanup(automation["id"])

    def test_enrolment_while_paused_is_held_and_run_next_rejects(self):
        first_email = self.create_contact()
        second_email = self.create_contact()
        automation = self.create_automation()
        first = self.enrol(automation["id"], first_email)

        result = self.pause(automation["id"])
        self.assertEqual(result.status_code, 200, result.text)

        held = self.enrol(automation["id"], second_email)
        self.assertEqual(held["status"], "held")
        self.assertEqual(held["current_node_id"], "node_add_tag_1")

        run_result = self.run_next(automation["id"], first["id"])
        self.assertEqual(run_result.status_code, 400)
        self.assertIn("Automation is paused", run_result.text)

        held_result = self.run_next(automation["id"], held["id"])
        self.assertEqual(held_result.status_code, 400)
        self.assertIn("Automation is paused", held_result.text)

        self.cleanup(automation["id"])

    def test_resume_releases_held_and_paused_ready_enrolments(self):
        first_email = self.create_contact()
        second_email = self.create_contact()
        automation = self.create_automation()
        first = self.enrol(automation["id"], first_email)
        self.assertEqual(first["status"], "ready")
        self.assertEqual(self.pause(automation["id"]).status_code, 200)
        held = self.enrol(automation["id"], second_email)
        self.assertEqual(held["status"], "held")

        result = self.resume(automation["id"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["status"], "published")

        statuses = {enrolment["id"]: enrolment["status"] for enrolment in self.list_enrolments(automation["id"])}
        self.assertEqual(statuses[first["id"]], "ready")
        self.assertEqual(statuses[held["id"]], "ready")

        self.cleanup(automation["id"])

    def test_resume_restarts_paused_wait_with_preserved_remaining_time(self):
        email = self.create_contact()
        automation = self.create_automation(nodes=self.wait_nodes())
        enrolment = self.enrol(automation["id"], email)
        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 200)
        self.assertEqual(self.pause(automation["id"]).status_code, 200)

        paused = self.list_enrolments(automation["id"])[0]
        remaining = paused["wait"]["remaining_seconds"]
        result = self.resume(automation["id"])
        self.assertEqual(result.status_code, 200, result.text)

        resumed = self.list_enrolments(automation["id"])[0]
        self.assertEqual(resumed["status"], "waiting")
        self.assertEqual(resumed["wait"]["last_remaining_seconds"], remaining)
        wake_at = dateutil.parser.parse(resumed["wake_at"])
        delta = int((wake_at - datetime.utcnow().replace(tzinfo=wake_at.tzinfo)).total_seconds())
        self.assertGreater(delta, 240)
        self.assertLessEqual(delta, remaining)

        self.cleanup(automation["id"])

    def test_completed_and_exited_enrolments_are_unchanged(self):
        first_email = self.create_contact()
        second_email = self.create_contact()
        automation = self.create_automation()
        completed = self.enrol(automation["id"], first_email)
        exited = self.enrol(automation["id"], second_email)
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where id = %s
            """,
            {
                "status": "completed",
                "modified": datetime.utcnow().isoformat() + "Z",
            },
            completed["id"],
        )
        self.assertEqual(self.run_next(automation["id"], exited["id"]).status_code, 200)
        self.assertEqual(self.run_next(automation["id"], exited["id"]).json["enrolment"]["status"], "exited")

        self.assertEqual(self.pause(automation["id"]).status_code, 200)
        self.assertEqual(self.resume(automation["id"]).status_code, 200)

        statuses = {enrolment["id"]: enrolment["status"] for enrolment in self.list_enrolments(automation["id"])}
        self.assertEqual(statuses[completed["id"]], "completed")
        self.assertEqual(statuses[exited["id"]], "exited")

        self.cleanup(automation["id"])

    def test_cross_account_pause_resume_is_blocked(self):
        automation = self.create_automation()
        self.db.execute(
            "update automations set cid = %s where id = %s",
            "other-account-cid",
            automation["id"],
        )

        pause = self.pause(automation["id"])
        self.assertEqual(pause.status_code, 403)
        resume = self.resume(automation["id"])
        self.assertEqual(resume.status_code, 403)

        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation["id"],
            "other-account-cid",
        )
