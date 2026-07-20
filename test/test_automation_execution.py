import shortuuid

import test_base


class TestAutomationExecution(test_base.TestBase):

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def create_contact(self):
        suffix = self.unique()
        email = "automation-exec-%s@example.com" % suffix
        lst = self.user_post("/api/lists", json={"name": "automation_execution_%s" % suffix})
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
        return email, contact_id

    def workflow(self, tag="onboarding", nodes=None):
        if nodes is None:
            nodes = [
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add onboarding tag",
                    "draft_tag": tag,
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
            "draft": {
                "nodes": nodes,
            },
        }

    def create_automation(self, tag="onboarding"):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_%s" % suffix},
        )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(tag=tag),
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
        self.assertEqual(result.status_code, 201)
        return result.json

    def run_next(self, automation_id, enrolment_id):
        return self.simulate_post(
            "/api/automations/%s/enrolments/%s/run-next" % (automation_id, enrolment_id),
            headers=self.headers(),
        )

    def has_tag(self, contact_id, tag):
        return bool(
            self.db.single(
                f"""select contact_id from contacts."contact_values_{self.user_cookie['cid']}"
                where contact_id = %s and type = 'tag' and value = %s""",
                contact_id,
                tag,
            )
        )

    def step_runs(self, automation_id, enrolment_id):
        return list(
            self.db.execute(
                """
                select id, cid, automation_id, enrolment_id, contact_id, node_id, node_type, data
                from automation_step_runs
                where cid = %s and automation_id = %s and enrolment_id = %s
                order by data->>'created', id
                """,
                self.user_cookie["cid"],
                automation_id,
                enrolment_id,
            )
        )

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

    def test_running_add_tag_adds_tag_and_advances(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="execution-tag")
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)

        self.assertTrue(self.has_tag(contact_id, "execution-tag"))
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["node_type"], "add_tag")
        self.assertEqual(result.json["step_run"]["tag"], "execution-tag")
        self.assertEqual(result.json["step_run"]["status"], "succeeded")

        self.cleanup(automation["id"])

    def test_running_add_tag_when_contact_already_has_tag_succeeds_and_advances(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="existing-execution-tag")
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            f"""insert into contacts."contact_values_{self.user_cookie['cid']}"
            (contact_id, type, value) values (%s, 'tag', %s)
            on conflict (contact_id, type, value) do nothing""",
            contact_id,
            "existing-execution-tag",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.has_tag(contact_id, "existing-execution-tag"))
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 1)

        self.cleanup(automation["id"])

    def test_running_exit_marks_enrolment_exited(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        first = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(first.status_code, 200)

        second = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json["enrolment"]["status"], "exited")
        self.assertEqual(second.json["step_run"]["node_id"], "node_exit_1")
        self.assertEqual(second.json["step_run"]["node_type"], "exit")

        self.cleanup(automation["id"])

    def test_running_after_completed_or_exited_is_rejected(self):
        email, _ = self.create_contact()
        completed_automation = self.create_automation()
        self.db.set_cid(self.user_cookie["cid"])
        completed = completed_automation["published"].copy()
        completed["nodes"] = [completed["nodes"][0]]
        self.db.automations.patch(completed_automation["id"], {"published": completed})
        completed_enrolment = self.enrol(completed_automation["id"], email)

        first = self.run_next(completed_automation["id"], completed_enrolment["id"])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["enrolment"]["status"], "completed")
        second = self.run_next(completed_automation["id"], completed_enrolment["id"])
        self.assertEqual(second.status_code, 400)

        exited_automation = self.create_automation(tag="second-tag")
        exited_enrolment = self.enrol(exited_automation["id"], email)
        self.assertEqual(self.run_next(exited_automation["id"], exited_enrolment["id"]).status_code, 200)
        exited = self.run_next(exited_automation["id"], exited_enrolment["id"])
        self.assertEqual(exited.status_code, 200)
        after_exited = self.run_next(exited_automation["id"], exited_enrolment["id"])
        self.assertEqual(after_exited.status_code, 400)

        self.cleanup(completed_automation["id"], exited_automation["id"])

    def test_missing_current_node_is_rejected_clearly(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where id = %s
            """,
            {"current_node_id": "missing_node"},
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("Current automation node is missing", result.text)

        self.cleanup(automation["id"])

    def test_cross_account_execution_is_blocked(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            "update automation_enrolments set cid = %s where id = %s",
            "other-account-cid",
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 403)

        self.db.execute(
            "delete from automation_enrolments where id = %s and cid = %s",
            enrolment["id"],
            "other-account-cid",
        )
        self.cleanup(automation["id"])

    def test_step_run_history_is_recorded(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="history-tag")
        enrolment = self.enrol(automation["id"], email)

        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 200)
        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 200)

        runs = self.step_runs(automation["id"], enrolment["id"])
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0][4], contact_id)
        self.assertEqual(runs[0][5], "node_add_tag_1")
        self.assertEqual(runs[0][6], "add_tag")
        self.assertEqual(runs[0][7]["tag"], "history-tag")
        self.assertEqual(runs[0][7]["published_revision"], automation["published_revision"])
        self.assertIn("created", runs[0][7])
        self.assertEqual(runs[1][5], "node_exit_1")
        self.assertEqual(runs[1][6], "exit")

        self.cleanup(automation["id"])

    def test_endpoint_executes_from_published_not_draft(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="published-execution-tag")
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(tag="draft-only-tag"),
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.has_tag(contact_id, "published-execution-tag"))
        self.assertFalse(self.has_tag(contact_id, "draft-only-tag"))
        self.assertEqual(result.json["step_run"]["tag"], "published-execution-tag")

        self.cleanup(automation["id"])
