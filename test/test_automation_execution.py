import os
import json
import shortuuid
import dateutil.parser
import falcon
from datetime import datetime, timedelta

import test_base
from api import automations
from api.migrations import (
    add_automation_email_events_table,
    add_automation_segment_trigger_baselines_table,
    add_automation_trigger_events_table,
    add_debug_email_tables,
)


class TestAutomationExecution(test_base.TestBase):

    def setUp(self):
        super(TestAutomationExecution, self).setUp()
        add_debug_email_tables.run(self.db)
        add_automation_email_events_table.run(self.db)
        add_automation_trigger_events_table.run(self.db)
        add_automation_segment_trigger_baselines_table.run(self.db)
        self.created_list_ids = []
        self.created_emails = []
        self.test_id = "automation_execution_%s" % shortuuid.uuid().lower()
        self.created_debug_backend_ids = []
        self.created_route_ids = []
        self.created_mailgun_ids = []
        self.created_policy_ids = []
        self.created_sink_ids = []
        self.created_exclusion_items = []
        self.created_clientdkim_ids = []
        self.created_scheduler_cids = []
        self.created_admin_user_ids = []
        self.created_admin_cookie_ids = []
        if self.admin_cookie is None:
            self.create_admin_cookie()
        self.original_company_routes = None
        company = self.db.companies.get(self.user_cookie["cid"])
        self.original_company_automation_settings = {
            "automation_processing_enabled": company.get("automation_processing_enabled"),
            "automation_diagnostics_visible": company.get("automation_diagnostics_visible"),
        }
        self.original_automation_env = {
            "automation_processing_enabled": os.environ.get("automation_processing_enabled"),
            "automation_processing_limit": os.environ.get("automation_processing_limit"),
            "automation_processing_account_limit": os.environ.get("automation_processing_account_limit"),
        }

    def tearDown(self):
        self.restore_automation_env()
        self.restore_company_automation_settings()
        self.cleanup_scheduler_accounts()
        self.cleanup_admin_cookie()
        self.cleanup_debug_routes()
        self.cleanup_clientdkim()
        self.cleanup_contacts_and_lists()
        super(TestAutomationExecution, self).tearDown()

    def restore_automation_env(self):
        for key, value in self.original_automation_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def restore_company_automation_settings(self):
        self.db.execute(
            """
            update companies
            set data = data - 'automation_processing_enabled' - 'automation_diagnostics_visible'
            where id = %s
            """,
            self.user_cookie["cid"],
        )
        patch = {
            key: value
            for key, value in self.original_company_automation_settings.items()
            if value is not None
        }
        if patch:
            self.db.execute(
                "update companies set data = data || %s where id = %s",
                patch,
                self.user_cookie["cid"],
            )

    def set_customer_automation_processing(self, enabled):
        self.db.execute(
            "update companies set data = data || %s where id = %s",
            {"automation_processing_enabled": enabled},
            self.user_cookie["cid"],
        )

    def set_customer_automation_diagnostics(self, visible):
        self.db.execute(
            "update companies set data = data || %s where id = %s",
            {"automation_diagnostics_visible": visible},
            self.user_cookie["cid"],
        )

    def clear_customer_automation_diagnostics(self):
        self.db.execute(
            "update companies set data = data - 'automation_diagnostics_visible' where id = %s",
            self.user_cookie["cid"],
        )

    def create_admin_cookie(self):
        backend_cid = self.backend_cid()
        oldcid = self.db.get_cid()
        self.db.set_cid(backend_cid)
        try:
            admin_uid = self.db.users.add(
                {
                    "username": "automation-admin-%s@example.com" % shortuuid.uuid().lower(),
                    "fullname": "Automation Admin",
                    "companyname": "Automation Admin Company",
                    "admin": True,
                    "created": datetime.utcnow().isoformat() + "Z",
                }
            )
            cookie_id = self.db.cookies.add(
                {
                    "lastused": datetime.utcnow().isoformat() + "Z",
                    "uid": admin_uid,
                    "admin": True,
                }
            )
        finally:
            self.db.set_cid(oldcid)
        self.created_admin_user_ids.append(admin_uid)
        self.created_admin_cookie_ids.append(cookie_id)
        self.admin_cookie = self.db.cookies.get(cookie_id)

    def cleanup_admin_cookie(self):
        if self.created_admin_cookie_ids:
            self.db.execute(
                "delete from cookies where id = any(%s)",
                self.created_admin_cookie_ids,
            )
            self.created_admin_cookie_ids = []
        if self.created_admin_user_ids:
            self.db.execute(
                "delete from users where id = any(%s)",
                self.created_admin_user_ids,
            )
            self.created_admin_user_ids = []

    def cleanup_scheduler_accounts(self):
        if not self.created_scheduler_cids:
            return
        self.db.execute(
            "delete from automation_segment_trigger_members where cid = any(%s)",
            self.created_scheduler_cids,
        )
        self.db.execute(
            "delete from automation_segment_trigger_snapshots where cid = any(%s)",
            self.created_scheduler_cids,
        )
        self.db.execute(
            "delete from automation_trigger_events where cid = any(%s)",
            self.created_scheduler_cids,
        )
        self.db.execute(
            "delete from automation_step_runs where cid = any(%s)",
            self.created_scheduler_cids,
        )
        self.db.execute(
            "delete from automation_enrolments where cid = any(%s)",
            self.created_scheduler_cids,
        )
        self.db.execute(
            "delete from automations where cid = any(%s)",
            self.created_scheduler_cids,
        )
        self.db.execute(
            "delete from companies where id = any(%s)",
            self.created_scheduler_cids,
        )
        self.created_scheduler_cids = []

    def cleanup_debug_routes(self):
        cid = self.user_cookie["cid"]
        if self.original_company_routes is not None:
            self.db.execute(
                "update companies set data = data || %s where id = %s",
                {"routes": self.original_company_routes},
                cid,
            )
            self.original_company_routes = None
        self.db.execute(
            "delete from debug_email_logs where data->'metadata'->>'test_id' = %s",
            self.test_id,
        )
        if self.created_debug_backend_ids:
            self.db.execute(
                "delete from debug_email_backends where id = any(%s)",
                self.created_debug_backend_ids,
            )
            self.created_debug_backend_ids = []
        if self.created_route_ids:
            self.db.execute(
                "delete from routes where id = any(%s)",
                self.created_route_ids,
            )
            self.created_route_ids = []
        if self.created_policy_ids:
            self.db.execute(
                "delete from policies where id = any(%s)",
                self.created_policy_ids,
            )
            self.created_policy_ids = []
        if self.created_mailgun_ids:
            self.db.execute(
                "delete from mailgun where id = any(%s)",
                self.created_mailgun_ids,
            )
            self.created_mailgun_ids = []
        if self.created_sink_ids:
            self.db.execute(
                "delete from sinks where id = any(%s)",
                self.created_sink_ids,
            )
            self.created_sink_ids = []

    def cleanup_clientdkim(self):
        if self.created_clientdkim_ids:
            self.db.execute(
                "delete from clientdkim where id = any(%s)",
                self.created_clientdkim_ids,
            )
            self.created_clientdkim_ids = []

    def cleanup_contacts_and_lists(self):
        cid = self.user_cookie["cid"]
        self.db.execute(
            "delete from alltags where cid = %s and tag like %s",
            cid,
            "%s%%" % self.test_id,
        )
        if self.created_emails:
            domains = list({email.split("@", 1)[1] for email in self.created_emails if "@" in email})
            self.db.execute(
                "delete from unsublogs where cid = %s and email = any(%s)",
                cid,
                self.created_emails,
            )
            self.db.execute(
                "delete from exclusions where cid = %s and item = any(%s)",
                cid,
                self.created_emails + domains + self.created_exclusion_items,
            )
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
            self.created_emails = []
            self.created_exclusion_items = []
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
            self.created_list_ids = []

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def admin_headers(self):
        if not self.created_admin_cookie_ids:
            self.create_admin_cookie()
        return {
            "X-Auth-UID": self.admin_cookie["uid"],
            "X-Auth-Cookie": self.admin_cookie["id"],
        }

    def admin_impersonation_headers(self):
        headers = self.admin_headers()
        headers["X-Auth-Impersonate"] = self.user_cookie["cid"]
        return headers

    def create_contact(self, domain="example.com"):
        suffix = self.unique()
        email = "automation-exec-%s@%s" % (suffix, domain)
        lst = self.user_post("/api/lists", json={"name": "automation_execution_%s" % suffix})
        self.created_list_ids.append(lst["id"])
        self.created_emails.append(email)
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

    def create_empty_list(self, name=None):
        suffix = self.unique()
        lst = self.user_post(
            "/api/lists",
            json={"name": name or "automation_execution_empty_%s" % suffix},
        )
        self.created_list_ids.append(lst["id"])
        return lst

    def workflow(self, tag="onboarding", nodes=None, reentry=None):
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
        doc = {
            "entry": {
                "type": "manual",
            },
            "draft": {
                "nodes": nodes,
            },
        }
        if reentry is not None:
            doc["reentry"] = reentry
        return doc

    def create_automation(self, tag="onboarding", reentry=None, nodes=None):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_%s" % suffix},
        )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(tag=tag, nodes=nodes, reentry=reentry),
        )
        return self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

    def create_send_email_automation(self):
        return self.create_send_email_automation_with_options()

    def create_send_email_automation_with_options(
        self,
        include_exit=True,
        fromname="Automation Sender",
        returnpath="automation-sender@example.com",
        fromemail="",
        replyto="",
    ):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_send_email_%s" % suffix},
        )
        email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Execution email",
                "subject": "Execution subject",
                "rawText": "<p>Hello</p>",
                "fromname": fromname,
                "returnpath": returnpath,
                "fromemail": fromemail,
                "replyto": replyto,
            },
        )
        nodes = [
            {
                "id": "node_send_email_1",
                "type": "send_email",
                "label": "Send email",
                "automation_email_id": email["id"],
            },
        ]
        if include_exit:
            nodes.append(
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                }
            )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json
        published["execution_email_id"] = email["id"]
        return published

    def create_condition_automation(self, node_type="if_has_tag", node_overrides=None):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_condition_%s" % suffix},
        )
        nodes = [
            {
                "id": "node_condition_1",
                "type": node_type,
                "label": "If contact does not have tag" if node_type == "if_missing_tag" else "If contact has tag",
                "draft_tag": "vip",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add branch tag",
                "draft_tag": "branch-tag",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]
        if node_overrides:
            nodes[0].update(node_overrides)
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        return self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

    def create_compound_condition_automation(self, mode="all", items=None, node_overrides=None, reentry=None):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_compound_condition_%s" % suffix},
        )
        node = {
            "id": "node_compound_condition_1",
            "type": "if_conditions",
            "label": "If conditions",
            "condition": {
                "mode": mode,
                "items": items or [
                    {"type": "has_tag", "tag": "vip"},
                    {"type": "missing_tag", "tag": "inactive"},
                ],
            },
            "yes_node_id": "node_add_tag_1",
            "no_node_id": "node_exit_1",
        }
        if node_overrides:
            node.update(node_overrides)
        nodes = [
            node,
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add compound branch tag",
                "draft_tag": "compound-branch",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes, reentry=reentry),
        )
        return self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

    def create_email_engagement_condition_automation(self, node_type="if_opened_email"):
        return self.create_email_engagement_condition_automation_with_options(node_type)

    def create_email_engagement_condition_automation_with_options(self, node_type="if_opened_email", node_overrides=None, reentry=None):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_email_condition_%s" % suffix},
        )
        email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Engagement condition email",
                "subject": "Engagement condition subject",
                "rawText": "<p>Hello</p>",
            },
        )
        nodes = [
            {
                "id": "node_email_condition_1",
                "type": node_type,
                "label": "If opened email" if node_type == "if_opened_email" else "If clicked email",
                "automation_email_id": email["id"],
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add engaged branch tag",
                "draft_tag": "engaged-branch",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]
        if node_overrides:
            nodes[0].update(node_overrides)
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes, reentry=reentry),
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json
        published["engagement_email_id"] = email["id"]
        return published

    def create_go_to_automation(self):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_go_to_%s" % suffix},
        )
        nodes = [
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
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        return self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

    def create_no_exit_automation(self, tag="implicit-completion-tag"):
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_no_exit_%s" % suffix},
        )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(
                tag=tag,
                nodes=[
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": "Add final tag",
                        "draft_tag": tag,
                    },
                ],
            ),
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

    def enrol_response(self, automation_id, email):
        return self.simulate_post(
            "/api/automations/%s/enrolments" % automation_id,
            json={"email": email},
            headers=self.headers(),
        )

    def run_next(self, automation_id, enrolment_id):
        return self.simulate_post(
            "/api/automations/%s/enrolments/%s/run-next" % (automation_id, enrolment_id),
            headers=self.headers(),
        )

    def run_next_skip_wait(self, automation_id, enrolment_id):
        return self.simulate_post(
            "/api/automations/%s/enrolments/%s/run-next?skip_wait=true" % (automation_id, enrolment_id),
            headers=self.headers(),
        )

    def contact_automation_enrolments(self, email, limit=None):
        url = "/api/contactdata/%s/automation-enrolments" % email
        if limit is not None:
            url += "?limit=%s" % limit
        return self.simulate_get(url, headers=self.headers())

    def cancel_enrolment(self, automation_id, enrolment_id, headers=None):
        return self.simulate_post(
            "/api/automations/%s/enrolments/%s/cancel" % (automation_id, enrolment_id),
            headers=headers or self.headers(),
        )

    def process_enrolments(self, **doc):
        self.set_customer_automation_processing(True)
        return self.simulate_post(
            "/api/automation-enrolments/process",
            json=doc,
            headers=self.headers(),
        )

    def processing_status(self):
        self.set_customer_automation_diagnostics(True)
        return self.simulate_get(
            "/api/automation-processing-status",
            headers=self.headers(),
        )

    def process_enrolments_task(self, automation_id=None, limit=25):
        self.set_customer_automation_processing(True)
        return automations.process_automation_enrolments_task(
            self.user_cookie["cid"],
            automation_id,
            limit,
        )

    def run_scheduler_with_dispatch_patch(self, account_ids):
        original_account_ids = automations._automation_processing_account_ids
        original_run_task = automations.run_task
        dispatched = []

        def fake_account_ids(db, account_limit):
            return account_ids[:account_limit]

        def fake_run_task(task, cid, automation_id, limit):
            dispatched.append(
                {
                    "task": task,
                    "cid": cid,
                    "automation_id": automation_id,
                    "limit": limit,
                }
            )
            return "task-%s" % len(dispatched)

        automations._automation_processing_account_ids = fake_account_ids
        automations.run_task = fake_run_task
        try:
            result = automations.check_automation_enrolments()
        finally:
            automations._automation_processing_account_ids = original_account_ids
            automations.run_task = original_run_task
        return result, dispatched

    def run_scheduler_with_task_patch(self):
        original_run_task = automations.run_task
        dispatched = []

        def fake_run_task(task, cid, automation_id, limit):
            dispatched.append(
                {
                    "task": task,
                    "cid": cid,
                    "automation_id": automation_id,
                    "limit": limit,
                }
            )
            return "task-%s" % len(dispatched)

        automations.run_task = fake_run_task
        try:
            result = automations.check_automation_enrolments()
        finally:
            automations.run_task = original_run_task
        return result, dispatched

    def create_scheduler_candidate_account(
        self,
        status="ready",
        automation_status="published",
        wake_at=None,
        modified_at=None,
        retry_after=None,
        automation_processing_enabled=True,
    ):
        cid = "automation-scheduler-%s" % self.unique()
        automation_id = "automation-scheduler-automation-%s" % self.unique()
        enrolment_id = "automation-scheduler-enrolment-%s" % self.unique()
        now = modified_at or datetime.utcnow().isoformat() + "Z"
        data = {
            "name": "Scheduler account %s" % cid,
            "admin": False,
        }
        if automation_processing_enabled is not None:
            data["automation_processing_enabled"] = automation_processing_enabled
            data["automation_diagnostics_visible"] = False
        self.db.execute(
            "insert into companies (id, cid, data) values (%s, %s, %s)",
            cid,
            self.backend_cid(),
            data,
        )
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            automation_id,
            cid,
            {
                "name": "Scheduler automation %s" % cid,
                "status": automation_status,
                "published": {
                    "nodes": [
                        {
                            "id": "node_add_tag_1",
                            "type": "add_tag",
                            "label": "Add tag",
                            "draft_tag": "scheduler-tag",
                        }
                    ],
                },
                "published_revision": 1,
            },
        )
        enrolment_data = {
            "status": status,
            "current_node_id": "node_add_tag_1",
            "created": now,
            "modified": now,
        }
        if wake_at is not None:
            enrolment_data["wake_at"] = wake_at
        if retry_after is not None:
            enrolment_data["retry_after"] = retry_after
        self.db.execute(
            """
            insert into automation_enrolments
                (id, cid, automation_id, contact_id, contact_email, data)
            values (%s, %s, %s, %s, %s, %s)
            """,
            enrolment_id,
            cid,
            automation_id,
            1,
            "%s@example.com" % cid,
            enrolment_data,
        )
        self.created_scheduler_cids.append(cid)
        return cid

    def patch_enrolment_data(self, enrolment_id, data):
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where id = %s and cid = %s
            """,
            data,
            enrolment_id,
            self.user_cookie["cid"],
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

    def add_existing_tag(self, contact_id, tag, count=1):
        cid = self.user_cookie["cid"]
        self.db.execute(
            """insert into alltags (cid, tag, added, count) values (%s, %s, now(), %s)
            on conflict (cid, tag) do update set count = excluded.count""",
            cid,
            tag,
            count,
        )
        self.db.execute(
            f"""insert into contacts."contact_values_{cid}" (contact_id, type, value)
            values (%s, 'tag', %s) on conflict (contact_id, type, value) do nothing""",
            contact_id,
            tag,
        )

    def tag_count(self, tag):
        return self.db.single(
            "select count from alltags where cid = %s and tag = %s",
            self.user_cookie["cid"],
            tag,
        )

    def contact_list_ids(self, contact_id):
        return [
            row[0]
            for row in self.db.execute(
                f"""select list_id from contacts."contact_lists_{self.user_cookie['cid']}"
                where contact_id = %s order by list_id""",
                contact_id,
            )
        ]

    def is_in_list(self, contact_id, list_id):
        return bool(
            self.db.single(
                f"""select contact_id from contacts."contact_lists_{self.user_cookie['cid']}"
                where contact_id = %s and list_id = %s""",
                contact_id,
                list_id,
            )
        )

    def list_count(self, list_id):
        return self.db.single(
            "select coalesce((data->>'count')::int, 0) from lists where id = %s",
            list_id,
        )

    def list_domain_count(self, list_id, domain="example.com"):
        return self.db.single(
            "select count from list_domains where list_id = %s and domain = %s",
            list_id,
            domain,
        )

    def contact_exists(self, contact_id):
        return bool(
            self.db.single(
                f"""select contact_id from contacts."contacts_{self.user_cookie['cid']}"
                where contact_id = %s""",
                contact_id,
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

    def enrolment_data(self, enrolment_id):
        return self.db.single(
            "select data from automation_enrolments where id = %s and cid = %s",
            enrolment_id,
            self.user_cookie["cid"],
        )

    def assert_claim_cleared(self, data):
        self.assertIsNone(data.get("claim_token"))
        self.assertIsNone(data.get("claimed_at"))
        self.assertIsNone(data.get("claimed_node_id"))
        self.assertIsNone(data.get("claimed_published_revision"))
        self.assertIsNone(data.get("running_status"))
        self.assertNotEqual(data.get("status"), "running")

    def backend_cid(self):
        company = self.db.companies.get(self.user_cookie["cid"])
        return company["cid"]

    def create_debug_backend(self):
        backend_id = shortuuid.uuid()
        self.db.execute(
            "insert into debug_email_backends (id, cid, data) values (%s, %s, %s)",
            backend_id,
            self.backend_cid(),
            {"name": "Debug Log %s" % self.test_id},
        )
        self.created_debug_backend_ids.append(backend_id)
        return backend_id

    def create_debug_route(self):
        backend_id = self.create_debug_backend()
        route_id = shortuuid.uuid()
        now = datetime.utcnow().isoformat() + "Z"
        route = {
            "name": "Debug automation route %s" % self.test_id,
            "dirty": False,
            "rules": [
                {
                    "splits": [{"pct": 100, "policy": backend_id}],
                    "default": True,
                    "domaingroup": "",
                }
            ],
            "modified": now,
            "published": {
                "rules": [
                    {
                        "splits": [{"pct": 100, "policy": backend_id}],
                        "default": True,
                        "domaingroup": "",
                    }
                ],
                "usedefault": False,
            },
            "usedefault": False,
        }
        self.db.execute(
            "insert into routes (id, cid, data) values (%s, %s, %s)",
            route_id,
            self.backend_cid(),
            route,
        )
        self.created_route_ids.append(route_id)
        return route_id

    def create_mailgun_backend(self):
        backend_id = shortuuid.uuid()
        self.db.execute(
            "insert into mailgun (id, cid, data) values (%s, %s, %s)",
            backend_id,
            self.backend_cid(),
            {
                "name": "Automation preflight Mailgun %s" % self.test_id,
                "apikey": "secret-api-key-%s" % self.test_id,
                "domain": "mg.example.com",
            },
        )
        self.created_mailgun_ids.append(backend_id)
        return backend_id

    def create_sink_backend(self):
        sink_id = shortuuid.uuid()
        self.db.execute(
            "insert into sinks (id, cid, data) values (%s, %s, %s)",
            sink_id,
            self.backend_cid(),
            {
                "name": "Automation preflight sink %s" % self.test_id,
                "accesskey": "secret-access-key-%s" % self.test_id,
            },
        )
        self.created_sink_ids.append(sink_id)
        return sink_id

    def create_delivery_policy(self, sink_id, published=True):
        policy_id = shortuuid.uuid()
        policy = {
            "name": "Automation preflight policy %s" % self.test_id,
            "domains": "*",
            "sinks": [{"sink": sink_id, "pct": 100}],
        }
        data = {
            "name": policy["name"],
            "domains": policy["domains"],
            "sinks": policy["sinks"],
            "published": policy if published else None,
            "dirty": not published,
            "secret": "not-returned-%s" % self.test_id,
        }
        self.db.execute(
            "insert into policies (id, cid, data) values (%s, %s, %s)",
            policy_id,
            self.backend_cid(),
            data,
        )
        self.created_policy_ids.append(policy_id)
        return policy_id

    def create_route_with_splits(self, splits, name=None):
        route_id = shortuuid.uuid()
        now = datetime.utcnow().isoformat() + "Z"
        route = {
            "name": name or "Automation preflight route %s" % self.test_id,
            "dirty": False,
            "rules": [
                {
                    "splits": splits,
                    "default": True,
                    "domaingroup": "",
                }
            ],
            "modified": now,
            "published": {
                "rules": [
                    {
                        "splits": splits,
                        "default": True,
                        "domaingroup": "",
                    }
                ],
                "usedefault": False,
            },
            "usedefault": False,
        }
        self.db.execute(
            "insert into routes (id, cid, data) values (%s, %s, %s)",
            route_id,
            self.backend_cid(),
            route,
        )
        self.created_route_ids.append(route_id)
        return route_id

    def create_mailgun_route(self):
        backend_id = self.create_mailgun_backend()
        return self.create_route_with_splits(
            [{"pct": 100, "policy": backend_id}],
            "Mailgun automation route %s" % self.test_id,
        )

    def create_policy_sink_route(self):
        sink_id = self.create_sink_backend()
        policy_id = self.create_delivery_policy(sink_id)
        return self.create_route_with_splits(
            [{"pct": 100, "policy": policy_id}],
            "Policy sink automation route %s" % self.test_id,
        )

    def create_mixed_debug_mailgun_route(self):
        debug_backend_id = self.create_debug_backend()
        mailgun_id = self.create_mailgun_backend()
        return self.create_route_with_splits(
            [
                {"pct": 50, "policy": debug_backend_id},
                {"pct": 50, "policy": mailgun_id},
            ],
            "Mixed automation route %s" % self.test_id,
        )

    def create_unresolved_route(self, policy_id="missing-policy"):
        return self.create_route_with_splits(
            [{"pct": 100, "policy": policy_id}],
            "Unresolved automation route %s" % self.test_id,
        )

    def create_drop_all_route(self):
        route_id = shortuuid.uuid()
        now = datetime.utcnow().isoformat() + "Z"
        route = {
            "name": "Drop automation route %s" % self.test_id,
            "dirty": False,
            "rules": [
                {
                    "splits": [{"pct": 100, "policy": ""}],
                    "default": True,
                    "domaingroup": "",
                }
            ],
            "modified": now,
            "published": {
                "rules": [
                    {
                        "splits": [{"pct": 100, "policy": ""}],
                        "default": True,
                        "domaingroup": "",
                    }
                ],
                "usedefault": False,
            },
            "usedefault": False,
        }
        self.db.execute(
            "insert into routes (id, cid, data) values (%s, %s, %s)",
            route_id,
            self.backend_cid(),
            route,
        )
        self.created_route_ids.append(route_id)
        return route_id

    def assign_company_routes(self, routes):
        cid = self.user_cookie["cid"]
        if self.original_company_routes is None:
            company = self.db.companies.get(cid)
            self.original_company_routes = list(company.get("routes") or [])
        self.db.execute(
            "update companies set data = data || %s where id = %s",
            {"routes": routes},
            cid,
        )

    def assign_single_debug_route(self):
        route_id = self.create_debug_route()
        self.assign_company_routes([route_id])
        return route_id

    def add_verified_sender_domain(self, domain="example.com"):
        entry_id = shortuuid.uuid()
        self.db.execute(
            "insert into clientdkim (id, cid, data) values (%s, %s, %s)",
            entry_id,
            self.user_cookie["cid"],
            {
                "name": domain,
                "verified": True,
            },
        )
        self.created_clientdkim_ids.append(entry_id)
        return entry_id

    def preflight(self, automation_id, mode="draft"):
        return self.user_get(
            "/api/automations/%s/preflight?mode=%s" % (automation_id, mode)
        )

    def debug_email_logs(self, automation_id):
        return self.db.execute(
            """
            select id, cid, data
            from debug_email_logs
            where data->'source_ids'->>'automation_id' = %s
            order by ts desc
            """,
            automation_id,
        ).fetchall()

    def suppress_contact_prop(self, contact_id, prop):
        cid = self.user_cookie["cid"]
        self.db.execute(
            f"""update contacts."contacts_{cid}"
            set props = props || %s
            where contact_id = %s""",
            {prop: ["true"]},
            contact_id,
        )

    def suppress_contact_unsublog(self, email, contact_id, **flags):
        cid = self.user_cookie["cid"]
        self.db.execute(
            """
            insert into unsublogs (cid, email, rawhash, unsubscribed, complained, bounced)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (cid, email) do update set
                unsubscribed = excluded.unsubscribed,
                complained = excluded.complained,
                bounced = excluded.bounced
            """,
            cid,
            email,
            contact_id,
            flags.get("unsubscribed", False),
            flags.get("complained", False),
            flags.get("bounced", False),
        )

    def suppress_exclusion(self, item, contact_id=None):
        cid = self.user_cookie["cid"]
        exclusion_id = "%s_exclusion" % self.test_id
        self.created_exclusion_items.append(item)
        self.db.execute(
            """
            insert into exclusions (cid, item, exclusionid, rawhash)
            values (%s, %s, %s, %s)
            on conflict (cid, item, exclusionid) do nothing
            """,
            cid,
            item,
            exclusion_id,
            contact_id,
        )

    def assert_suppressed_send_skips_and_advances(
        self,
        email,
        automation,
        enrolment,
        expected_reason,
        expected_status="ready",
        expected_node_id="node_exit_1",
    ):
        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["enrolment"]["status"], expected_status)
        if expected_node_id is not None:
            self.assertEqual(result.json["enrolment"]["current_node_id"], expected_node_id)
        self.assert_claim_cleared(result.json["enrolment"])

        step_run = result.json["step_run"]
        self.assertEqual(step_run["status"], "succeeded")
        self.assertEqual(step_run["node_type"], "send_email")
        self.assertEqual(step_run["action"], "send_email")
        self.assertEqual(step_run["automation_email_id"], automation["execution_email_id"])
        self.assertEqual(step_run["automation_email_name"], "Execution email")
        self.assertEqual(step_run["subject"], "Execution subject")
        self.assertEqual(step_run["recipient_email"], email)
        self.assertEqual(step_run["sent"], False)
        self.assertEqual(step_run["suppressed"], True)
        self.assertEqual(step_run["suppression_reason"], expected_reason)
        self.assertIsNone(step_run.get("route_id"))
        self.assertEqual(self.debug_email_logs(automation["id"]), [])

    def insert_open_event(
        self,
        automation_id,
        enrolment_id,
        contact_id,
        contact_email,
        automation_email_id,
        event_cid=None,
        event_enrolment_id=None,
        event_contact_id=None,
        event_automation_email_id=None,
        event_type="open",
        event_data=None,
    ):
        event_id = shortuuid.uuid()
        self.db.execute(
            """
            insert into automation_email_events (
                id,
                cid,
                contact_id,
                contact_email,
                automation_id,
                automation_email_id,
                enrolment_id,
                send_node_id,
                send_step_run_id,
                event_type,
                ts,
                data
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
            """,
            event_id,
            event_cid or self.user_cookie["cid"],
            event_contact_id if event_contact_id is not None else contact_id,
            contact_email,
            automation_id,
            event_automation_email_id or automation_email_id,
            event_enrolment_id or enrolment_id,
            "node_send_email_1",
            "send-step-%s" % event_id,
            event_type,
            event_data or {"test_id": self.test_id},
        )
        return event_id

    def cleanup(self, *automation_ids):
        self.db.execute(
            "delete from debug_email_logs where data->'source_ids'->>'automation_id' = any(%s)",
            list(automation_ids),
        )
        self.db.execute(
            "delete from automation_email_events where automation_id = any(%s)",
            list(automation_ids),
        )
        self.db.execute(
            "delete from automation_emails where automation_id = any(%s)",
            list(automation_ids),
        )
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
        self.cleanup_contacts_and_lists()

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
        self.assert_claim_cleared(result.json["enrolment"])
        self.assert_claim_cleared(self.enrolment_data(enrolment["id"]))

        self.cleanup(automation["id"])

    def test_contact_automation_enrolments_lists_active_and_terminal(self):
        email, _ = self.create_contact()
        automation = self.create_automation(
            reentry="multiple",
            nodes=[
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add first tag",
                    "draft_tag": "contact-status-first",
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ],
        )
        terminal = self.enrol(automation["id"], email)
        self.patch_enrolment_data(
            terminal["id"],
            {"status": "completed", "current_node_id": None, "source": "manual-terminal"},
        )
        active = self.enrol(automation["id"], email)
        self.patch_enrolment_data(
            active["id"],
            {"status": "waiting", "current_node_id": "node_exit_1", "source": "manual-test"},
        )

        result = self.contact_automation_enrolments(email)

        self.assertEqual(result.status_code, 200, result.text)
        records = result.json["records"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["id"], active["id"])
        self.assertEqual(records[0]["status"], "waiting")
        self.assertEqual(records[0]["progress"], 50)
        self.assertEqual(records[0]["current_node_label"], "Exit automation")
        self.assertEqual(records[0]["current_node_type"], "exit")
        self.assertEqual(records[0]["source"], "manual-test")
        self.assertTrue(records[0]["cancellable"])
        self.assertEqual(records[1]["id"], terminal["id"])
        self.assertEqual(records[1]["progress"], 100)
        self.assertFalse(records[1]["cancellable"])
        self.assertNotIn("published", records[0])
        self.assertNotIn("data", records[0])

        self.cleanup(automation["id"])

    def test_contact_automation_enrolments_missing_current_node_safe_fallback(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        self.patch_enrolment_data(enrolment["id"], {"current_node_id": "missing-node"})

        result = self.contact_automation_enrolments(email)

        self.assertEqual(result.status_code, 200, result.text)
        record = result.json["records"][0]
        self.assertIsNone(record["progress"])
        self.assertEqual(record["current_node_label"], "Unknown step")
        self.assertEqual(record["current_node_type"], "")

        self.cleanup(automation["id"])

    def test_contact_automation_enrolments_are_account_scoped(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        self.enrol(automation["id"], email)
        other_cid = self.create_scheduler_candidate_account(status="ready")

        result = self.contact_automation_enrolments(email)

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json["records"]), 1)
        self.assertNotEqual(result.json["records"][0]["automation_id"], other_cid)

        self.cleanup(automation["id"])

    def test_cancel_active_automation_enrolment_statuses(self):
        for status in ("ready", "waiting", "held", "paused_ready", "paused_waiting"):
            email, _ = self.create_contact()
            automation = self.create_automation(tag="cancel-%s" % status)
            enrolment = self.enrol(automation["id"], email)
            self.patch_enrolment_data(enrolment["id"], {"status": status})

            result = self.cancel_enrolment(automation["id"], enrolment["id"])

            self.assertEqual(result.status_code, 200, result.text)
            data = self.enrolment_data(enrolment["id"])
            self.assertEqual(data["status"], "cancelled")
            self.assertEqual(data["cancelled_by_uid"], self.user_cookie["uid"])
            self.assertIsNotNone(data.get("cancelled_at"))
            self.assertEqual(data["cancelled_metadata"]["previous_status"], status)

            self.cleanup(automation["id"])

    def test_cancel_running_and_terminal_automation_enrolments_fails(self):
        for status in ("running", "completed", "exited", "cancelled", "failed"):
            email, _ = self.create_contact()
            automation = self.create_automation(tag="cancel-blocked-%s" % status)
            enrolment = self.enrol(automation["id"], email)
            self.patch_enrolment_data(enrolment["id"], {"status": status})

            result = self.cancel_enrolment(automation["id"], enrolment["id"])

            self.assertEqual(result.status_code, 400)
            if status == "running":
                self.assertIn("currently running", result.text)
            else:
                self.assertIn("cannot be cancelled", result.text)
            self.assertEqual(self.enrolment_data(enrolment["id"])["status"], status)

            self.cleanup(automation["id"])

    def test_cancel_automation_enrolment_is_account_scoped(self):
        other_cid = self.create_scheduler_candidate_account(status="ready")
        automation_id = self.db.single(
            "select id from automations where cid = %s limit 1",
            other_cid,
        )
        enrolment_id = self.db.single(
            "select id from automation_enrolments where cid = %s limit 1",
            other_cid,
        )

        result = self.cancel_enrolment(automation_id, enrolment_id)

        self.assertEqual(result.status_code, 403)

    def test_cancel_automation_enrolment_preserves_step_runs(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        run = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(run.status_code, 200, run.text)
        before = self.step_runs(automation["id"], enrolment["id"])
        self.assertEqual(len(before), 1)

        result = self.cancel_enrolment(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200, result.text)
        after = self.step_runs(automation["id"], enrolment["id"])
        self.assertEqual([row[0] for row in after], [row[0] for row in before])
        self.assertEqual(self.enrolment_data(enrolment["id"])["status"], "cancelled")

        self.cleanup(automation["id"])

    def test_tag_added_entry_does_not_automatically_enrol_when_tag_is_added(self):
        email, contact_id = self.create_contact()
        trigger_tag = "%s_entry_trigger" % self.test_id
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_entry_trigger_%s" % self.unique()},
        )
        workflow = self.workflow(tag="entry-trigger-action")
        workflow["entry"] = {
            "type": "tag_added",
            "tag": trigger_tag,
        }
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=workflow,
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

        self.add_existing_tag(contact_id, trigger_tag)

        enrolment_count = self.db.single(
            """
            select count(*)
            from automation_enrolments
            where cid = %s and automation_id = %s and contact_id = %s
            """,
            self.user_cookie["cid"],
            published["id"],
            contact_id,
        )
        self.assertEqual(enrolment_count, 0)

        self.cleanup(published["id"])

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

    def test_linear_automation_without_explicit_exit_completes_at_end(self):
        email, contact_id = self.create_contact()
        automation = self.create_no_exit_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.has_tag(contact_id, "implicit-completion-tag"))
        self.assertEqual(result.json["enrolment"]["status"], "completed")
        self.assertEqual(result.json["step_run"]["node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["node_type"], "add_tag")

        again = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(again.status_code, 400)

        self.cleanup(automation["id"])

    def test_running_remove_tag_removes_existing_tag_and_advances(self):
        email, contact_id = self.create_contact()
        tag = "%s_remove_existing" % self.test_id
        self.add_existing_tag(contact_id, tag)
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_remove_tag_1",
                    "type": "remove_tag",
                    "label": "Remove old tag",
                    "draft_tag": tag,
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.has_tag(contact_id, tag))
        self.assertIsNone(self.tag_count(tag))
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["node_type"], "remove_tag")
        self.assertEqual(result.json["step_run"]["action"], "remove_tag")
        self.assertEqual(result.json["step_run"]["tag"], tag)
        self.assertEqual(result.json["step_run"]["removed"], True)

        self.cleanup(automation["id"])

    def test_running_remove_tag_when_tag_absent_succeeds_and_advances(self):
        email, contact_id = self.create_contact()
        tag = "%s_remove_absent" % self.test_id
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_remove_tag_1",
                    "type": "remove_tag",
                    "label": "Remove missing tag",
                    "draft_tag": tag,
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.has_tag(contact_id, tag))
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["node_type"], "remove_tag")
        self.assertEqual(result.json["step_run"]["removed"], False)

        self.cleanup(automation["id"])

    def test_remove_tag_completes_when_final_node(self):
        email, contact_id = self.create_contact()
        tag = "%s_remove_final" % self.test_id
        self.add_existing_tag(contact_id, tag)
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_remove_tag_1",
                    "type": "remove_tag",
                    "label": "Remove final tag",
                    "draft_tag": tag,
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.has_tag(contact_id, tag))
        self.assertEqual(result.json["enrolment"]["status"], "completed")
        self.assertEqual(result.json["step_run"]["node_type"], "remove_tag")
        self.assertEqual(result.json["step_run"]["removed"], True)

        self.cleanup(automation["id"])

    def test_remove_tag_does_not_execute_next_node_in_same_request(self):
        email, contact_id = self.create_contact()
        remove_tag = "%s_remove_one_node" % self.test_id
        next_tag = "%s_next_not_run" % self.test_id
        self.add_existing_tag(contact_id, remove_tag)
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_remove_tag_1",
                    "type": "remove_tag",
                    "label": "Remove first tag",
                    "draft_tag": remove_tag,
                },
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add next tag",
                    "draft_tag": next_tag,
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.has_tag(contact_id, remove_tag))
        self.assertFalse(self.has_tag(contact_id, next_tag))
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 1)

        self.cleanup(automation["id"])

    def test_plural_lists_membership_counters_events_history_and_noops(self):
        from unittest.mock import patch
        for action, event in (("add_to_list", "list_joined"), ("remove_from_list", "list_left")):
            with self.subTest(action=action):
                email, contact_id = self.create_contact()
                existing = self.contact_list_ids(contact_id)[0]
                empty = self.create_empty_list()["id"]
                ids = [existing, empty]
                a = self.create_automation(nodes=[{"id": "lists", "type": action, "label": "Lists", "list_ids": ids}, {"id": "end", "type": "exit", "label": "End"}])
                self.addCleanup(self.cleanup, a["id"])
                self.assertEqual(a["published"]["nodes"][0]["list_ids"], ids)
                e = self.enrol(a["id"], email)
                self.patch_enrolment_data(e["id"], {"trigger_correlation_id": "list-batch", "trigger_depth": 2})
                self.addCleanup(self.db.execute, "delete from automation_trigger_events where cid = %s and contact_id = %s", self.user_cookie["cid"], contact_id)
                with patch.dict(os.environ, {"automation_trigger_emission_enabled": "true"}), patch.object(automations.contacts, "matching_list_trigger_automation_exists", return_value=True):
                    result = self.run_next(a["id"], e["id"])
                self.assertEqual(result.status_code, 200, result.text)
                for value in ids:
                    self.assertEqual(self.is_in_list(contact_id, value), action == "add_to_list")
                    self.assertEqual(self.list_count(value), 1 if action == "add_to_list" else 0)
                    self.assertEqual(self.list_domain_count(value), 1 if action == "add_to_list" else None)
                changed = empty if action == "add_to_list" else existing
                self.assertEqual(result.json["step_run"]["changed_list_ids"], [changed])
                self.assertEqual(result.json["step_run"]["list_ids"], ids)
                self.assertEqual(result.json["enrolment"]["current_node_id"], "end")
                rows = self.db.execute("select data from automation_trigger_events where cid = %s and contact_id = %s and event_type = %s", self.user_cookie["cid"], contact_id, event).fetchall()
                self.assertEqual([row[0]["list_id"] for row in rows], [changed])
                self.assertEqual(rows[0][0]["correlation_id"], "list-batch")
                self.assertEqual(rows[0][0]["depth"], 3)

    def test_plural_lists_later_trigger_failure_rolls_back_membership_counters_events_and_claim(self):
        from unittest.mock import patch
        for action, event in (("add_to_list", "list_joined"), ("remove_from_list", "list_left")):
            email, contact_id = self.create_contact()
            ids = sorted([self.create_empty_list()["id"], self.create_empty_list()["id"]])
            if action == "remove_from_list":
                for value in ids:
                    automations._add_contact_to_list(self.db, self.user_cookie["cid"], contact_id, email, value)
            a = self.create_automation(nodes=[{"id": "lists", "type": action, "label": "Lists", "list_ids": ids}])
            self.addCleanup(self.cleanup, a["id"])
            e = self.enrol(a["id"], email)
            original = automations.contacts.maybe_insert_list_trigger_event
            def fail_second(*args, **kwargs):
                if args[5] == ids[1]:
                    raise ValueError("Injected second-list event failure")
                return original(*args, **kwargs)
            with patch.dict(os.environ, {"automation_trigger_emission_enabled": "true"}), patch.object(automations.contacts, "matching_list_trigger_automation_exists", return_value=True), patch.object(automations.contacts, "maybe_insert_list_trigger_event", side_effect=fail_second):
                result = self.run_next(a["id"], e["id"])
            self.assertEqual(result.status_code, 400, result.text)
            for value in ids:
                self.assertEqual(self.is_in_list(contact_id, value), action == "remove_from_list")
                self.assertEqual(self.list_count(value), 1 if action == "remove_from_list" else 0)
                self.assertEqual(self.list_domain_count(value), 1 if action == "remove_from_list" else None)
            self.assertEqual(self.db.single("select count(*) from automation_trigger_events where cid = %s and contact_id = %s and event_type = %s", self.user_cookie["cid"], contact_id, event), 0)
            state = self.enrolment_data(e["id"])
            self.assertEqual(state["status"], "held")
            self.assert_claim_cleared(state)

    def test_plural_lists_missing_runtime_list_prevents_all_changes(self):
        email, contact_id = self.create_contact()
        ids = [self.create_empty_list()["id"], self.create_empty_list()["id"]]
        a = self.create_automation(nodes=[{"id": "lists", "type": "add_to_list", "label": "Lists", "list_ids": ids}])
        self.addCleanup(self.cleanup, a["id"])
        e = self.enrol(a["id"], email)
        self.db.lists.remove(ids[1])
        result = self.run_next(a["id"], e["id"])
        self.assertEqual(result.status_code, 400, result.text)
        self.assertFalse(self.is_in_list(contact_id, ids[0]))
        self.assertEqual(self.list_count(ids[0]), 0)
        self.assert_claim_cleared(self.enrolment_data(e["id"]))

    def test_add_to_list_adds_membership_and_updates_count(self):
        email, contact_id = self.create_contact()
        target_list = self.create_empty_list()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_to_list_1",
                    "type": "add_to_list",
                    "label": "Add to target list",
                    "list_id": target_list["id"],
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.is_in_list(contact_id, target_list["id"]))
        self.assertEqual(self.list_count(target_list["id"]), 1)
        self.assertEqual(self.list_domain_count(target_list["id"]), 1)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["node_type"], "add_to_list")
        self.assertEqual(result.json["step_run"]["action"], "add_to_list")
        self.assertEqual(result.json["step_run"]["list_id"], target_list["id"])
        self.assertEqual(result.json["step_run"]["list_name"], target_list["name"])
        self.assertEqual(result.json["step_run"]["added"], True)

        self.cleanup(automation["id"])

    def test_add_to_list_when_already_present_succeeds_without_count_change(self):
        email, contact_id = self.create_contact()
        existing_list_id = self.contact_list_ids(contact_id)[0]
        self.assertEqual(self.list_count(existing_list_id), 1)
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_to_list_1",
                    "type": "add_to_list",
                    "label": "Add to existing list",
                    "list_id": existing_list_id,
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.is_in_list(contact_id, existing_list_id))
        self.assertEqual(self.list_count(existing_list_id), 1)
        self.assertEqual(result.json["step_run"]["node_type"], "add_to_list")
        self.assertEqual(result.json["step_run"]["added"], False)

        self.cleanup(automation["id"])

    def test_remove_from_list_removes_membership_and_updates_count(self):
        email, contact_id = self.create_contact()
        existing_list_id = self.contact_list_ids(contact_id)[0]
        self.assertEqual(self.list_count(existing_list_id), 1)
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_remove_from_list_1",
                    "type": "remove_from_list",
                    "label": "Remove from source list",
                    "list_id": existing_list_id,
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.is_in_list(contact_id, existing_list_id))
        self.assertTrue(self.contact_exists(contact_id))
        self.assertEqual(self.list_count(existing_list_id), 0)
        self.assertIsNone(self.list_domain_count(existing_list_id))
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["node_type"], "remove_from_list")
        self.assertEqual(result.json["step_run"]["action"], "remove_from_list")
        self.assertEqual(result.json["step_run"]["list_id"], existing_list_id)
        self.assertEqual(result.json["step_run"]["removed"], True)

        self.cleanup(automation["id"])

    def test_remove_from_list_when_absent_succeeds_without_count_change(self):
        email, contact_id = self.create_contact()
        target_list = self.create_empty_list()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_remove_from_list_1",
                    "type": "remove_from_list",
                    "label": "Remove absent list",
                    "list_id": target_list["id"],
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.is_in_list(contact_id, target_list["id"]))
        self.assertTrue(self.contact_exists(contact_id))
        self.assertEqual(self.list_count(target_list["id"]), 0)
        self.assertEqual(result.json["step_run"]["node_type"], "remove_from_list")
        self.assertEqual(result.json["step_run"]["removed"], False)

        self.cleanup(automation["id"])

    def test_add_to_list_completes_when_final_node(self):
        email, contact_id = self.create_contact()
        target_list = self.create_empty_list()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_to_list_1",
                    "type": "add_to_list",
                    "label": "Add final list",
                    "list_id": target_list["id"],
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.is_in_list(contact_id, target_list["id"]))
        self.assertEqual(result.json["enrolment"]["status"], "completed")
        self.assertEqual(result.json["step_run"]["node_type"], "add_to_list")

        self.cleanup(automation["id"])

    def test_list_action_does_not_execute_next_node_in_same_request(self):
        email, contact_id = self.create_contact()
        target_list = self.create_empty_list()
        next_tag = "%s_list_next_not_run" % self.test_id
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_to_list_1",
                    "type": "add_to_list",
                    "label": "Add list first",
                    "list_id": target_list["id"],
                },
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add next tag",
                    "draft_tag": next_tag,
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertTrue(self.is_in_list(contact_id, target_list["id"]))
        self.assertFalse(self.has_tag(contact_id, next_tag))
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 1)

        self.cleanup(automation["id"])

    def test_list_action_execution_missing_or_unowned_list_is_rejected_clearly(self):
        email, _ = self.create_contact()
        target_list = self.create_empty_list()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_to_list_1",
                    "type": "add_to_list",
                    "label": "Add to target list",
                    "list_id": target_list["id"],
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            "update lists set cid = %s where id = %s",
            "other-account-cid",
            target_list["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("contact list that was not found", result.text)

        self.db.execute(
            "delete from lists where id = %s and cid = %s",
            target_list["id"],
            "other-account-cid",
        )
        self.cleanup(automation["id"])

    def test_list_action_paused_enrolment_rejection_remains_intact(self):
        email, contact_id = self.create_contact()
        target_list = self.create_empty_list()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_to_list_1",
                    "type": "add_to_list",
                    "label": "Add to target list",
                    "list_id": target_list["id"],
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            {"status": "held"},
            self.user_cookie["cid"],
            automation["id"],
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("Enrolment is paused", result.text)
        self.assertFalse(self.is_in_list(contact_id, target_list["id"]))

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

    def test_running_send_email_records_debug_log_and_advances(self):
        email, _ = self.create_contact()
        route_id = self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assert_claim_cleared(result.json["enrolment"])

        step_run = result.json["step_run"]
        self.assertEqual(step_run["node_type"], "send_email")
        self.assertEqual(step_run["automation_email_id"], automation["execution_email_id"])
        self.assertEqual(step_run["subject"], "Execution subject")
        self.assertEqual(step_run["recipient_email"], email)
        self.assertEqual(step_run["route_id"], route_id)
        self.assertEqual(step_run["published_revision"], automation["published_revision"])
        self.assertEqual(step_run["sent"], True)
        self.assertEqual(step_run["status"], "succeeded")

        logs = self.debug_email_logs(automation["id"])
        self.assertEqual(len(logs), 1)
        log_data = logs[0][2]
        self.assertEqual(log_data["subject"], "Execution subject")
        self.assertEqual(log_data["recipient_email"], email)
        self.assertEqual(log_data["source_type"], "automation")
        self.assertEqual(log_data["source_id"], automation["id"])
        self.assertEqual(log_data["source_ids"]["automation_id"], automation["id"])
        self.assertEqual(log_data["source_ids"]["automation_email_id"], automation["execution_email_id"])
        self.assertEqual(log_data["source_ids"]["enrolment_id"], enrolment["id"])
        self.assertEqual(log_data["source_ids"]["node_id"], "node_send_email_1")
        self.assertEqual(log_data["source_ids"]["step_run_id"], step_run["id"])
        self.assertEqual(log_data["source_ids"]["published_revision"], automation["published_revision"])
        self.assertEqual(log_data["metadata"]["automation_id"], automation["id"])
        self.assertEqual(log_data["metadata"]["step_run_id"], step_run["id"])

        self.cleanup(automation["id"])

    def test_send_email_preflight_draft_and_published_use_correct_nodes(self):
        self.assign_single_debug_route()
        self.add_verified_sender_domain()
        automation = self.create_send_email_automation()
        replacement_email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Draft replacement",
                "subject": "Draft subject",
                "rawText": "<p>Draft body</p>",
                "fromname": "",
                "returnpath": "automation-sender@example.com",
            },
        )
        self.db.set_cid(self.user_cookie["cid"])
        draft = automation["draft"].copy()
        draft["nodes"][0] = draft["nodes"][0].copy()
        draft["nodes"][0]["automation_email_id"] = replacement_email["id"]
        self.db.automations.patch(automation["id"], {"draft": draft})

        draft = self.preflight(automation["id"], "draft")
        published = self.preflight(automation["id"], "published")

        self.assertFalse(draft["ready"])
        self.assertEqual(draft["nodes"][0]["automation_email_id"], replacement_email["id"])
        self.assertEqual(draft["nodes"][0]["errors"][0]["code"], "missing_fromname")
        self.assertTrue(published["ready"])
        self.assertEqual(published["nodes"][0]["automation_email_id"], automation["execution_email_id"])
        self.assertEqual(published["route"]["status"], "debug_log")
        self.assertTrue(published["route"]["ready_for_debug"])

        self.cleanup(automation["id"])

    def test_send_email_preflight_missing_email_error(self):
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        self.db.set_cid(self.user_cookie["cid"])
        draft = automation["draft"].copy()
        draft["nodes"][0] = draft["nodes"][0].copy()
        draft["nodes"][0]["automation_email_id"] = "missing-email-id"
        self.db.automations.patch(automation["id"], {"draft": draft})

        result = self.preflight(automation["id"], "draft")

        self.assertFalse(result["ready"])
        self.assertEqual(result["nodes"][0]["errors"][0]["code"], "missing_email")

        self.cleanup(automation["id"])

    def test_send_email_preflight_no_send_email_nodes_is_ready_info_state(self):
        automation = self.create_automation()
        self.assign_company_routes([])

        result = self.preflight(automation["id"], "published")

        self.assertTrue(result["ready"])
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["route"], {})
        self.assertIn("no_send_email_nodes", {info["code"] for info in result["info"]})

        self.cleanup(automation["id"])

    def test_send_email_preflight_missing_sender_subject_and_body_errors(self):
        self.assign_single_debug_route()
        automation = self.create_send_email_automation_with_options(fromname="", returnpath="")
        self.db.execute(
            """
            update automation_emails
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            {
                "subject": "",
                "rawText": "",
                "parts": [],
            },
            self.user_cookie["cid"],
            automation["id"],
            automation["execution_email_id"],
        )

        result = self.preflight(automation["id"], "published")
        codes = {error["code"] for error in result["nodes"][0]["errors"]}

        self.assertFalse(result["ready"])
        self.assertTrue({"missing_fromname", "missing_returnpath", "missing_subject", "missing_body"}.issubset(codes))

        self.cleanup(automation["id"])

    def test_send_email_preflight_body_detection_by_editor_type(self):
        self.assign_single_debug_route()
        self.add_verified_sender_domain()
        cases = [
            ("raw", "", [], True),
            ("raw", "<p>Raw body</p>", [], False),
            ("wysiwyg", "", [], True),
            ("wysiwyg", "<p>WYSIWYG body</p>", [], False),
            ("beefree", '{"page": {"body": {}}}', [], True),
            ("beefree", '{"html": "<p>BeeFree body</p>"}', [], False),
            ("", "", [], True),
            ("", "", [{"type": "text", "html": "<p>Legacy body</p>"}], False),
        ]
        created_automation_ids = []
        try:
            for email_type, raw_text, parts, should_error in cases:
                with self.subTest(email_type=email_type, should_error=should_error):
                    automation = self.create_send_email_automation()
                    created_automation_ids.append(automation["id"])
                    self.db.execute(
                        """
                        update automation_emails
                        set data = data || %s
                        where cid = %s and automation_id = %s and id = %s
                        """,
                        {
                            "type": email_type,
                            "rawText": raw_text,
                            "parts": parts,
                            "bodyStyle": {},
                        },
                        self.user_cookie["cid"],
                        automation["id"],
                        automation["execution_email_id"],
                    )

                    result = self.preflight(automation["id"], "published")
                    codes = {error["code"] for error in result["nodes"][0]["errors"]}

                    if should_error:
                        self.assertIn("missing_body", codes)
                    else:
                        self.assertNotIn("missing_body", codes)
                        self.assertTrue(result["ready"])
        finally:
            if created_automation_ids:
                self.cleanup(*created_automation_ids)

    def test_send_email_preflight_no_route_and_multiple_route_errors(self):
        self.add_verified_sender_domain()
        automation = self.create_send_email_automation()
        self.assign_company_routes([])

        no_route = self.preflight(automation["id"], "published")
        self.assertFalse(no_route["ready"])
        self.assertEqual(no_route["route"]["status"], "missing")
        self.assertEqual(no_route["route"]["errors"][0]["code"], "no_route")

        first_route = self.create_debug_route()
        second_route = self.create_debug_route()
        self.assign_company_routes([first_route, second_route])
        multiple = self.preflight(automation["id"], "published")
        self.assertFalse(multiple["ready"])
        self.assertEqual(multiple["route"]["status"], "multiple")
        self.assertEqual(multiple["route"]["errors"][0]["code"], "multiple_routes")

        self.cleanup(automation["id"])

    def test_send_email_preflight_drop_all_route_errors(self):
        self.add_verified_sender_domain()
        route_id = self.create_drop_all_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()

        result = self.preflight(automation["id"], "published")

        self.assertFalse(result["ready"])
        self.assertEqual(result["route"]["status"], "drop_all")
        self.assertEqual(result["route"]["route_id"], route_id)
        self.assertEqual(result["route"]["errors"][0]["code"], "drop_all_route")

        self.cleanup(automation["id"])

    def test_send_email_preflight_projects_live_backend_details_without_secrets(self):
        self.add_verified_sender_domain()
        route_id = self.create_mailgun_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()

        result = self.preflight(automation["id"], "published")
        route = result["route"]

        self.assertTrue(result["ready"])
        self.assertEqual(route["status"], "published_route")
        self.assertEqual(route["route_id"], route_id)
        self.assertTrue(route["assigned"])
        self.assertTrue(route["published"])
        self.assertFalse(route["debug"])
        self.assertFalse(route["drop_all"])
        self.assertEqual(route["backend_types"], ["mailgun"])
        self.assertEqual(route["backends"][0]["type"], "mailgun")
        self.assertIn("Automation preflight Mailgun", route["backends"][0]["name"])
        serialized = json.dumps(route)
        self.assertNotIn("secret-api-key", serialized)
        self.assertNotIn("apikey", serialized)
        self.assertNotIn("domain", serialized)

        self.cleanup(automation["id"])

    def test_send_email_preflight_projects_policy_sink_backend_details(self):
        self.add_verified_sender_domain()
        route_id = self.create_policy_sink_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()

        result = self.preflight(automation["id"], "published")
        route = result["route"]

        self.assertTrue(result["ready"])
        self.assertEqual(route["status"], "published_route")
        self.assertEqual(route["route_id"], route_id)
        self.assertEqual(route["backend_types"], ["mta_sink"])
        self.assertEqual(route["backends"][0]["type"], "mta_sink")
        self.assertEqual(route["backends"][0]["source"], "policy_sink")
        self.assertIn("policy_id", route["backends"][0])
        serialized = json.dumps(route)
        self.assertNotIn("secret-access-key", serialized)
        self.assertNotIn("accesskey", serialized)
        self.assertNotIn("not-returned", serialized)

        self.cleanup(automation["id"])

    def test_send_email_preflight_mixed_route_projects_backend_types(self):
        self.add_verified_sender_domain()
        route_id = self.create_mixed_debug_mailgun_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()

        result = self.preflight(automation["id"], "published")
        route = result["route"]

        self.assertTrue(result["ready"])
        self.assertEqual(route["status"], "mixed_debug")
        self.assertEqual(route["route_id"], route_id)
        self.assertTrue(route["debug"])
        self.assertTrue(route["mixed"])
        self.assertEqual(set(route["backend_types"]), {"debug_log", "mailgun"})
        self.assertEqual({backend["type"] for backend in route["backends"]}, {"debug_log", "mailgun"})
        self.assertEqual(route["warnings"][0]["code"], "mixed_debug_route")

        self.cleanup(automation["id"])

    def test_send_email_preflight_unresolved_route_is_conservative(self):
        self.add_verified_sender_domain()
        route_id = self.create_unresolved_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()

        result = self.preflight(automation["id"], "published")
        route = result["route"]

        self.assertTrue(result["ready"])
        self.assertEqual(route["status"], "unresolved")
        self.assertEqual(route["route_id"], route_id)
        self.assertEqual(route["backend_types"], [])
        self.assertEqual(route["warnings"][0]["code"], "unresolved_route_backend")
        self.assertEqual(route["unresolved"][0]["reason"], "missing_policy_or_backend")

        self.cleanup(automation["id"])

    def test_send_email_preflight_unpublished_policy_is_conservative(self):
        self.add_verified_sender_domain()
        sink_id = self.create_sink_backend()
        policy_id = self.create_delivery_policy(sink_id, published=False)
        route_id = self.create_route_with_splits(
            [{"pct": 100, "policy": policy_id}],
            "Unpublished policy automation route %s" % self.test_id,
        )
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()

        result = self.preflight(automation["id"], "published")
        route = result["route"]

        self.assertTrue(result["ready"])
        self.assertEqual(route["status"], "unresolved")
        self.assertEqual(route["warnings"][0]["code"], "unresolved_route_backend")
        self.assertEqual(route["unresolved"][0]["reason"], "unpublished_policy")

        self.cleanup(automation["id"])

    def test_send_email_preflight_unverified_sender_domain_errors(self):
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()

        result = self.preflight(automation["id"], "published")
        codes = {error["code"] for error in result["nodes"][0]["errors"]}

        self.assertFalse(result["ready"])
        self.assertIn("sender_domain_not_verified", codes)

        self.cleanup(automation["id"])

    def test_send_email_preflight_account_scoped(self):
        automation = self.create_send_email_automation()

        scoped = self.simulate_get(
            "/api/automations/%s/preflight?mode=published" % automation["id"],
            headers=self.admin_impersonation_headers(),
        )
        self.assertEqual(scoped.status_code, 200)
        self.assertEqual(scoped.json["automation_id"], automation["id"])

        result = self.simulate_get(
            "/api/automations/%s/preflight?mode=published" % automation["id"],
            headers=self.admin_headers(),
        )

        self.assertEqual(result.status_code, 401)

        self.cleanup(automation["id"])

    def test_send_email_unsubscribed_contact_skips_send_and_advances(self):
        email, contact_id = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.suppress_contact_prop(contact_id, "Unsubscribed")

        self.assert_suppressed_send_skips_and_advances(
            email,
            automation,
            enrolment,
            "unsubscribed",
        )
        data = self.enrolment_data(enrolment["id"])
        self.assertIsNone(data.get("retry_after"))
        self.assertIsNone(data.get("last_error"))

        self.cleanup(automation["id"])

    def test_send_email_complained_contact_skips_send_and_advances(self):
        email, contact_id = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.suppress_contact_prop(contact_id, "Complained")

        self.assert_suppressed_send_skips_and_advances(
            email,
            automation,
            enrolment,
            "complained",
        )

        self.cleanup(automation["id"])

    def test_send_email_bounced_contact_skips_send_and_advances(self):
        email, contact_id = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.suppress_contact_unsublog(email, contact_id, bounced=True)

        self.assert_suppressed_send_skips_and_advances(
            email,
            automation,
            enrolment,
            "bounced",
        )

        self.cleanup(automation["id"])

    def test_send_email_excluded_email_skips_send_and_advances(self):
        email, contact_id = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.suppress_exclusion(email, contact_id)

        self.assert_suppressed_send_skips_and_advances(
            email,
            automation,
            enrolment,
            "excluded_email",
        )

        self.cleanup(automation["id"])

    def test_send_email_excluded_domain_skips_send_and_advances(self):
        domain = "%s.example.com" % self.unique()
        email, _ = self.create_contact(domain=domain)
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.suppress_exclusion(domain)

        self.assert_suppressed_send_skips_and_advances(
            email,
            automation,
            enrolment,
            "excluded_domain",
        )

        self.cleanup(automation["id"])

    def test_send_email_does_not_execute_next_node_in_same_request(self):
        email, contact_id = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        self.db.set_cid(self.user_cookie["cid"])
        published = automation["published"].copy()
        published["nodes"][1] = {
            "id": "node_add_tag_1",
            "type": "add_tag",
            "label": "Add after send",
            "draft_tag": "send-email-next-node",
        }
        self.db.automations.patch(automation["id"], {"published": published})
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertFalse(self.has_tag(contact_id, "send-email-next-node"))
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 1)

        self.cleanup(automation["id"])

    def test_send_email_completes_when_no_next_node(self):
        email, _ = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation_with_options(include_exit=False)
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "completed")
        self.assertEqual(result.json["step_run"]["node_type"], "send_email")
        self.assertEqual(len(self.debug_email_logs(automation["id"])), 1)

        self.cleanup(automation["id"])

    def test_suppressed_final_send_email_completes_enrolment(self):
        email, contact_id = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation_with_options(include_exit=False)
        enrolment = self.enrol(automation["id"], email)
        self.suppress_contact_prop(contact_id, "Unsubscribed")

        self.assert_suppressed_send_skips_and_advances(
            email,
            automation,
            enrolment,
            "unsubscribed",
            expected_status="completed",
            expected_node_id=None,
        )

        self.cleanup(automation["id"])

    def test_send_email_missing_referenced_email_fails_clearly(self):
        email, _ = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        self.db.set_cid(self.user_cookie["cid"])
        published = automation["published"].copy()
        published["nodes"][0] = published["nodes"][0].copy()
        published["nodes"][0]["automation_email_id"] = "missing-email-id"
        self.db.automations.patch(automation["id"], {"published": published})
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("Automation email is missing", result.text)
        self.assertEqual(self.debug_email_logs(automation["id"]), [])
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "held")
        self.assertEqual(data["last_failure_retryable"], False)
        self.assertEqual(data["last_failure_class"], "configuration")

        self.cleanup(automation["id"])

    def test_send_email_missing_fromname_fails_clearly(self):
        email, _ = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation_with_options(fromname="")
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("missing From Name", result.text)
        self.assertEqual(self.debug_email_logs(automation["id"]), [])
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "held")
        self.assertEqual(data["last_failure_retryable"], False)
        self.assertEqual(data["last_failure_class"], "configuration")

        self.cleanup(automation["id"])

    def test_send_email_missing_returnpath_fails_clearly(self):
        email, _ = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation_with_options(returnpath="")
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("missing Sender Email Address", result.text)
        self.assertEqual(self.debug_email_logs(automation["id"]), [])
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "held")
        self.assertEqual(data["last_failure_retryable"], False)
        self.assertEqual(data["last_failure_class"], "configuration")

        self.cleanup(automation["id"])

    def test_send_email_no_available_route_fails_clearly(self):
        email, _ = self.create_contact()
        self.assign_company_routes([])
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("No postal route available", result.text)
        self.assertEqual(self.debug_email_logs(automation["id"]), [])
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "held")
        self.assertEqual(data["last_failure_retryable"], False)
        self.assertEqual(data["last_failure_class"], "configuration")

        self.cleanup(automation["id"])

    def test_send_email_multiple_available_routes_fail_clearly(self):
        email, _ = self.create_contact()
        first_route = self.create_debug_route()
        second_route = self.create_debug_route()
        self.assign_company_routes([first_route, second_route])
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("Multiple postal routes available", result.text)
        self.assertEqual(self.debug_email_logs(automation["id"]), [])
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "held")
        self.assertEqual(data["last_failure_retryable"], False)
        self.assertEqual(data["last_failure_class"], "configuration")

        self.cleanup(automation["id"])

    def test_send_email_paused_enrolment_rejection_remains_intact(self):
        email, _ = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            {"status": "held"},
            self.user_cookie["cid"],
            automation["id"],
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("Enrolment is paused", result.text)
        self.assertEqual(self.debug_email_logs(automation["id"]), [])
        self.assertIsNone(self.enrolment_data(enrolment["id"]).get("claim_token"))

        self.cleanup(automation["id"])

    def test_running_claim_rejects_duplicate_run_next(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        now = datetime.utcnow().isoformat() + "Z"
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            {
                "status": "running",
                "running_status": "ready",
                "claim_token": "active-claim",
                "claimed_at": now,
                "claimed_node_id": "node_add_tag_1",
                "claimed_published_revision": automation["published_revision"],
            },
            self.user_cookie["cid"],
            automation["id"],
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("already running", result.text)
        self.assertFalse(self.has_tag(contact_id, "onboarding"))
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["claim_token"], "active-claim")

        self.cleanup(automation["id"])

    def test_stale_running_claim_can_be_recovered(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="stale-claim-tag")
        enrolment = self.enrol(automation["id"], email)
        stale = (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z"
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            {
                "status": "running",
                "running_status": "ready",
                "claim_token": "stale-claim",
                "claimed_at": stale,
                "claimed_node_id": "node_add_tag_1",
                "claimed_published_revision": automation["published_revision"],
                "retry_count": "bad-count",
                "retry_after": (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z",
            },
            self.user_cookie["cid"],
            automation["id"],
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(self.has_tag(contact_id, "stale-claim-tag"))
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assert_claim_cleared(result.json["enrolment"])
        self.assertIsNone(result.json["enrolment"].get("retry_after"))
        self.assertIsNone(result.json["enrolment"].get("retry_count"))

        self.cleanup(automation["id"])

    def test_stale_running_claim_with_non_runnable_status_is_not_recovered(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="stale-held-tag")
        enrolment = self.enrol(automation["id"], email)
        stale = (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z"
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            {
                "status": "running",
                "running_status": "held",
                "claim_token": "stale-held-claim",
                "claimed_at": stale,
                "claimed_node_id": "node_add_tag_1",
                "claimed_published_revision": automation["published_revision"],
            },
            self.user_cookie["cid"],
            automation["id"],
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("already running", result.text)
        self.assertFalse(self.has_tag(contact_id, "stale-held-tag"))
        self.assertEqual(self.enrolment_data(enrolment["id"])["claim_token"], "stale-held-claim")

        self.cleanup(automation["id"])

    def test_final_enrolment_update_requires_matching_claim_token(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where cid = %s and automation_id = %s and id = %s
            """,
            {
                "status": "running",
                "running_status": "ready",
                "claim_token": "correct-token",
                "claimed_at": datetime.utcnow().isoformat() + "Z",
                "claimed_node_id": "node_add_tag_1",
                "claimed_published_revision": automation["published_revision"],
            },
            self.user_cookie["cid"],
            automation["id"],
            enrolment["id"],
        )

        with self.assertRaises(falcon.HTTPConflict):
            automations._advance_claimed_enrolment(
                self.db,
                self.user_cookie["cid"],
                automation["id"],
                enrolment["id"],
                "wrong-token",
                {"status": "ready", "modified": datetime.utcnow().isoformat() + "Z"},
            )
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "running")
        self.assertEqual(data["claim_token"], "correct-token")

        self.cleanup(automation["id"])

    def test_send_email_failure_records_failed_step_run_and_releases_claim(self):
        email, _ = self.create_contact()
        route_id = self.create_drop_all_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        self.assertIn("Drop All Mail", result.text)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["retry_count"], 1)
        self.assertIsNotNone(data["retry_after"])
        self.assertEqual(data["last_failure_retryable"], True)
        self.assertEqual(data["last_failure_class"], "provider")
        self.assert_claim_cleared(data)
        runs = self.step_runs(automation["id"], enrolment["id"])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][6], "send_email")
        self.assertEqual(runs[0][7]["status"], "failed")
        self.assertIn("Drop All Mail", runs[0][7]["error"])
        self.assertEqual(runs[0][7]["retryable"], True)
        self.assertEqual(runs[0][7]["retry_count"], 1)
        self.assertIsNotNone(runs[0][7]["retry_after"])
        self.assertEqual(self.debug_email_logs(automation["id"]), [])

        self.cleanup(automation["id"])

    def test_retryable_send_email_failure_marks_failed_after_max_retries(self):
        email, _ = self.create_contact()
        route_id = self.create_drop_all_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.patch_enrolment_data(
            enrolment["id"],
            {
                "retry_count": 3,
                "retry_after": (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z",
            },
        )

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 400)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "failed")
        self.assertEqual(data["retry_count"], 4)
        self.assertIsNone(data.get("retry_after"))
        self.assertEqual(data["last_error"]["status"], "failed")
        self.assert_claim_cleared(data)

        self.cleanup(automation["id"])

    def test_success_clears_retry_failure_metadata_and_manual_run_bypasses_backoff(self):
        email, _ = self.create_contact()
        self.assign_single_debug_route()
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.patch_enrolment_data(
            enrolment["id"],
            {
                "retry_count": 1,
                "retry_after": (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z",
                "last_error": {"title": "Previous failure"},
                "last_failed_node_id": "node_send_email_1",
                "last_failed_node_type": "send_email",
                "last_failed_step_run_id": "previous-step-run",
                "last_failure_retryable": True,
                "last_failure_class": "provider",
            },
        )

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200, result.text)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertIsNone(data.get("retry_count"))
        self.assertIsNone(data.get("retry_after"))
        self.assertIsNone(data.get("last_error"))
        self.assertIsNone(data.get("last_failed_node_id"))
        self.assertIsNone(data.get("last_failed_step_run_id"))
        self.assertEqual(len(self.debug_email_logs(automation["id"])), 1)

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

    def test_terminal_enrolments_are_not_claimed(self):
        email, _ = self.create_contact()
        automation_ids = []
        try:
            for status in ("completed", "exited", "cancelled"):
                automation = self.create_automation(tag="%s-terminal" % status)
                automation_ids.append(automation["id"])
                enrolment = self.enrol(automation["id"], email)
                self.db.execute(
                    """
                    update automation_enrolments
                    set data = data || %s
                    where cid = %s and automation_id = %s and id = %s
                    """,
                    {"status": status},
                    self.user_cookie["cid"],
                    automation["id"],
                    enrolment["id"],
                )

                result = self.run_next(automation["id"], enrolment["id"])

                self.assertEqual(result.status_code, 400)
                self.assertIn("Enrolment is not ready", result.text)
                self.assertIsNone(self.enrolment_data(enrolment["id"]).get("claim_token"))
        finally:
            self.cleanup(*automation_ids)

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

    def test_execution_for_deleted_contact_is_blocked(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation()
        enrolment = self.enrol(automation["id"], email)

        self.db.execute(
            f"""delete from contacts."contacts_{self.user_cookie['cid']}" where contact_id = %s""",
            contact_id,
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 403)

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

    def test_if_has_tag_true_branch_moves_to_yes_target(self):
        email, contact_id = self.create_contact()
        automation = self.create_condition_automation()
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            f"""insert into contacts."contact_values_{self.user_cookie['cid']}"
            (contact_id, type, value) values (%s, 'tag', %s)
            on conflict (contact_id, type, value) do nothing""",
            contact_id,
            "vip",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertFalse(self.has_tag(contact_id, "branch-tag"))

        step_run = result.json["step_run"]
        self.assertEqual(step_run["node_id"], "node_condition_1")
        self.assertEqual(step_run["node_type"], "if_has_tag")
        self.assertEqual(step_run["node_label"], "If contact has tag")
        self.assertEqual(step_run["tag"], "vip")
        self.assertEqual(step_run["result"], True)
        self.assertEqual(step_run["branch"], "yes")
        self.assertEqual(step_run["target_node_id"], "node_add_tag_1")
        self.assertEqual(step_run["published_revision"], automation["published_revision"])
        self.assertEqual(step_run["status"], "succeeded")
        self.set_customer_automation_diagnostics(True)
        history = self.user_get("/api/automations/%s/history" % automation["id"])
        step_events = [event for event in history["events"] if event["type"] == "step_run"]
        self.assertEqual(step_events[0]["result"], True)
        self.assertEqual(step_events[0]["branch"], "yes")
        self.assertEqual(step_events[0]["target_node_id"], "node_add_tag_1")

        self.cleanup(automation["id"])

    def test_if_has_tag_false_branch_moves_to_no_target(self):
        email, _ = self.create_contact()
        automation = self.create_condition_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")

        step_run = result.json["step_run"]
        self.assertEqual(step_run["node_type"], "if_has_tag")
        self.assertEqual(step_run["tag"], "vip")
        self.assertEqual(step_run["result"], False)
        self.assertEqual(step_run["branch"], "no")
        self.assertEqual(step_run["target_node_id"], "node_exit_1")

        self.cleanup(automation["id"])

    def test_if_has_tag_target_missing_is_rejected_clearly(self):
        email, contact_id = self.create_contact()
        automation = self.create_condition_automation()
        published = automation["published"].copy()
        published["nodes"] = [
            node for node in published["nodes"] if node["id"] != "node_add_tag_1"
        ]
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation["id"], {"published": published})
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            f"""insert into contacts."contact_values_{self.user_cookie['cid']}"
            (contact_id, type, value) values (%s, 'tag', %s)
            on conflict (contact_id, type, value) do nothing""",
            contact_id,
            "vip",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("if_has_tag yes target was not found", result.text)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "held")
        self.assertEqual(data["last_failure_retryable"], False)
        self.assertEqual(data["last_failure_class"], "configuration")

        self.cleanup(automation["id"])

    def test_if_missing_tag_yes_branch_when_contact_lacks_tag(self):
        email, contact_id = self.create_contact()
        automation = self.create_condition_automation("if_missing_tag")
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertFalse(self.has_tag(contact_id, "branch-tag"))

        step_run = result.json["step_run"]
        self.assertEqual(step_run["node_type"], "if_missing_tag")
        self.assertEqual(step_run["node_label"], "If contact does not have tag")
        self.assertEqual(step_run["condition"], "missing_tag")
        self.assertEqual(step_run["tag"], "vip")
        self.assertEqual(step_run["has_tag"], False)
        self.assertEqual(step_run["result"], True)
        self.assertEqual(step_run["branch"], "yes")
        self.assertEqual(step_run["target_node_id"], "node_add_tag_1")
        self.assertEqual(step_run["published_revision"], automation["published_revision"])
        self.assertEqual(step_run["status"], "succeeded")

        self.cleanup(automation["id"])

    def test_if_missing_tag_no_branch_when_contact_has_tag(self):
        email, contact_id = self.create_contact()
        automation = self.create_condition_automation("if_missing_tag")
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            f"""insert into contacts."contact_values_{self.user_cookie['cid']}"
            (contact_id, type, value) values (%s, 'tag', %s)
            on conflict (contact_id, type, value) do nothing""",
            contact_id,
            "vip",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["node_type"], "if_missing_tag")
        self.assertEqual(result.json["step_run"]["condition"], "missing_tag")
        self.assertEqual(result.json["step_run"]["has_tag"], True)
        self.assertEqual(result.json["step_run"]["result"], False)
        self.assertEqual(result.json["step_run"]["branch"], "no")

        self.cleanup(automation["id"])

    def test_if_missing_tag_target_missing_is_rejected_clearly(self):
        email, contact_id = self.create_contact()
        automation = self.create_condition_automation("if_missing_tag")
        published = automation["published"].copy()
        published["nodes"] = [
            node for node in published["nodes"] if node["id"] != "node_add_tag_1"
        ]
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation["id"], {"published": published})
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("if_missing_tag yes target was not found", result.text)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "held")
        self.assertEqual(data["last_failure_retryable"], False)
        self.assertEqual(data["last_failure_class"], "configuration")

        self.cleanup(automation["id"])

    def test_if_missing_tag_publish_validation(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_missing_tag_validation_%s" % self.unique()},
        )
        nodes = [
            {
                "id": "node_condition_1",
                "type": "if_missing_tag",
                "label": "If contact does not have tag",
                "draft_tag": "",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add branch tag",
                "draft_tag": "branch-tag",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("If missing tag nodes must have draft tag configuration", result.text)

        nodes[0]["draft_tag"] = "vip"
        nodes[0]["yes_node_id"] = ""
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("If missing tag nodes must have a yes target", result.text)

        nodes[0]["yes_node_id"] = "missing-node"
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("If missing tag yes target must exist", result.text)

        nodes[0]["yes_node_id"] = "node_condition_1"
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("If missing tag nodes cannot target themselves", result.text)

        self.cleanup(automation["id"])

    def test_if_missing_tag_cycle_publishes_for_runtime_guard(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_missing_tag_cycle_%s" % self.unique()},
        )
        nodes = [
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add branch tag",
                "draft_tag": "branch-tag",
            },
            {
                "id": "node_condition_1",
                "type": "if_missing_tag",
                "label": "If contact does not have tag",
                "draft_tag": "vip",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["published"]["nodes"], nodes)

        self.cleanup(automation["id"])

    def test_if_conditions_valid_all_and_any_publish(self):
        automation_all = self.create_compound_condition_automation("all")
        self.assertEqual(automation_all["published"]["nodes"][0]["type"], "if_conditions")
        self.assertEqual(automation_all["published"]["nodes"][0]["condition"]["mode"], "all")
        self.cleanup(automation_all["id"])

        automation_any = self.create_compound_condition_automation("any")
        self.assertEqual(automation_any["published"]["nodes"][0]["condition"]["mode"], "any")
        self.cleanup(automation_any["id"])

    def test_if_conditions_publish_validation_rejects_empty_too_many_unknown_and_nested_items(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_compound_validation_%s" % self.unique()},
        )
        base_node = {
            "id": "node_compound_condition_1",
            "type": "if_conditions",
            "label": "If conditions",
            "condition": {
                "mode": "all",
                "items": [],
            },
            "yes_node_id": "node_add_tag_1",
            "no_node_id": "node_exit_1",
        }
        nodes = [
            base_node,
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add branch tag",
                "draft_tag": "compound-branch",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]
        result = self.simulate_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes), headers=self.headers())
        self.assertEqual(result.status_code, 400)
        self.assertIn("too short", result.text)

        nodes[0]["condition"]["items"] = [{"type": "has_tag", "tag": "tag-%s" % i} for i in range(21)]
        result = self.simulate_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes), headers=self.headers())
        self.assertEqual(result.status_code, 400)

        nodes[0]["condition"]["items"] = [{"type": "group", "mode": "all", "items": [{"type": "has_tag", "tag": "vip"}]}]
        self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes))
        result = self.simulate_post("/api/automations/%s/publish" % automation["id"], headers=self.headers())
        self.assertEqual(result.status_code, 400)
        self.assertIn("Nested condition groups are not supported yet", result.text)

        nodes[0]["condition"]["items"] = [{"type": "unknown_condition"}]
        result = self.simulate_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes), headers=self.headers())
        self.assertEqual(result.status_code, 400)

        self.cleanup(automation["id"])

    def test_if_conditions_publish_validation_rejects_missing_selectors(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_compound_selector_validation_%s" % self.unique()},
        )
        email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={"name": "Compound email", "subject": "Compound subject", "rawText": "<p>Hello</p>"},
        )
        lst = self.create_empty_list()
        base_items = [
            {"type": "has_tag", "tag": ""},
            {"type": "opened_email", "automation_email_id": ""},
            {"type": "clicked_email", "automation_email_id": email["id"], "click_match": "url_prefix", "link_url": ""},
            {"type": "in_list", "list_id": ""},
        ]
        expected = [
            "must select a tag",
            "must select an automation email",
            "URL conditions must have a link URL",
            "must select a contact list",
        ]
        for item, expected_text in zip(base_items, expected):
            nodes = [
                {
                    "id": "node_compound_condition_1",
                    "type": "if_conditions",
                    "label": "If conditions",
                    "condition": {"mode": "all", "items": [item]},
                    "yes_node_id": "node_add_tag_1",
                    "no_node_id": "node_exit_1",
                },
                {"id": "node_add_tag_1", "type": "add_tag", "label": "Add branch tag", "draft_tag": "compound-branch"},
                {"id": "node_exit_1", "type": "exit", "label": "Exit automation"},
            ]
            self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes))
            result = self.simulate_post("/api/automations/%s/publish" % automation["id"], headers=self.headers())
            self.assertEqual(result.status_code, 400)
            self.assertIn(expected_text, result.text)

        valid_items = [
            {"type": "has_tag", "tag": "vip"},
            {"type": "opened_email", "automation_email_id": email["id"]},
            {"type": "clicked_email", "automation_email_id": email["id"], "click_match": "url_exact", "link_url": "https://example.com"},
            {"type": "not_in_list", "list_id": lst["id"]},
        ]
        nodes[0]["condition"] = {"mode": "all", "items": valid_items}
        self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes))
        result = self.simulate_post("/api/automations/%s/publish" % automation["id"], headers=self.headers())
        self.assertEqual(result.status_code, 200)

        self.cleanup(automation["id"])

    def test_if_conditions_branch_target_validation_and_cycle_acceptance(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_compound_target_validation_%s" % self.unique()},
        )
        nodes = [
            {
                "id": "node_compound_condition_1",
                "type": "if_conditions",
                "label": "If conditions",
                "condition": {"mode": "all", "items": [{"type": "has_tag", "tag": "vip"}]},
                "yes_node_id": "",
                "no_node_id": "node_exit_1",
            },
            {"id": "node_add_tag_1", "type": "add_tag", "label": "Add branch tag", "draft_tag": "compound-branch"},
            {"id": "node_exit_1", "type": "exit", "label": "Exit automation"},
        ]
        self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes))
        result = self.simulate_post("/api/automations/%s/publish" % automation["id"], headers=self.headers())
        self.assertEqual(result.status_code, 400)
        self.assertIn("If conditions nodes must have a yes target", result.text)

        nodes[0]["yes_node_id"] = "missing-node"
        self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes))
        result = self.simulate_post("/api/automations/%s/publish" % automation["id"], headers=self.headers())
        self.assertEqual(result.status_code, 400)
        self.assertIn("If conditions yes target must exist", result.text)

        nodes[0]["yes_node_id"] = "node_compound_condition_1"
        self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes))
        result = self.simulate_post("/api/automations/%s/publish" % automation["id"], headers=self.headers())
        self.assertEqual(result.status_code, 400)
        self.assertIn("If conditions nodes cannot target themselves", result.text)

        nodes = [
            {"id": "node_add_tag_1", "type": "add_tag", "label": "Add branch tag", "draft_tag": "compound-branch"},
            {
                "id": "node_compound_condition_1",
                "type": "if_conditions",
                "label": "If conditions",
                "condition": {"mode": "all", "items": [{"type": "has_tag", "tag": "vip"}]},
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {"id": "node_exit_1", "type": "exit", "label": "Exit automation"},
        ]
        self.user_patch("/api/automations/%s" % automation["id"], json=self.workflow(nodes=nodes))
        result = self.simulate_post("/api/automations/%s/publish" % automation["id"], headers=self.headers())
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["published"]["nodes"], nodes)

        self.cleanup(automation["id"])

    def test_if_conditions_all_branches_yes_and_does_not_execute_target(self):
        email, contact_id = self.create_contact()
        self.add_existing_tag(contact_id, "vip")
        automation = self.create_compound_condition_automation("all")
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["node_type"], "if_conditions")
        self.assertEqual(result.json["step_run"]["action"], "if_conditions")
        self.assertEqual(result.json["step_run"]["mode"], "all")
        self.assertEqual(result.json["step_run"]["result"], True)
        self.assertEqual(result.json["step_run"]["branch"], "yes")
        self.assertEqual(result.json["step_run"]["evaluated_count"], 2)
        self.assertEqual(result.json["step_run"]["conditions"][0]["type"], "has_tag")
        self.assertFalse(self.has_tag(contact_id, "compound-branch"))

        self.cleanup(automation["id"])

    def test_if_conditions_all_branches_no_with_short_circuit(self):
        email, _ = self.create_contact()
        automation = self.create_compound_condition_automation("all")
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)
        self.assertEqual(result.json["step_run"]["branch"], "no")
        self.assertEqual(result.json["step_run"]["evaluated_count"], 1)

        self.cleanup(automation["id"])

    def test_if_conditions_any_branches_yes_and_no(self):
        email, _ = self.create_contact()
        automation = self.create_compound_condition_automation(
            "any",
            [
                {"type": "has_tag", "tag": "vip"},
                {"type": "missing_tag", "tag": "inactive"},
            ],
        )
        enrolment = self.enrol(automation["id"], email)
        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["result"], True)
        self.assertEqual(result.json["step_run"]["branch"], "yes")
        self.assertEqual(result.json["step_run"]["evaluated_count"], 2)
        self.cleanup(automation["id"])

        email, _ = self.create_contact()
        automation = self.create_compound_condition_automation(
            "any",
            [
                {"type": "has_tag", "tag": "vip"},
                {"type": "has_tag", "tag": "inactive"},
            ],
        )
        enrolment = self.enrol(automation["id"], email)
        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)
        self.assertEqual(result.json["step_run"]["branch"], "no")
        self.assertEqual(result.json["step_run"]["evaluated_count"], 2)
        self.cleanup(automation["id"])

    def test_if_conditions_email_engagement_scoped_to_current_enrolment(self):
        email, contact_id = self.create_contact()
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_compound_engagement_%s" % suffix},
        )
        automation_email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Compound engagement email",
                "subject": "Compound engagement subject",
                "rawText": "<p>Hello</p>",
            },
        )
        nodes = [
            {
                "id": "node_compound_condition_1",
                "type": "if_conditions",
                "label": "If conditions",
                "condition": {
                    "mode": "all",
                    "items": [
                        {
                            "type": "clicked_email",
                            "automation_email_id": automation_email["id"],
                            "click_match": "url_prefix",
                            "link_url": "https://example.com/offer",
                        },
                    ],
                },
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {"id": "node_add_tag_1", "type": "add_tag", "label": "Add branch tag", "draft_tag": "compound-branch"},
            {"id": "node_exit_1", "type": "exit", "label": "Exit automation"},
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes, reentry="multiple"),
        )
        automation = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json
        automation_email_id = automation_email["id"]

        first_enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            first_enrolment["id"],
            contact_id,
            email,
            automation_email_id,
            event_type="click",
            event_data={"link_url": "https://example.com/offer?utm=1", "test_id": self.test_id},
        )
        first = self.run_next(automation["id"], first_enrolment["id"])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(first.json["step_run"]["result"], True)
        self.assertEqual(self.run_next(automation["id"], first_enrolment["id"]).status_code, 200)
        exited = self.run_next(automation["id"], first_enrolment["id"])
        self.assertEqual(exited.json["enrolment"]["status"], "exited")

        second_enrolment = self.enrol(automation["id"], email)
        second = self.run_next(automation["id"], second_enrolment["id"])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(second.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def assert_if_conditions_clicked_email_counts_current_enrolment_only(self, click_match, configured_url=None, event_url=None):
        email, contact_id = self.create_contact()
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_compound_click_scope_%s" % suffix},
        )
        automation_email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Compound click scope email",
                "subject": "Compound click scope subject",
                "rawText": "<p>Hello</p>",
            },
        )
        item = {
            "type": "clicked_email",
            "automation_email_id": automation_email["id"],
            "click_match": click_match,
        }
        if configured_url is not None:
            item["link_url"] = configured_url
        nodes = [
            {
                "id": "node_compound_condition_1",
                "type": "if_conditions",
                "label": "If conditions",
                "condition": {
                    "mode": "all",
                    "items": [item],
                },
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {"id": "node_add_tag_1", "type": "add_tag", "label": "Add branch tag", "draft_tag": "compound-branch"},
            {"id": "node_exit_1", "type": "exit", "label": "Exit automation"},
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes, reentry="multiple"),
        )
        automation = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

        first_enrolment = self.enrol(automation["id"], email)
        event_data = {"test_id": self.test_id}
        if event_url is not None:
            event_data["link_url"] = event_url
        self.insert_open_event(
            automation["id"],
            first_enrolment["id"],
            contact_id,
            email,
            automation_email["id"],
            event_type="click",
            event_data=event_data,
        )
        first = self.run_next(automation["id"], first_enrolment["id"])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(first.json["step_run"]["result"], True)
        self.assertEqual(first.json["step_run"]["conditions"][0]["click_match"], click_match)
        if click_match == "url":
            self.assertEqual(first.json["step_run"]["conditions"][0]["effective_click_match"], "url_exact")
        else:
            self.assertEqual(first.json["step_run"]["conditions"][0]["effective_click_match"], click_match)
        self.assertEqual(self.run_next(automation["id"], first_enrolment["id"]).status_code, 200)
        exited = self.run_next(automation["id"], first_enrolment["id"])
        self.assertEqual(exited.status_code, 200)
        self.assertEqual(exited.json["enrolment"]["status"], "exited")

        second_enrolment = self.enrol(automation["id"], email)
        second = self.run_next(automation["id"], second_enrolment["id"])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(second.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_conditions_clicked_email_legacy_url_counts_current_enrolment_only(self):
        self.assert_if_conditions_clicked_email_counts_current_enrolment_only(
            "url",
            configured_url="https://example.com/compound",
            event_url="https://example.com/compound",
        )

    def test_if_conditions_clicked_email_any_counts_current_enrolment_only(self):
        self.assert_if_conditions_clicked_email_counts_current_enrolment_only(
            "any",
        )

    def test_if_conditions_clicked_email_url_exact_counts_current_enrolment_only(self):
        self.assert_if_conditions_clicked_email_counts_current_enrolment_only(
            "url_exact",
            configured_url="https://example.com/compound",
            event_url="https://example.com/compound",
        )

    def test_if_conditions_clicked_email_url_prefix_counts_current_enrolment_only(self):
        self.assert_if_conditions_clicked_email_counts_current_enrolment_only(
            "url_prefix",
            configured_url="https://example.com/compound",
            event_url="https://example.com/compound?utm=1",
        )

    def test_if_conditions_list_membership_conditions(self):
        email, contact_id = self.create_contact()
        in_list_id = self.contact_list_ids(contact_id)[0]
        not_in_list = self.create_empty_list()
        automation = self.create_compound_condition_automation(
            "all",
            [
                {"type": "in_list", "list_id": in_list_id},
                {"type": "not_in_list", "list_id": not_in_list["id"]},
            ],
        )
        enrolment = self.enrol(automation["id"], email)
        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["result"], True)
        self.assertEqual(result.json["step_run"]["conditions"][0]["in_list"], True)
        self.assertEqual(result.json["step_run"]["conditions"][1]["in_list"], False)

        self.cleanup(automation["id"])

    def test_if_opened_email_true_branch_when_matching_open_exists(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_opened_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertFalse(self.has_tag(contact_id, "engaged-branch"))

        step_run = result.json["step_run"]
        self.assertEqual(step_run["node_id"], "node_email_condition_1")
        self.assertEqual(step_run["node_type"], "if_opened_email")
        self.assertEqual(step_run["action"], "if_opened_email")
        self.assertEqual(step_run["automation_email_id"], automation["engagement_email_id"])
        self.assertEqual(step_run["automation_email_name"], "Engagement condition email")
        self.assertEqual(step_run["subject"], "Engagement condition subject")
        self.assertEqual(step_run["result"], True)
        self.assertEqual(step_run["branch"], "yes")
        self.assertEqual(step_run["target_node_id"], "node_add_tag_1")
        self.assertEqual(step_run["published_revision"], automation["published_revision"])
        self.assertEqual(step_run["status"], "succeeded")

        self.cleanup(automation["id"])

    def test_if_opened_email_false_branch_when_no_open_exists(self):
        email, _ = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_opened_email")
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)
        self.assertEqual(result.json["step_run"]["branch"], "no")
        self.assertEqual(result.json["step_run"]["target_node_id"], "node_exit_1")

        self.cleanup(automation["id"])

    def test_if_opened_email_true_branch_when_inferred_open_exists(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_opened_email")
        enrolment = self.enrol(automation["id"], email)
        event_id = self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
        )
        self.db.execute(
            "update automation_email_events set data = data || %s where id = %s",
            {"inferred": True, "inferred_from_event_type": "click"},
            event_id,
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["result"], True)
        self.assertEqual(result.json["step_run"]["branch"], "yes")

        self.cleanup(automation["id"])

    def test_if_opened_email_ignores_open_from_another_enrolment(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_opened_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_enrolment_id="other-enrolment-%s" % self.unique(),
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_opened_email_ignores_open_from_another_automation_email(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_opened_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_automation_email_id="other-email-%s" % self.unique(),
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_opened_email_ignores_open_from_another_contact_or_account(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_opened_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_contact_id=contact_id + 100000,
        )
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_cid="other-account-%s" % self.unique(),
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_opened_email_target_missing_is_rejected_clearly(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_opened_email")
        published = automation["published"].copy()
        published["nodes"] = [
            node for node in published["nodes"] if node["id"] != "node_add_tag_1"
        ]
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation["id"], {"published": published})
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("if_opened_email yes target was not found", result.text)

        self.cleanup(automation["id"])

    def test_if_opened_email_missing_email_is_rejected_clearly(self):
        email, _ = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_opened_email")
        self.db.execute(
            "delete from automation_emails where id = %s and cid = %s",
            automation["engagement_email_id"],
            self.user_cookie["cid"],
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("if_opened_email node references an automation email that was not found", result.text)

        self.cleanup(automation["id"])

    def test_if_clicked_email_true_branch_when_matching_click_exists(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_clicked_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertFalse(self.has_tag(contact_id, "engaged-branch"))

        step_run = result.json["step_run"]
        self.assertEqual(step_run["node_id"], "node_email_condition_1")
        self.assertEqual(step_run["node_type"], "if_clicked_email")
        self.assertEqual(step_run["action"], "if_clicked_email")
        self.assertEqual(step_run["automation_email_id"], automation["engagement_email_id"])
        self.assertEqual(step_run["automation_email_name"], "Engagement condition email")
        self.assertEqual(step_run["subject"], "Engagement condition subject")
        self.assertEqual(step_run["result"], True)
        self.assertEqual(step_run["branch"], "yes")
        self.assertEqual(step_run["target_node_id"], "node_add_tag_1")
        self.assertEqual(step_run["published_revision"], automation["published_revision"])
        self.assertEqual(step_run["status"], "succeeded")

        self.cleanup(automation["id"])

    def test_if_clicked_email_false_branch_when_no_click_exists(self):
        email, _ = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_clicked_email")
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)
        self.assertEqual(result.json["step_run"]["branch"], "no")
        self.assertEqual(result.json["step_run"]["target_node_id"], "node_exit_1")

        self.cleanup(automation["id"])

    def test_if_clicked_email_specific_url_true_branch_when_matching_click_exists(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url",
                "link_url": "https://example.com/offer",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
            event_data={"link_url": "https://example.com/offer", "test_id": self.test_id},
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["result"], True)
        self.assertEqual(result.json["step_run"]["branch"], "yes")
        self.assertEqual(result.json["step_run"]["click_match"], "url")
        self.assertEqual(result.json["step_run"]["link_url"], "https://example.com/offer")
        self.assertEqual(result.json["step_run"]["normalized_link_url"], "https://example.com/offer")

        self.cleanup(automation["id"])

    def test_if_clicked_email_specific_url_false_branch_for_different_url(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url",
                "link_url": "https://example.com/offer",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
            event_data={"link_url": "https://example.com/other", "test_id": self.test_id},
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)
        self.assertEqual(result.json["step_run"]["branch"], "no")

        self.cleanup(automation["id"])

    def test_if_clicked_email_url_exact_true_branch_when_matching_click_exists(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url_exact",
                "link_url": "https://example.com/offer",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
            event_data={"link_url": "https://example.com/offer", "test_id": self.test_id},
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["result"], True)
        self.assertEqual(result.json["step_run"]["click_match"], "url_exact")
        self.assertEqual(result.json["step_run"]["effective_click_match"], "url_exact")

        self.cleanup(automation["id"])

    def test_if_clicked_email_url_prefix_matches_query_and_hash_not_sibling_path(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url_prefix",
                "link_url": "https://example.com/somepage",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
            event_data={"link_url": "https://example.com/somepage?utm=1", "test_id": self.test_id},
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["result"], True)
        self.assertEqual(result.json["step_run"]["click_match"], "url_prefix")
        self.assertEqual(result.json["step_run"]["effective_click_match"], "url_prefix")
        self.assertEqual(result.json["step_run"]["matched_link_url"], "https://example.com/somepage?utm=1")

        self.cleanup(automation["id"])

        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url_prefix",
                "link_url": "https://example.com/somepage",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
            event_data={"link_url": "https://example.com/somepage#section", "test_id": self.test_id},
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["result"], True)

        self.cleanup(automation["id"])

        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url_prefix",
                "link_url": "https://example.com/somepage",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
            event_data={"link_url": "https://example.com/somepage-other", "test_id": self.test_id},
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_clicked_email_specific_url_normalizes_bare_domain_and_host_case(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url",
                "link_url": "Example.com/Offer",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
            event_data={"link_url": "http://example.com/Offer", "test_id": self.test_id},
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(result.json["step_run"]["result"], True)
        self.assertEqual(result.json["step_run"]["normalized_link_url"], "http://example.com/Offer")

        self.cleanup(automation["id"])

    def test_if_clicked_email_specific_url_open_event_does_not_count(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url",
                "link_url": "https://example.com/offer",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_data={"link_url": "https://example.com/offer", "test_id": self.test_id},
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_clicked_email_specific_url_ignores_other_scopes(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            {
                "click_match": "url",
                "link_url": "https://example.com/offer",
            },
        )
        enrolment = self.enrol(automation["id"], email)
        for overrides in (
            {"event_enrolment_id": "other-enrolment-%s" % self.unique()},
            {"event_automation_email_id": "other-email-%s" % self.unique()},
            {"event_contact_id": contact_id + 100000},
            {"event_cid": "other-account-%s" % self.unique()},
        ):
            self.insert_open_event(
                automation["id"],
                enrolment["id"],
                contact_id,
                email,
                automation["engagement_email_id"],
                event_type="click",
                event_data={"link_url": "https://example.com/offer", "test_id": self.test_id},
                **overrides
            )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_clicked_email_specific_url_publish_validation(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_click_url_validation_%s" % self.unique()},
        )
        email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Click validation email",
                "subject": "Click validation subject",
                "rawText": "<p>Hello</p>",
            },
        )
        nodes = [
            {
                "id": "node_email_condition_1",
                "type": "if_clicked_email",
                "label": "If clicked email",
                "automation_email_id": email["id"],
                "click_match": "url",
                "link_url": "",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add engaged branch tag",
                "draft_tag": "engaged-branch",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )

        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("must have a link URL", result.text)

        nodes[0]["click_match"] = "url_exact"
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("must have a link URL", result.text)

        nodes[0]["click_match"] = "url_prefix"
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
        )
        result = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("must have a link URL", result.text)

        self.cleanup(automation["id"])

    def test_if_clicked_email_unknown_click_match_is_rejected(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_click_match_validation_%s" % self.unique()},
        )
        email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Click match validation email",
                "subject": "Click match validation subject",
                "rawText": "<p>Hello</p>",
            },
        )
        nodes = [
            {
                "id": "node_email_condition_1",
                "type": "if_clicked_email",
                "label": "If clicked email",
                "automation_email_id": email["id"],
                "click_match": "something_else",
                "yes_node_id": "node_add_tag_1",
                "no_node_id": "node_exit_1",
            },
            {
                "id": "node_add_tag_1",
                "type": "add_tag",
                "label": "Add engaged branch tag",
                "draft_tag": "engaged-branch",
            },
            {
                "id": "node_exit_1",
                "type": "exit",
                "label": "Exit automation",
            },
        ]
        result = self.simulate_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=nodes),
            headers=self.headers(),
        )
        self.assertEqual(result.status_code, 400)

        self.cleanup(automation["id"])

    def test_if_clicked_email_ignores_click_from_another_enrolment(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_clicked_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_enrolment_id="other-enrolment-%s" % self.unique(),
            event_type="click",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def assert_click_condition_counts_current_enrolment_only(self, node_overrides, event_url=None):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation_with_options(
            "if_clicked_email",
            node_overrides,
            reentry="multiple",
        )

        first_enrolment = self.enrol(automation["id"], email)
        event_data = {"test_id": self.test_id}
        if event_url:
            event_data["link_url"] = event_url
        self.insert_open_event(
            automation["id"],
            first_enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
            event_data=event_data,
        )

        first_result = self.run_next(automation["id"], first_enrolment["id"])
        self.assertEqual(first_result.status_code, 200)
        self.assertEqual(first_result.json["enrolment"]["current_node_id"], "node_add_tag_1")
        self.assertEqual(first_result.json["step_run"]["result"], True)
        self.assertEqual(first_result.json["step_run"]["branch"], "yes")
        add_tag_result = self.run_next(automation["id"], first_enrolment["id"])
        self.assertEqual(add_tag_result.status_code, 200)
        self.assertEqual(add_tag_result.json["enrolment"]["status"], "ready")
        self.assertEqual(add_tag_result.json["enrolment"]["current_node_id"], "node_exit_1")
        exit_result = self.run_next(automation["id"], first_enrolment["id"])
        self.assertEqual(exit_result.status_code, 200)
        self.assertEqual(exit_result.json["enrolment"]["status"], "exited")

        second_enrolment = self.enrol(automation["id"], email)
        second_result = self.run_next(automation["id"], second_enrolment["id"])
        self.assertEqual(second_result.status_code, 200)
        self.assertEqual(second_result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(second_result.json["step_run"]["result"], False)
        self.assertEqual(second_result.json["step_run"]["branch"], "no")

        self.cleanup(automation["id"])

    def test_if_clicked_email_any_click_counts_current_enrolment_only(self):
        self.assert_click_condition_counts_current_enrolment_only({}, event_url=None)

    def test_if_clicked_email_legacy_url_counts_current_enrolment_only(self):
        self.assert_click_condition_counts_current_enrolment_only(
            {
                "click_match": "url",
                "link_url": "https://example.com/offer",
            },
            event_url="https://example.com/offer",
        )

    def test_if_clicked_email_url_exact_counts_current_enrolment_only(self):
        self.assert_click_condition_counts_current_enrolment_only(
            {
                "click_match": "url_exact",
                "link_url": "https://example.com/offer",
            },
            event_url="https://example.com/offer",
        )

    def test_if_clicked_email_url_prefix_counts_current_enrolment_only(self):
        self.assert_click_condition_counts_current_enrolment_only(
            {
                "click_match": "url_prefix",
                "link_url": "https://example.com/offer",
            },
            event_url="https://example.com/offer?utm=1",
        )

    def test_if_clicked_email_ignores_click_from_another_automation_email(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_clicked_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_automation_email_id="other-email-%s" % self.unique(),
            event_type="click",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_clicked_email_ignores_click_from_another_contact_or_account(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_clicked_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_contact_id=contact_id + 100000,
            event_type="click",
        )
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_cid="other-account-%s" % self.unique(),
            event_type="click",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_clicked_email_open_event_does_not_count_as_click(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_clicked_email")
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["step_run"]["result"], False)

        self.cleanup(automation["id"])

    def test_if_clicked_email_target_missing_is_rejected_clearly(self):
        email, contact_id = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_clicked_email")
        published = automation["published"].copy()
        published["nodes"] = [
            node for node in published["nodes"] if node["id"] != "node_add_tag_1"
        ]
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation["id"], {"published": published})
        enrolment = self.enrol(automation["id"], email)
        self.insert_open_event(
            automation["id"],
            enrolment["id"],
            contact_id,
            email,
            automation["engagement_email_id"],
            event_type="click",
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("if_clicked_email yes target was not found", result.text)

        self.cleanup(automation["id"])

    def test_if_clicked_email_missing_email_is_rejected_clearly(self):
        email, _ = self.create_contact()
        automation = self.create_email_engagement_condition_automation("if_clicked_email")
        self.db.execute(
            "delete from automation_emails where id = %s and cid = %s",
            automation["engagement_email_id"],
            self.user_cookie["cid"],
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("if_clicked_email node references an automation email that was not found", result.text)

        self.cleanup(automation["id"])

    def test_go_to_moves_to_target_without_executing_it(self):
        email, _ = self.create_contact()
        automation = self.create_go_to_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")

        step_run = result.json["step_run"]
        self.assertEqual(step_run["node_id"], "node_go_to_1")
        self.assertEqual(step_run["node_type"], "go_to")
        self.assertEqual(step_run["node_label"], "Go to exit")
        self.assertEqual(step_run["target_node_id"], "node_exit_1")
        self.assertEqual(step_run["published_revision"], automation["published_revision"])
        self.assertEqual(step_run["status"], "succeeded")
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 1)
        self.set_customer_automation_diagnostics(True)
        history = self.user_get("/api/automations/%s/history" % automation["id"])
        step_events = [event for event in history["events"] if event["type"] == "step_run"]
        self.assertEqual(step_events[0]["target_node_id"], "node_exit_1")

        second = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json["enrolment"]["status"], "exited")

        self.cleanup(automation["id"])

    def test_wait_guarded_loop_starts_a_fresh_wait_on_each_visit(self):
        email, _ = self.create_contact()
        nodes = [
            {"id": "wait", "type": "wait_duration", "label": "Wait", "duration": {"days": 0, "hours": 0, "minutes": 5}},
            {"id": "go", "type": "go_to", "label": "Repeat", "target_node_id": "wait"},
        ]
        automation = self.create_automation(nodes=nodes)
        self.assertIn("published", automation)
        self.addCleanup(self.cleanup, automation["id"])
        enrolment = self.enrol(automation["id"], email)
        first = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["enrolment"]["status"], "waiting")
        # Simulate an actually elapsed wait, without sleeping or skipping it.
        past = (datetime.utcnow() - timedelta(minutes=6)).isoformat() + "Z"
        state = first.json["enrolment"]
        state["wait"]["started_at"] = past
        state["wake_at"] = past
        state["transitions_without_wait"] = 1000
        self.db.execute("update automation_enrolments set data = data || %s where id = %s", state, enrolment["id"])
        complete = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(complete.status_code, 200, complete.text)
        self.assertEqual(complete.json["enrolment"]["transitions_without_wait"], 1)
        self.assertEqual(complete.json["enrolment"]["visited_node_ids"], [])
        self.assertIsNone(complete.json["enrolment"]["wait"])
        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).json["enrolment"]["current_node_id"], "wait")
        repeated = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(repeated.json["enrolment"]["status"], "waiting")
        self.assertGreater(repeated.json["enrolment"]["wait"]["started_at"], past)
        self.assertGreater((dateutil.parser.parse(repeated.json["enrolment"]["wake_at"]) - dateutil.parser.parse(repeated.json["enrolment"]["wait"]["started_at"])).total_seconds(), 299)

    def test_runtime_holds_before_repeating_action_and_releases_claim(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        self.addCleanup(self.cleanup, automation["id"])
        nodes = automation["published"]["nodes"]
        nodes[-1] = {"id": nodes[-1]["id"], "type": "go_to", "label": "Malformed loop", "target_node_id": nodes[0]["id"]}
        self.db.automations.patch(automation["id"], {"published": {**automation["published"], "nodes": nodes}})
        enrolment = self.enrol(automation["id"], email)
        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 200)
        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 200)
        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("loop detected", result.text)
        state = self.enrolment_data(enrolment["id"])
        self.assertEqual(state["status"], "held")
        self.assertFalse(state.get("claim_token"))
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 2)
        self.assertTrue(all(row[7]["status"] == "succeeded" for row in self.step_runs(automation["id"], enrolment["id"])))

    def test_visit_guard_catches_inner_loops_and_both_condition_outcomes_across_ticks(self):
        for kind in ("if_has_tag", "if_missing_tag", "if_conditions"):
            for yes in (False, True):
                with self.subTest(kind=kind, yes=yes):
                    email, contact_id = self.create_contact()
                    if yes != (kind == "if_missing_tag"):
                        self.add_existing_tag(contact_id, "vip")
                    condition = {"id": "branch", "type": kind, "label": "Branch", "yes_node_id": "left", "no_node_id": "right"}
                    if kind == "if_conditions":
                        condition["condition"] = {"mode": "all", "items": [{"type": "has_tag", "tag": "vip"}]}
                    else:
                        condition["draft_tag"] = "vip"
                    nodes = [{"id": "entry", "type": "add_tag", "label": "Once", "draft_tag": "once"}, condition,
                             {"id": "left", "type": "go_to", "label": "Left", "target_node_id": "branch"},
                             {"id": "right", "type": "go_to", "label": "Right", "target_node_id": "branch"}]
                    a = self.create_automation(nodes=nodes)
                    self.addCleanup(self.cleanup, a["id"])
                    e = self.enrol(a["id"], email)
                    for expected in ("branch", "left" if yes else "right", "branch"):
                        result = self.run_next(a["id"], e["id"])
                        self.assertEqual(result.status_code, 200, result.text)
                        self.assertEqual(result.json["enrolment"]["current_node_id"], expected)
                    # The loop never returns to the enrolment's entry node.
                    self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 400)
                    state = self.enrolment_data(e["id"])
                    self.assertEqual(state["status"], "held")
                    self.assert_claim_cleared(state)
                    self.assertEqual(len(self.step_runs(a["id"], e["id"])), 3)

    def test_visit_history_survives_pause_resume_and_publication(self):
        email, _ = self.create_contact()
        a = self.create_automation(nodes=[
            {"id": "tag", "type": "add_tag", "label": "Tag", "draft_tag": "once"},
            {"id": "go", "type": "go_to", "label": "Again", "target_node_id": "tag"}])
        self.addCleanup(self.cleanup, a["id"])
        e = self.enrol(a["id"], email)
        self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 200)
        self.user_post("/api/automations/%s/pause" % a["id"])
        self.user_post("/api/automations/%s/publish" % a["id"])
        self.assertEqual(self.enrolment_data(e["id"])["visited_node_ids"], ["tag"])
        self.user_post("/api/automations/%s/resume" % a["id"])
        self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 200)
        self.assertIn("loop detected", self.run_next(a["id"], e["id"]).text)

    def test_skipped_or_instantly_elapsed_wait_does_not_clear_visits(self):
        for instant in (False, True):
            with self.subTest(instant=instant):
                email, _ = self.create_contact()
                a = self.create_automation(nodes=[
                    {"id": "wait", "type": "wait_duration", "label": "Wait", "duration": {"days": 0, "hours": 0, "minutes": 5}},
                    {"id": "go", "type": "go_to", "label": "Again", "target_node_id": "wait"}])
                self.addCleanup(self.cleanup, a["id"])
                e = self.enrol(a["id"], email)
                start = self.run_next(a["id"], e["id"])
                self.assertEqual(start.json["enrolment"]["visited_node_ids"], ["wait"])
                if instant:
                    self.patch_enrolment_data(e["id"], {"wake_at": (datetime.utcnow() - timedelta(seconds=1)).isoformat() + "Z"})
                    complete = self.run_next(a["id"], e["id"])
                else:
                    complete = self.run_next_skip_wait(a["id"], e["id"])
                self.assertEqual(complete.status_code, 200, complete.text)
                self.assertEqual(complete.json["enrolment"]["visited_node_ids"], ["wait"])
                self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 200)
                self.assertIn("loop detected", self.run_next(a["id"], e["id"]).text)

    def test_malformed_visit_history_fails_closed_without_action(self):
        for invalid in ("tag", [1], None):
            with self.subTest(invalid=invalid):
                email, contact_id = self.create_contact()
                a = self.create_automation(tag="must-not-run")
                self.addCleanup(self.cleanup, a["id"])
                e = self.enrol(a["id"], email)
                self.patch_enrolment_data(e["id"], {"visited_node_ids": invalid})
                result = self.run_next(a["id"], e["id"])
                self.assertEqual(result.status_code, 400)
                self.assertFalse(self.has_tag(contact_id, "must-not-run"))
                self.assert_claim_cleared(self.enrolment_data(e["id"]))

    def test_email_throttle_spans_nodes_and_reenrolments_but_not_contacts(self):
        self.assign_single_debug_route()
        email, _ = self.create_contact()
        other_email, _ = self.create_contact()
        a = self.create_send_email_automation()
        self.addCleanup(self.cleanup, a["id"])
        first = a["published"]["nodes"][0]
        nodes = [first, {**first, "id": "second"}, a["published"]["nodes"][-1]]
        self.user_patch("/api/automations/%s" % a["id"], json=self.workflow(nodes=nodes, reentry="multiple"))
        self.user_post("/api/automations/%s/publish" % a["id"])
        e = self.enrol(a["id"], email)
        sent = self.run_next(a["id"], e["id"])
        self.assertTrue(sent.json["step_run"]["sent"])
        skipped = self.run_next(a["id"], e["id"])
        self.assertFalse(skipped.json["step_run"]["sent"])
        self.assertTrue(skipped.json["step_run"]["throttled"])
        self.assertEqual(skipped.json["enrolment"]["current_node_id"], "node_exit_1")
        self.run_next(a["id"], e["id"])
        again = self.enrol(a["id"], email)
        self.assertTrue(self.run_next(a["id"], again["id"]).json["step_run"]["throttled"])
        other = self.enrol(a["id"], other_email)
        self.assertTrue(self.run_next(a["id"], other["id"]).json["step_run"]["sent"])
        self.assertEqual(len(self.debug_email_logs(a["id"])), 2)

    def test_two_email_loop_resets_visits_after_wait_but_throttles_both_emails(self):
        self.assign_single_debug_route()
        email, _ = self.create_contact()
        a = self.create_send_email_automation()
        self.addCleanup(self.cleanup, a["id"])
        second = self.user_post("/api/automations/%s/emails" % a["id"], json={
            "name": "Second", "subject": "Second", "rawText": "<p>Second</p>",
            "fromname": "Automation Sender", "returnpath": "automation-sender@example.com"})
        first = a["published"]["nodes"][0]
        nodes = [first, {**first, "id": "second", "automation_email_id": second["id"]},
                 {"id": "wait", "type": "wait_duration", "label": "Wait", "duration": {"days": 0, "hours": 0, "minutes": 10}},
                 {"id": "go", "type": "go_to", "label": "Repeat", "target_node_id": first["id"]}]
        self.user_patch("/api/automations/%s" % a["id"], json=self.workflow(nodes=nodes))
        self.user_post("/api/automations/%s/publish" % a["id"])
        e = self.enrol(a["id"], email)
        for _ in range(2):
            self.assertTrue(self.run_next(a["id"], e["id"]).json["step_run"]["sent"])
        waiting = self.run_next(a["id"], e["id"]).json["enrolment"]
        waiting["wait"]["started_at"] = (datetime.utcnow() - timedelta(minutes=11)).isoformat() + "Z"
        waiting["wake_at"] = (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"
        self.patch_enrolment_data(e["id"], waiting)
        self.assertEqual(self.run_next(a["id"], e["id"]).json["enrolment"]["visited_node_ids"], [])
        self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 200)
        for _ in range(2):
            result = self.run_next(a["id"], e["id"])
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json["step_run"]["throttled"])
        self.assertEqual(self.run_next(a["id"], e["id"]).json["enrolment"]["status"], "waiting")
        self.assertEqual(len(self.debug_email_logs(a["id"])), 2)

    def test_email_throttle_expires_after_rolling_24_hours(self):
        self.assign_single_debug_route()
        email, _ = self.create_contact()
        a = self.create_send_email_automation()
        self.addCleanup(self.cleanup, a["id"])
        first = a["published"]["nodes"][0]
        nodes = [first, {**first, "id": "second"}, a["published"]["nodes"][-1]]
        self.user_patch("/api/automations/%s" % a["id"], json=self.workflow(nodes=nodes))
        self.user_post("/api/automations/%s/publish" % a["id"])
        e = self.enrol(a["id"], email)
        sent = self.run_next(a["id"], e["id"])
        old = (datetime.utcnow() - timedelta(hours=24, seconds=1)).isoformat() + "Z"
        automations._patch_step_run(self.db, self.user_cookie["cid"], sent.json["step_run"]["id"], {"email_sent_at": old})
        result = self.run_next(a["id"], e["id"])
        self.assertTrue(result.json["step_run"]["sent"])
        self.assertFalse(result.json["step_run"]["throttled"])
        self.assertEqual(len(self.debug_email_logs(a["id"])), 2)

    def test_uncertain_email_send_holds_and_retry_does_not_send_again(self):
        from unittest.mock import patch
        self.assign_single_debug_route()
        email, _ = self.create_contact()
        a = self.create_send_email_automation()
        self.addCleanup(self.cleanup, a["id"])
        e = self.enrol(a["id"], email)
        with patch.object(automations, "send_backend_mail", side_effect=TimeoutError("Ambiguous delivery")) as send:
            result = self.run_next(a["id"], e["id"])
            self.assertEqual(result.status_code, 400)
            self.assertIn("delivery uncertain", result.text)
            state = self.enrolment_data(e["id"])
            self.assertEqual(state["status"], "held")
            self.assert_claim_cleared(state)
            self.assertFalse(state.get("visited_node_ids"))
            # Even an operator reactivation cannot accidentally retry an uncertain send.
            self.patch_enrolment_data(e["id"], {"status": "ready"})
            self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 400)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(self.debug_email_logs(a["id"]), [])

    def test_plural_tags_add_remove_atomically_and_preserve_singular_nodes(self):
        for action in ("add_tag", "remove_tag"):
            with self.subTest(action=action):
                email, contact_id = self.create_contact()
                tags = ["customer", "paid", "active"]
                if action == "remove_tag":
                    for tag in tags: self.add_existing_tag(contact_id, tag)
                a = self.create_automation(nodes=[{"id": "tags", "type": action, "label": "Tags", "draft_tags": tags}, {"id": "end", "type": "exit", "label": "End"}])
                self.addCleanup(self.cleanup, a["id"])
                self.assertEqual(a["published"]["nodes"][0]["draft_tags"], tags)
                e = self.enrol(a["id"], email)
                result = self.run_next(a["id"], e["id"])
                self.assertEqual(result.status_code, 200, result.text)
                for tag in tags: self.assertEqual(self.has_tag(contact_id, tag), action == "add_tag")
                self.assertEqual(result.json["step_run"]["tags"], tags)
                self.assertEqual(result.json["enrolment"]["current_node_id"], "end")

    def test_plural_tag_failure_rolls_back_entire_batch_and_releases_claim(self):
        from unittest.mock import patch
        for action in ("add_tag", "remove_tag"):
            with self.subTest(action=action):
                email, contact_id = self.create_contact()
                if action == "remove_tag":
                    for tag in ("first", "second"): self.add_existing_tag(contact_id, tag)
                a = self.create_automation(nodes=[{"id": "tags", "type": action, "label": "Tags", "draft_tags": ["first", "second"]}])
                self.addCleanup(self.cleanup, a["id"])
                e = self.enrol(a["id"], email)
                helper = getattr(automations.contacts, action)
                def failing(*args, **kwargs):
                    if args[4] == "second": raise ValueError("Injected batch failure")
                    return helper(*args, **kwargs)
                with patch.object(automations.contacts, action, side_effect=failing):
                    result = self.run_next(a["id"], e["id"])
                self.assertEqual(result.status_code, 400, result.text)
                for tag in ("first", "second"): self.assertEqual(self.has_tag(contact_id, tag), action == "remove_tag")
                state = self.enrolment_data(e["id"])
                self.assertEqual(state["status"], "held")
                self.assert_claim_cleared(state)

    def test_plural_tags_emit_only_changed_tags_with_shared_correlation_and_depth(self):
        from unittest.mock import patch
        for action, event in (("add_tag", "tag_added"), ("remove_tag", "tag_removed")):
            email, contact_id = self.create_contact()
            self.add_existing_tag(contact_id, "already")
            if action == "remove_tag":
                self.add_existing_tag(contact_id, "second")
            a = self.create_automation(nodes=[{"id":"tags","type":action,"label":"Tags","draft_tags":["already","second","third"]}])
            self.addCleanup(self.cleanup, a["id"])
            e = self.enrol(a["id"], email)
            self.patch_enrolment_data(e["id"], {"trigger_correlation_id":"tag-batch-test", "trigger_depth":2})
            with patch.dict(os.environ, {"automation_trigger_emission_enabled":"true"}), patch.object(automations.contacts, "matching_tag_trigger_automation_exists", return_value=True):
                self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 200)
            rows = self.db.execute("select data from automation_trigger_events where cid = %s and contact_id = %s and event_type = %s", self.user_cookie["cid"], contact_id, event).fetchall()
            self.addCleanup(self.db.execute, "delete from automation_trigger_events where cid = %s and contact_id = %s", self.user_cookie["cid"], contact_id)
            self.assertEqual(sorted(row[0]["tag"] for row in rows), ["second","third"] if action == "add_tag" else ["already","second"])
            self.assertTrue(all(row[0]["correlation_id"] == "tag-batch-test" and row[0]["depth"] == 3 for row in rows))

    def test_concurrent_plural_tag_actions_do_not_duplicate_change_events(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        email, contact_id = self.create_contact()
        nodes = [{"id":"tags", "type":"add_tag", "label":"Tags", "draft_tags":["batch-a", "batch-b"]}]
        first = self.create_automation(nodes=nodes)
        second = self.create_automation(nodes=nodes)
        self.addCleanup(self.cleanup, first["id"], second["id"])
        one, two = self.enrol(first["id"], email), self.enrol(second["id"], email)
        db1, db2 = self.publish_safety_db(), self.publish_safety_db()
        entered, release, second_started = Event(), Event(), Event()
        original = automations.contacts.add_tag
        original_execute = db2.execute
        def observed_execute(sql, *args, **kwargs):
            if sql.startswith('select contact_id from contacts.') and 'for update' in sql:
                db2.tag_batch_pid = db2.single("select pg_backend_pid()")
                second_started.set()
            return original_execute(sql, *args, **kwargs)
        db2.execute = observed_execute
        def blocked(db, *args, **kwargs):
            if db is db1:
                db1.tag_batch_pid = db.single("select pg_backend_pid()")
                entered.set()
                if not release.wait(5): raise AssertionError("Tag batch was not released")
            return original(db, *args, **kwargs)
        def run_second():
            return automations._run_next_automation_enrolment(db2, self.user_cookie["cid"], second["id"], two["id"])
        with patch.dict(os.environ, {"automation_trigger_emission_enabled":"true"}), patch.object(automations.contacts, "matching_tag_trigger_automation_exists", return_value=True), patch.object(automations.contacts, "add_tag", side_effect=blocked), ThreadPoolExecutor(2) as pool:
            f1 = pool.submit(automations._run_next_automation_enrolment, db1, self.user_cookie["cid"], first["id"], one["id"])
            try:
                self.assertTrue(entered.wait(4))
                f2 = pool.submit(run_second)
                self.assertTrue(second_started.wait(4))
                import time
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    blockers = self.db.single("select pg_blocking_pids(%s)", db2.tag_batch_pid)
                    if db1.tag_batch_pid in blockers: break
                    time.sleep(0.01)
                self.assertIn(db1.tag_batch_pid, blockers, "The second batch must wait for the first contact lock")
            finally:
                release.set()
            f1.result(timeout=5)
            f2.result(timeout=5)
        rows = self.db.execute("select data from automation_trigger_events where cid = %s and contact_id = %s", self.user_cookie["cid"], contact_id).fetchall()
        self.addCleanup(self.db.execute, "delete from automation_trigger_events where cid = %s and contact_id = %s", self.user_cookie["cid"], contact_id)
        self.assertEqual(sorted(row[0]["tag"] for row in rows), ["batch-a", "batch-b"])
        self.assert_claim_cleared(self.enrolment_data(one["id"]))
        self.assert_claim_cleared(self.enrolment_data(two["id"]))

    def test_plural_tag_trigger_failure_rolls_back_tags_and_events(self):
        from unittest.mock import patch
        for action in ("add_tag", "remove_tag"):
            email, contact_id = self.create_contact()
            if action == "remove_tag":
                for tag in ("first", "second"): self.add_existing_tag(contact_id, tag)
            a = self.create_automation(nodes=[{"id":"tags", "type":action, "label":"Tags", "draft_tags":["first", "second"]}])
            self.addCleanup(self.cleanup, a["id"])
            e = self.enrol(a["id"], email)
            helper_name = "maybe_insert_tag_added_trigger_event" if action == "add_tag" else "maybe_insert_tag_removed_trigger_event"
            helper = getattr(automations.contacts, helper_name)
            calls = []
            def failing(*args, **kwargs):
                calls.append(True)
                if len(calls) == 2: raise ValueError("Injected trigger failure")
                return helper(*args, **kwargs)
            with patch.dict(os.environ, {"automation_trigger_emission_enabled":"true"}), patch.object(automations.contacts, "matching_tag_trigger_automation_exists", return_value=True), patch.object(automations.contacts, helper_name, side_effect=failing):
                result = self.run_next(a["id"], e["id"])
            self.assertEqual(result.status_code, 400, result.text)
            self.assertEqual(len(calls), 2)
            for tag in ("first", "second"): self.assertEqual(self.has_tag(contact_id, tag), action == "remove_tag")
            self.assertEqual(self.db.execute("select count(*) from automation_trigger_events where cid = %s and contact_id = %s", self.user_cookie["cid"], contact_id).fetchone()[0], 0)
            self.assert_claim_cleared(self.enrolment_data(e["id"]))

    def test_wait_mode_changes_are_blocked_for_waiting_contacts_in_impact_and_publish(self):
        from copy import deepcopy
        for absolute in (False, True):
            for paused in (False, True):
                nodes = self.wait_nodes()
                if absolute:
                    nodes[0].pop("duration")
                    nodes[0]["wait_until"] = (datetime.utcnow()+timedelta(days=1)).isoformat()+"Z"
                a = self.create_automation(nodes=nodes)
                self.addCleanup(self.cleanup, a["id"])
                email, _ = self.create_contact()
                e = self.enrol(a["id"], email)
                self.run_next(a["id"], e["id"])
                path = "/api/automations/" + a["id"]
                if paused: self.user_post(path + "/pause")
                before = self.enrolment_data(e["id"])
                proposed = deepcopy(nodes)
                if absolute:
                    proposed[0].pop("wait_until")
                    proposed[0]["duration"] = {"days":1,"hours":0,"minutes":0}
                else:
                    proposed[0].pop("duration")
                    proposed[0]["wait_until"] = (datetime.utcnow()+timedelta(days=1)).isoformat()+"Z"
                self.user_patch(path, json={"draft":{"nodes":proposed}})
                saved = self.user_get(path)
                impact = self.user_get(path + "/publish-impact")
                self.assertIn("incompatible_retained_wait", [item["code"] for item in impact["blockers"]])
                self.assertEqual(self.simulate_post(path + "/publish", headers=self.headers()).status_code, 409)
                self.assertEqual(self.user_get(path), saved)
                self.assertEqual(self.enrolment_data(e["id"]), before)

    def test_date_wait_waits_until_exact_instant_and_resume_does_not_move_deadline(self):
        email, _ = self.create_contact()
        deadline = (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z"
        a = self.create_automation(nodes=[{"id": "wait", "type": "wait_duration", "label": "Date wait", "wait_until": deadline}, {"id": "end", "type": "exit", "label": "End"}])
        self.addCleanup(self.cleanup, a["id"])
        e = self.enrol(a["id"], email)
        first = self.run_next(a["id"], e["id"])
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json["enrolment"]["wake_at"], deadline)
        self.user_post("/api/automations/%s/pause" % a["id"])
        self.user_post("/api/automations/%s/resume" % a["id"])
        self.assertEqual(self.enrolment_data(e["id"])["wake_at"], deadline)
        self.assertIn("Wait has not elapsed", self.run_next(a["id"], e["id"]).text)
        self.user_post("/api/automations/%s/pause" % a["id"])
        from unittest.mock import patch
        with patch.object(automations, "datetime", wraps=datetime) as clock:
            clock.utcnow.return_value = datetime.utcnow() + timedelta(hours=3)
            self.user_post("/api/automations/%s/resume" % a["id"])
            self.assertEqual(self.enrolment_data(e["id"])["wake_at"], deadline)
            result = self.run_next(a["id"], e["id"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "end")

    def test_expired_date_wait_advances_without_resetting_loop_guard(self):
        email, _ = self.create_contact()
        a = self.create_automation(nodes=[{"id": "wait", "type": "wait_duration", "label": "Past date", "wait_until": "2020-01-01T12:00:00Z"}, {"id": "go", "type": "go_to", "label": "Repeat", "target_node_id": "wait"}])
        self.addCleanup(self.cleanup, a["id"])
        e = self.enrol(a["id"], email)
        result = self.run_next(a["id"], e["id"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["enrolment"]["current_node_id"], "go")
        self.assertEqual(result.json["enrolment"]["visited_node_ids"], ["wait"])
        self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 200)
        self.assertIn("loop detected", self.run_next(a["id"], e["id"]).text)

    def test_date_wait_elapsed_after_entry_clears_visits(self):
        email, _ = self.create_contact()
        a = self.create_automation(nodes=[{"id": "wait", "type": "wait_duration", "label": "Date", "wait_until": (datetime.utcnow()+timedelta(hours=1)).isoformat()+"Z"}, {"id": "end", "type": "exit", "label": "End"}])
        self.addCleanup(self.cleanup, a["id"])
        e = self.enrol(a["id"], email)
        state = self.run_next(a["id"], e["id"]).json["enrolment"]
        state["wait"]["started_at"] = (datetime.utcnow()-timedelta(minutes=2)).isoformat()+"Z"
        state["wake_at"] = (datetime.utcnow()-timedelta(minutes=1)).isoformat()+"Z"
        state["wait"]["wait_until"] = state["wake_at"]
        self.patch_enrolment_data(e["id"], state)
        result = self.run_next(a["id"], e["id"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["enrolment"]["visited_node_ids"], [])

    def test_transition_budget_holds_before_action(self):
        email, _ = self.create_contact()
        automation = self.create_automation()
        self.addCleanup(self.cleanup, automation["id"])
        enrolment = self.enrol(automation["id"], email)
        self.db.execute("update automation_enrolments set data = data || %s where id = %s", {"transitions_without_wait": 1000}, enrolment["id"])
        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("safety limit", result.text)
        self.assertEqual(self.enrolment_data(enrolment["id"])["status"], "held")
        self.assertEqual(self.step_runs(automation["id"], enrolment["id"]), [])

    def test_skipping_a_loop_wait_does_not_reset_transition_budget(self):
        email, _ = self.create_contact()
        automation = self.create_automation(nodes=[
            {"id": "wait", "type": "wait_duration", "label": "Wait", "duration": {"days": 0, "hours": 0, "minutes": 5}},
            {"id": "go", "type": "go_to", "label": "Repeat", "target_node_id": "wait"},
        ])
        self.addCleanup(self.cleanup, automation["id"])
        enrolment = self.enrol(automation["id"], email)
        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 200)
        self.db.execute("update automation_enrolments set data = data || %s where id = %s", {"transitions_without_wait": 999}, enrolment["id"])
        skipped = self.run_next_skip_wait(automation["id"], enrolment["id"])
        self.assertEqual(skipped.status_code, 200, skipped.text)
        self.assertEqual(skipped.json["enrolment"]["transitions_without_wait"], 1000)
        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 400)
        state = self.enrolment_data(enrolment["id"])
        self.assertEqual(state["status"], "held")
        self.assertFalse(state.get("claim_token"))

    def test_go_to_target_missing_is_rejected_clearly(self):
        email, _ = self.create_contact()
        automation = self.create_go_to_automation()
        published = automation["published"].copy()
        published["nodes"] = [
            node for node in published["nodes"] if node["id"] != "node_exit_1"
        ]
        self.db.set_cid(self.user_cookie["cid"])
        self.db.automations.patch(automation["id"], {"published": published})
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("go_to target was not found", result.text)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "held")
        self.assertEqual(data["last_failure_retryable"], False)
        self.assertEqual(data["last_failure_class"], "configuration")

        self.cleanup(automation["id"])

    def test_tag_added_by_automation_is_detected_by_later_condition(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add detected tag",
                    "draft_tag": "detected-tag",
                },
                {
                    "id": "node_condition_1",
                    "type": "if_has_tag",
                    "label": "Check detected tag",
                    "draft_tag": "detected-tag",
                    "yes_node_id": "node_exit_1",
                    "no_node_id": "node_no_branch_1",
                },
                {
                    "id": "node_no_branch_1",
                    "type": "add_tag",
                    "label": "Add no branch tag",
                    "draft_tag": "no-branch",
                },
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        first = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(first.status_code, 200)
        self.assertTrue(self.has_tag(contact_id, "detected-tag"))
        self.assertEqual(first.json["enrolment"]["current_node_id"], "node_condition_1")

        second = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(second.json["step_run"]["node_type"], "if_has_tag")
        self.assertEqual(second.json["step_run"]["result"], True)
        self.assertEqual(second.json["step_run"]["branch"], "yes")
        self.assertEqual(second.json["step_run"]["target_node_id"], "node_exit_1")
        self.assertFalse(self.has_tag(contact_id, "no-branch"))

        self.cleanup(automation["id"])

    def wait_nodes(self, final=False):
        nodes = [
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
        ]
        if not final:
            nodes.append(
                {
                    "id": "node_exit_1",
                    "type": "exit",
                    "label": "Exit automation",
                }
            )
        return nodes

    def create_wait_automation(self, final=False):
        automation = self.create_automation()
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(nodes=self.wait_nodes(final)),
        )
        return self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json

    def test_ready_enrolment_on_wait_duration_becomes_waiting(self):
        email, _ = self.create_contact()
        automation = self.create_wait_automation()
        enrolment = self.enrol(automation["id"], email)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        updated = result.json["enrolment"]
        step_run = result.json["step_run"]

        self.assertEqual(updated["status"], "waiting")
        self.assertEqual(updated["current_node_id"], "node_wait_1")
        self.assertIn("wake_at", updated)
        self.assertEqual(updated["wait"]["node_id"], "node_wait_1")
        self.assertEqual(updated["wait"]["duration"], {"days": 0, "hours": 0, "minutes": 5})
        self.assert_claim_cleared(updated)
        self.assertEqual(step_run["node_id"], "node_wait_1")
        self.assertEqual(step_run["node_type"], "wait_duration")
        self.assertEqual(step_run["status"], "waiting")
        self.assertEqual(step_run["action"], "wait_start")
        self.assertEqual(step_run["duration"], {"days": 0, "hours": 0, "minutes": 5})

        created = dateutil.parser.parse(step_run["created"])
        wake_at = dateutil.parser.parse(updated["wake_at"])
        self.assertEqual(int((wake_at - created).total_seconds()), 5 * 60)

        self.cleanup(automation["id"])

    def test_run_next_before_wake_at_is_rejected_clearly(self):
        email, _ = self.create_contact()
        automation = self.create_wait_automation()
        enrolment = self.enrol(automation["id"], email)

        started = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(started.status_code, 200)

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 400)
        self.assertIn("Wait has not elapsed", result.text)
        self.assertIn(started.json["enrolment"]["wake_at"], result.text)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "waiting")
        self.assert_claim_cleared(data)

        self.cleanup(automation["id"])

    def test_skip_wait_before_wake_at_advances_for_debugging(self):
        email, _ = self.create_contact()
        automation = self.create_wait_automation()
        enrolment = self.enrol(automation["id"], email)

        started = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(started.status_code, 200)

        result = self.run_next_skip_wait(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["enrolment"]["wake_at"], None)
        self.assertEqual(result.json["step_run"]["action"], "wait_complete")
        self.assertEqual(result.json["step_run"]["wake_at"], started.json["enrolment"]["wake_at"])
        self.assertEqual(result.json["step_run"]["skipped"], True)

        self.cleanup(automation["id"])

    def test_run_next_after_wake_at_records_wait_complete_and_advances(self):
        email, _ = self.create_contact()
        automation = self.create_wait_automation()
        enrolment = self.enrol(automation["id"], email)
        started = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(started.status_code, 200)

        past = (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where id = %s
            """,
            {
                "wake_at": past,
                "wait": {
                    "node_id": "node_wait_1",
                    "duration": {"days": 0, "hours": 0, "minutes": 5},
                    "started_at": started.json["enrolment"]["wait"]["started_at"],
                    "wake_at": past,
                    "published_revision": automation["published_revision"],
                },
            },
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "ready")
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")
        self.assertEqual(result.json["enrolment"]["wake_at"], None)
        self.assert_claim_cleared(result.json["enrolment"])
        self.assertEqual(result.json["step_run"]["node_type"], "wait_duration")
        self.assertEqual(result.json["step_run"]["status"], "succeeded")
        self.assertEqual(result.json["step_run"]["action"], "wait_complete")

        runs = self.step_runs(automation["id"], enrolment["id"])
        self.assertEqual([run[7]["action"] for run in runs], ["wait_start", "wait_complete"])

        self.cleanup(automation["id"])

    def test_wait_as_final_node_completes_after_elapsed(self):
        email, _ = self.create_contact()
        automation = self.create_wait_automation()
        automation["published"]["nodes"] = self.wait_nodes(final=True)
        self.db.automations.patch(
            automation["id"],
            {
                "published": automation["published"],
            },
        )
        enrolment = self.enrol(automation["id"], email)
        started = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(started.status_code, 200)

        past = (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"
        self.db.execute(
            """
            update automation_enrolments
            set data = data || %s
            where id = %s
            """,
            {
                "wake_at": past,
                "wait": {
                    "node_id": "node_wait_1",
                    "duration": {"days": 0, "hours": 0, "minutes": 5},
                    "started_at": started.json["enrolment"]["wait"]["started_at"],
                    "wake_at": past,
                    "published_revision": automation["published_revision"],
                },
            },
            enrolment["id"],
        )

        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["enrolment"]["status"], "completed")
        self.assertEqual(result.json["step_run"]["action"], "wait_complete")

        again = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(again.status_code, 400)

        self.cleanup(automation["id"])

    def test_once_does_not_allow_running_again_after_exit(self):
        email, _ = self.create_contact()
        automation = self.create_automation(reentry="once")
        enrolment = self.enrol(automation["id"], email)

        self.assertEqual(self.run_next(automation["id"], enrolment["id"]).status_code, 200)
        exited = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(exited.status_code, 200)
        self.assertEqual(exited.json["enrolment"]["status"], "exited")

        again = self.enrol_response(automation["id"], email)
        self.assertEqual(again.status_code, 400)

        self.cleanup(automation["id"])

    def test_multiple_allows_running_again_after_exit_and_preserves_history(self):
        email, _ = self.create_contact()
        automation = self.create_automation(tag="repeat-tag", reentry="multiple")
        first_enrolment = self.enrol(automation["id"], email)

        self.assertEqual(self.run_next(automation["id"], first_enrolment["id"]).status_code, 200)
        exited = self.run_next(automation["id"], first_enrolment["id"])
        self.assertEqual(exited.status_code, 200)
        self.assertEqual(exited.json["enrolment"]["status"], "exited")
        first_runs = self.step_runs(automation["id"], first_enrolment["id"])
        self.assertEqual(len(first_runs), 2)

        second_enrolment = self.enrol(automation["id"], email)
        self.assertNotEqual(first_enrolment["id"], second_enrolment["id"])
        self.assertEqual(second_enrolment["status"], "ready")
        self.assertEqual(second_enrolment["current_node_id"], "node_add_tag_1")

        self.assertEqual(len(self.step_runs(automation["id"], first_enrolment["id"])), 2)
        self.assertEqual(self.step_runs(automation["id"], second_enrolment["id"]), [])

        self.cleanup(automation["id"])

    def test_manual_processor_rejects_when_customer_processing_disabled(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="processor-disabled")
        self.enrol(automation["id"], email)
        self.set_customer_automation_processing(False)

        result = self.simulate_post(
            "/api/automation-enrolments/process",
            json={"automation_id": automation["id"]},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("Automation processing is disabled", result.text)
        self.assertFalse(self.has_tag(contact_id, "processor-disabled"))

        self.cleanup(automation["id"])

    def test_manual_processor_works_when_customer_processing_enabled(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="processor-enabled")
        self.enrol(automation["id"], email)
        self.set_customer_automation_processing(True)

        result = self.simulate_post(
            "/api/automation-enrolments/process",
            json={"automation_id": automation["id"]},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 1)
        self.assertTrue(self.has_tag(contact_id, "processor-enabled"))

        self.cleanup(automation["id"])

    def test_run_next_remains_allowed_when_customer_processing_disabled(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="run-next-processing-disabled")
        enrolment = self.enrol(automation["id"], email)
        self.set_customer_automation_processing(False)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(self.has_tag(contact_id, "run-next-processing-disabled"))

        self.cleanup(automation["id"])

    def test_processor_processes_ready_enrolment_one_node_only(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add first tag",
                    "draft_tag": "processor-first",
                },
                {
                    "id": "node_add_tag_2",
                    "type": "add_tag",
                    "label": "Add second tag",
                    "draft_tag": "processor-second",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 1)
        self.assertEqual(result.json["succeeded"], 1)
        self.assertTrue(self.has_tag(contact_id, "processor-first"))
        self.assertFalse(self.has_tag(contact_id, "processor-second"))
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["current_node_id"], "node_add_tag_2")
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 1)

        self.cleanup(automation["id"])

    def test_processor_processes_elapsed_waiting_enrolment(self):
        email, _ = self.create_contact()
        automation = self.create_wait_automation()
        enrolment = self.enrol(automation["id"], email)
        started = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(started.status_code, 200)
        past = (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"
        self.patch_enrolment_data(
            enrolment["id"],
            {
                "wake_at": past,
                "wait": {
                    "node_id": "node_wait_1",
                    "duration": {"days": 0, "hours": 0, "minutes": 5},
                    "started_at": started.json["enrolment"]["wait"]["started_at"],
                    "wake_at": past,
                    "published_revision": automation["published_revision"],
                },
            },
        )

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 1)
        self.assertEqual(result.json["succeeded"], 1)
        self.assertEqual(result.json["waiting"], 0)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["current_node_id"], "node_exit_1")
        self.assert_claim_cleared(data)

        self.cleanup(automation["id"])

    def test_processor_does_not_select_non_elapsed_waiting_enrolment(self):
        email, _ = self.create_contact()
        automation = self.create_wait_automation()
        enrolment = self.enrol(automation["id"], email)
        started = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(started.status_code, 200)

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 0)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "waiting")
        self.assertEqual(data["wake_at"], started.json["enrolment"]["wake_at"])

        self.cleanup(automation["id"])

    def test_processor_skips_future_retry_after(self):
        email, _ = self.create_contact()
        route_id = self.create_drop_all_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.patch_enrolment_data(
            enrolment["id"],
            {
                "retry_count": 1,
                "retry_after": (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z",
            },
        )

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 0)
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 0)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["retry_count"], 1)

        self.cleanup(automation["id"])

    def test_processor_retries_after_elapsed_retry_after(self):
        email, _ = self.create_contact()
        route_id = self.create_drop_all_route()
        self.assign_company_routes([route_id])
        automation = self.create_send_email_automation()
        enrolment = self.enrol(automation["id"], email)
        self.patch_enrolment_data(
            enrolment["id"],
            {
                "retry_count": 1,
                "retry_after": (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z",
            },
        )

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 1)
        self.assertEqual(result.json["failed"], 1)
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["retry_count"], 2)
        self.assertIsNotNone(data["retry_after"])
        self.assertEqual(len(self.step_runs(automation["id"], enrolment["id"])), 1)

        self.cleanup(automation["id"])

    def test_processor_treats_invalid_retry_after_as_elapsed(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="processor-invalid-retry-after")
        enrolment = self.enrol(automation["id"], email)
        self.patch_enrolment_data(
            enrolment["id"],
            {
                "retry_count": "not-a-number",
                "retry_after": "not-a-date",
            },
        )

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 1)
        self.assertEqual(result.json["succeeded"], 1)
        self.assertTrue(self.has_tag(contact_id, "processor-invalid-retry-after"))
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertIsNone(data.get("retry_after"))
        self.assertIsNone(data.get("retry_count"))

        self.cleanup(automation["id"])

    def test_processor_excludes_ineligible_statuses_and_paused_automations(self):
        statuses = ["held", "paused_ready", "paused_waiting", "completed", "exited", "cancelled", "failed"]
        automation = self.create_automation(tag="processor-ineligible")
        for status in statuses:
            email, _ = self.create_contact()
            enrolment = self.enrol(automation["id"], email)
            self.patch_enrolment_data(
                enrolment["id"],
                {
                    "status": status,
                    "retry_after": "not-a-date",
                },
            )

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 0)

        paused_email, _ = self.create_contact()
        paused_automation = self.create_automation(tag="processor-paused-automation")
        self.enrol(paused_automation["id"], paused_email)
        paused = self.simulate_post(
            "/api/automations/%s/pause" % paused_automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(paused.status_code, 200, paused.text)

        paused_result = self.process_enrolments(automation_id=paused_automation["id"])

        self.assertEqual(paused_result.status_code, 200, paused_result.text)
        self.assertEqual(paused_result.json["processed"], 0)

        self.cleanup(automation["id"], paused_automation["id"])

    def test_processor_counts_running_enrolments_without_claiming_them(self):
        email, _ = self.create_contact()
        automation = self.create_automation(tag="processor-running")
        enrolment = self.enrol(automation["id"], email)
        self.patch_enrolment_data(
            enrolment["id"],
            {
                "status": "running",
                "running_status": "ready",
                "claim_token": "test-claim",
                "claimed_at": datetime.utcnow().isoformat() + "Z",
                "claimed_node_id": "node_add_tag_1",
                "claimed_published_revision": automation["published_revision"],
            },
        )

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 0)
        self.assertEqual(result.json["skipped_running"], 1)
        self.assertEqual(self.enrolment_data(enrolment["id"])["status"], "running")

        self.cleanup(automation["id"])

    def test_processor_continues_after_one_enrolment_fails(self):
        bad_email, _ = self.create_contact()
        good_email, good_contact_id = self.create_contact()
        automation = self.create_automation(tag="processor-good")
        bad_enrolment = self.enrol(automation["id"], bad_email)
        self.enrol(automation["id"], good_email)
        self.patch_enrolment_data(bad_enrolment["id"], {"current_node_id": "missing-node"})

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 2)
        self.assertEqual(result.json["succeeded"], 1)
        self.assertEqual(result.json["failed"], 1)
        self.assertTrue(result.json["errors"])
        self.assertTrue(self.has_tag(good_contact_id, "processor-good"))

        self.cleanup(automation["id"])

    def test_processor_enforces_batch_limit(self):
        automation = self.create_automation(tag="processor-limit")
        for i in range(2):
            email, _ = self.create_contact()
            self.enrol(automation["id"], email)

        result = self.process_enrolments(automation_id=automation["id"], limit=1)

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 1)

        self.cleanup(automation["id"])

    def test_processor_automation_id_filter_only_processes_selected_automation(self):
        selected_email, selected_contact_id = self.create_contact()
        other_email, other_contact_id = self.create_contact()
        selected = self.create_automation(tag="processor-selected")
        other = self.create_automation(tag="processor-other")
        self.enrol(selected["id"], selected_email)
        self.enrol(other["id"], other_email)

        result = self.process_enrolments(automation_id=selected["id"], limit=10)

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 1)
        self.assertTrue(self.has_tag(selected_contact_id, "processor-selected"))
        self.assertFalse(self.has_tag(other_contact_id, "processor-other"))

        self.cleanup(selected["id"], other["id"])

    def test_processor_is_current_account_scoped(self):
        email, _ = self.create_contact()
        automation = self.create_automation(tag="processor-scope")
        enrolment = self.enrol(automation["id"], email)
        self.db.execute(
            "update automation_enrolments set cid = %s where id = %s",
            "other-account-cid",
            enrolment["id"],
        )

        result = self.process_enrolments(automation_id=automation["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["processed"], 0)
        self.db.execute(
            "delete from automation_enrolments where id = %s and cid = %s",
            enrolment["id"],
            "other-account-cid",
        )
        self.cleanup(automation["id"])

    def test_processing_status_is_current_account_scoped(self):
        email, _ = self.create_contact()
        automation = self.create_automation(tag="status-scope")
        self.enrol(automation["id"], email)
        other_cid = "automation-status-other-%s" % self.unique()
        other_automation_id = "automation-status-other-automation-%s" % self.unique()
        other_enrolment_id = "automation-status-other-enrolment-%s" % self.unique()
        self.created_scheduler_cids.append(other_cid)
        self.db.execute(
            "insert into companies (id, cid, data) values (%s, %s, %s)",
            other_cid,
            self.backend_cid(),
            {"name": "Status other account", "admin": False},
        )
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            other_automation_id,
            other_cid,
            {
                "name": "Status other automation",
                "status": "published",
                "published_revision": 1,
                "published": {"nodes": []},
            },
        )
        self.db.execute(
            """
            insert into automation_enrolments
                (id, cid, automation_id, contact_id, contact_email, data)
            values (%s, %s, %s, %s, %s, %s)
            """,
            other_enrolment_id,
            other_cid,
            other_automation_id,
            1,
            "other-status@example.com",
            {"status": "ready", "created": datetime.utcnow().isoformat() + "Z"},
        )

        result = self.processing_status()

        self.assertEqual(result.status_code, 200, result.text)
        self.assertGreaterEqual(result.json["summary"]["ready"], 1)
        automation_ids = [item["automation_id"] for item in result.json["automations"]]
        self.assertIn(automation["id"], automation_ids)
        self.assertNotIn(other_automation_id, automation_ids)
        breakdown = [
            item for item in result.json["automations"]
            if item["automation_id"] == automation["id"]
        ][0]
        self.assertEqual(breakdown["counts"]["ready"], 1)

        self.cleanup(automation["id"])

    def test_processing_status_hidden_from_customer_by_default(self):
        self.clear_customer_automation_diagnostics()

        result = self.simulate_get(
            "/api/automation-processing-status",
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)
        self.assertIn("Automation diagnostics are not enabled", result.text)

    def test_processing_status_visible_when_customer_flag_enabled(self):
        self.set_customer_automation_diagnostics(True)

        result = self.simulate_get(
            "/api/automation-processing-status",
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 200, result.text)

    def test_processing_status_visible_to_admin_impersonation_when_customer_flag_false(self):
        self.set_customer_automation_diagnostics(False)

        result = self.simulate_get(
            "/api/automation-processing-status",
            headers=self.admin_impersonation_headers(),
        )

        self.assertEqual(result.status_code, 200, result.text)

    def test_run_next_remains_allowed_when_diagnostics_hidden(self):
        email, _ = self.create_contact()
        automation = self.create_automation(tag="diagnostics-hidden-run-next")
        enrolment = self.enrol(automation["id"], email)
        self.set_customer_automation_diagnostics(False)

        result = self.run_next(automation["id"], enrolment["id"])

        self.assertEqual(result.status_code, 200, result.text)
        self.cleanup(automation["id"])

    def test_processing_status_returns_summary_and_per_automation_counts(self):
        automation = self.create_automation(tag="status-counts")
        statuses = [
            "ready",
            "waiting",
            "held",
            "paused_ready",
            "paused_waiting",
            "running",
            "failed",
            "completed",
            "exited",
            "cancelled",
        ]
        for status in statuses:
            email, _ = self.create_contact()
            enrolment = self.enrol(automation["id"], email)
            self.patch_enrolment_data(enrolment["id"], {"status": status})

        result = self.processing_status()

        self.assertEqual(result.status_code, 200, result.text)
        for status in statuses:
            self.assertGreaterEqual(result.json["summary"][status], 1)
        self.assertGreaterEqual(result.json["summary"]["total"], len(statuses))
        breakdown = [
            item for item in result.json["automations"]
            if item["automation_id"] == automation["id"]
        ][0]
        for status in statuses:
            self.assertEqual(breakdown["counts"][status], 1)
        self.assertEqual(breakdown["counts"]["total"], len(statuses))
        self.assertEqual(breakdown["counts"]["stale_running"], 0)

        self.cleanup(automation["id"])

    def test_processing_status_detects_stale_running_claims(self):
        email, _ = self.create_contact()
        fresh_email, _ = self.create_contact()
        automation = self.create_automation(tag="status-stale")
        stale_enrolment = self.enrol(automation["id"], email)
        fresh_enrolment = self.enrol(automation["id"], fresh_email)
        stale = (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z"
        fresh = datetime.utcnow().isoformat() + "Z"
        self.patch_enrolment_data(
            stale_enrolment["id"],
            {
                "status": "running",
                "running_status": "ready",
                "claim_token": "stale-status-claim",
                "claimed_at": stale,
                "claimed_node_id": "node_add_tag_1",
                "claimed_published_revision": automation["published_revision"],
            },
        )
        self.patch_enrolment_data(
            fresh_enrolment["id"],
            {
                "status": "running",
                "running_status": "ready",
                "claim_token": "fresh-status-claim",
                "claimed_at": fresh,
                "claimed_node_id": "node_add_tag_1",
                "claimed_published_revision": automation["published_revision"],
            },
        )

        result = self.processing_status()

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["summary"]["running"], 2)
        self.assertEqual(result.json["summary"]["stale_running"], 1)
        self.assertEqual(len(result.json["stale_running"]), 1)
        self.assertEqual(result.json["stale_running"][0]["enrolment_id"], stale_enrolment["id"])
        self.assertEqual(result.json["stale_running"][0]["claimed_node_id"], "node_add_tag_1")

        self.cleanup(automation["id"])

    def test_processing_status_recent_failures_are_capped_and_scoped(self):
        automation = self.create_automation(tag="status-failed")
        for i in range(26):
            email, _ = self.create_contact()
            enrolment = self.enrol(automation["id"], email)
            self.patch_enrolment_data(
                enrolment["id"],
                {
                    "status": "failed",
                    "last_error": {
                        "title": "Failure %s" % i,
                        "description": "Status failure %s" % i,
                        "at": (datetime.utcnow() + timedelta(seconds=i)).isoformat() + "Z",
                    },
                },
            )
        other_cid = "automation-status-failure-other-%s" % self.unique()
        other_automation_id = "automation-status-failure-other-automation-%s" % self.unique()
        self.created_scheduler_cids.append(other_cid)
        self.db.execute(
            "insert into companies (id, cid, data) values (%s, %s, %s)",
            other_cid,
            self.backend_cid(),
            {"name": "Status failure other account", "admin": False},
        )
        self.db.execute(
            "insert into automations (id, cid, data) values (%s, %s, %s)",
            other_automation_id,
            other_cid,
            {"name": "Status failure other automation", "status": "published"},
        )
        self.db.execute(
            """
            insert into automation_enrolments
                (id, cid, automation_id, contact_id, contact_email, data)
            values (%s, %s, %s, %s, %s, %s)
            """,
            "automation-status-failure-other-enrolment-%s" % self.unique(),
            other_cid,
            other_automation_id,
            1,
            "other-failure@example.com",
            {"status": "failed", "last_error": {"description": "hidden"}},
        )

        result = self.processing_status()

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json["recent_failures"]), 25)
        self.assertTrue(all(item["automation_id"] == automation["id"] for item in result.json["recent_failures"]))
        self.assertEqual(result.json["recent_failures"][0]["error"], "Status failure 25")

        self.cleanup(automation["id"])

    def test_processing_status_flags_are_booleans_only(self):
        os.environ["automation_processing_enabled"] = "true"
        os.environ["automation_triggers_enabled"] = "yes"
        os.environ["automation_trigger_emission_enabled"] = "on"
        os.environ["automation_trigger_manual_events_enabled"] = "1"

        result = self.processing_status()

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            result.json["flags"],
            {
                "automation_processing_enabled": True,
                "automation_triggers_enabled": True,
                "automation_trigger_emission_enabled": True,
                "automation_trigger_manual_events_enabled_debug": True,
            },
        )
        self.assertTrue(all(isinstance(value, bool) for value in result.json["flags"].values()))

    def test_processor_send_email_uses_debug_path_and_does_not_auto_loop(self):
        route_id = self.assign_single_debug_route()
        email, contact_id = self.create_contact()
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_processor_send_%s" % suffix},
        )
        automation_email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Processor email",
                "subject": "Processor subject %s" % suffix,
                "rawText": "<p>Processor body %s</p>" % suffix,
                "fromname": "Automation Sender",
                "returnpath": "automation-sender@example.com",
            },
        )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(
                nodes=[
                    {
                        "id": "node_send_email_1",
                        "type": "send_email",
                        "label": "Send email",
                        "automation_email_id": automation_email["id"],
                    },
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": "Add after send",
                        "draft_tag": "processor-send-finished",
                    },
                ],
            ),
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json
        enrolment = self.enrol(published["id"], email)

        first = self.process_enrolments(automation_id=published["id"])

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json["processed"], 1)
        self.assertEqual(first.json["succeeded"], 1)
        self.assertFalse(self.has_tag(contact_id, "processor-send-finished"))
        first_data = self.enrolment_data(enrolment["id"])
        self.assertEqual(first_data["status"], "ready")
        self.assertEqual(first_data["current_node_id"], "node_add_tag_1")
        logs = self.debug_email_logs(published["id"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0][2]["recipient_email"], email)
        self.assertEqual(logs[0][2]["route_id"], route_id)
        self.assertEqual(logs[0][2]["source_ids"]["automation_id"], published["id"])

        second = self.process_enrolments(automation_id=published["id"])

        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json["processed"], 1)
        self.assertTrue(self.has_tag(contact_id, "processor-send-finished"))
        self.assertEqual(len(self.debug_email_logs(published["id"])), 1)
        self.assertEqual(self.enrolment_data(enrolment["id"])["status"], "completed")

        self.cleanup(published["id"])

    def test_processor_task_processes_ready_enrolment(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="processor-task-ready")
        self.enrol(automation["id"], email)

        result = self.process_enrolments_task(automation["id"], 25)

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["succeeded"], 1)
        self.assertTrue(self.has_tag(contact_id, "processor-task-ready"))

        self.cleanup(automation["id"])

    def test_processor_task_respects_automation_id(self):
        selected_email, selected_contact_id = self.create_contact()
        other_email, other_contact_id = self.create_contact()
        selected = self.create_automation(tag="processor-task-selected")
        other = self.create_automation(tag="processor-task-other")
        self.enrol(selected["id"], selected_email)
        self.enrol(other["id"], other_email)

        result = self.process_enrolments_task(selected["id"], 25)

        self.assertEqual(result["processed"], 1)
        self.assertTrue(self.has_tag(selected_contact_id, "processor-task-selected"))
        self.assertFalse(self.has_tag(other_contact_id, "processor-task-other"))

        self.cleanup(selected["id"], other["id"])

    def test_processor_task_respects_limit_and_runs_one_node_only(self):
        first_email, first_contact_id = self.create_contact()
        second_email, second_contact_id = self.create_contact()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add first task tag",
                    "draft_tag": "processor-task-first-node",
                },
                {
                    "id": "node_add_tag_2",
                    "type": "add_tag",
                    "label": "Add second task tag",
                    "draft_tag": "processor-task-second-node",
                },
            ]
        )
        first_enrolment = self.enrol(automation["id"], first_email)
        self.enrol(automation["id"], second_email)

        result = self.process_enrolments_task(automation["id"], 1)

        self.assertEqual(result["processed"], 1)
        self.assertTrue(self.has_tag(first_contact_id, "processor-task-first-node"))
        self.assertFalse(self.has_tag(first_contact_id, "processor-task-second-node"))
        self.assertFalse(self.has_tag(second_contact_id, "processor-task-first-node"))
        data = self.enrolment_data(first_enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["current_node_id"], "node_add_tag_2")

        self.cleanup(automation["id"])

    def test_processor_task_excludes_paused_automation(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(tag="processor-task-paused")
        self.enrol(automation["id"], email)
        paused = self.simulate_post(
            "/api/automations/%s/pause" % automation["id"],
            headers=self.headers(),
        )
        self.assertEqual(paused.status_code, 200, paused.text)

        result = self.process_enrolments_task(automation["id"], 25)

        self.assertEqual(result["processed"], 0)
        self.assertFalse(self.has_tag(contact_id, "processor-task-paused"))

        self.cleanup(automation["id"])

    def test_processor_task_uses_existing_send_debug_path(self):
        route_id = self.assign_single_debug_route()
        email, contact_id = self.create_contact()
        suffix = self.unique()
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_execution_processor_task_send_%s" % suffix},
        )
        automation_email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={
                "name": "Processor task email",
                "subject": "Processor task subject %s" % suffix,
                "rawText": "<p>Processor task body %s</p>" % suffix,
                "fromname": "Automation Sender",
                "returnpath": "automation-sender@example.com",
            },
        )
        self.user_patch(
            "/api/automations/%s" % automation["id"],
            json=self.workflow(
                nodes=[
                    {
                        "id": "node_send_email_1",
                        "type": "send_email",
                        "label": "Send email",
                        "automation_email_id": automation_email["id"],
                    },
                    {
                        "id": "node_add_tag_1",
                        "type": "add_tag",
                        "label": "Add after task send",
                        "draft_tag": "processor-task-send-finished",
                    },
                ],
            ),
        )
        published = self.simulate_post(
            "/api/automations/%s/publish" % automation["id"],
            headers=self.headers(),
        ).json
        enrolment = self.enrol(published["id"], email)

        result = self.process_enrolments_task(published["id"], 25)

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["succeeded"], 1)
        self.assertFalse(self.has_tag(contact_id, "processor-task-send-finished"))
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["current_node_id"], "node_add_tag_1")
        logs = self.debug_email_logs(published["id"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0][2]["recipient_email"], email)
        self.assertEqual(logs[0][2]["route_id"], route_id)
        self.assertEqual(logs[0][2]["source_ids"]["automation_id"], published["id"])

        self.cleanup(published["id"])

    def test_processor_task_result_shape_matches_manual_processor(self):
        manual_email, _ = self.create_contact()
        task_email, _ = self.create_contact()
        manual = self.create_automation(tag="processor-manual-shape")
        task = self.create_automation(tag="processor-task-shape")
        self.enrol(manual["id"], manual_email)
        self.enrol(task["id"], task_email)

        manual_result = self.process_enrolments(automation_id=manual["id"]).json
        task_result = self.process_enrolments_task(task["id"], 25)

        self.assertEqual(set(task_result.keys()), set(manual_result.keys()))
        for key in ("processed", "succeeded", "waiting", "completed", "exited", "failed", "skipped_running"):
            self.assertIn(key, task_result)
        self.assertIn("errors", task_result)

        self.cleanup(manual["id"], task["id"])

    def test_admin_can_update_customer_automation_processing_settings(self):
        cid = self.user_cookie["cid"]

        result = self.simulate_patch(
            "/api/companies/%s" % cid,
            json={
                "automation_processing_enabled": True,
                "automation_diagnostics_visible": True,
            },
            headers=self.admin_headers(),
        )

        self.assertEqual(result.status_code, 200, result.text)
        company = self.db.companies.get(cid)
        self.assertEqual(company.get("automation_processing_enabled"), True)
        self.assertEqual(company.get("automation_diagnostics_visible"), True)

    def test_customer_cannot_update_automation_processing_settings(self):
        cid = self.user_cookie["cid"]

        result = self.simulate_patch(
            "/api/companies/%s" % cid,
            json={
                "automation_processing_enabled": True,
                "automation_diagnostics_visible": True,
            },
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 401)
        company = self.db.companies.get(cid)
        self.assertIsNone(company.get("automation_processing_enabled"))
        self.assertIsNone(company.get("automation_diagnostics_visible"))

    def test_company_automation_processing_settings_must_be_boolean(self):
        cid = self.user_cookie["cid"]

        result = self.simulate_patch(
            "/api/companies/%s" % cid,
            json={"automation_processing_enabled": "true"},
            headers=self.admin_headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("must be a boolean", result.text)

    def test_customer_automation_processing_default_is_false(self):
        cid = self.user_cookie["cid"]
        company = self.db.companies.get(cid)

        self.assertIsNone(company.get("automation_processing_enabled"))
        self.assertIsNone(company.get("automation_diagnostics_visible"))
        self.assertFalse(automations._customer_automation_processing_enabled(self.db, cid))

    def test_admin_can_read_company_automation_operations(self):
        cid = self.create_scheduler_candidate_account(
            status="ready",
            automation_processing_enabled=None,
        )

        result = self.simulate_get(
            "/api/companies/%s/automation-operations" % cid,
            headers=self.admin_headers(),
        )

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["company"]["id"], cid)
        self.assertFalse(result.json["company"]["automation_processing_enabled"])
        self.assertFalse(result.json["company"]["automation_diagnostics_visible"])
        self.assertEqual(result.json["summary"]["ready"], 1)
        self.assertEqual(result.json["summary"]["total"], 1)
        for value in result.json["flags"].values():
            self.assertIs(type(value), bool)

    def test_customer_cannot_read_company_automation_operations(self):
        cid = self.create_scheduler_candidate_account(status="ready")

        result = self.simulate_get(
            "/api/companies/%s/automation-operations" % cid,
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 401)

    def test_company_automation_operations_summary_is_scoped(self):
        cid = self.create_scheduler_candidate_account(status="ready")
        other_cid = self.create_scheduler_candidate_account(status="failed")

        result = self.simulate_get(
            "/api/companies/%s/automation-operations" % cid,
            headers=self.admin_headers(),
        )

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["summary"]["ready"], 1)
        self.assertEqual(result.json["summary"]["failed"], 0)
        self.assertEqual(result.json["summary"]["total"], 1)
        self.assertNotEqual(cid, other_cid)

    def recovery_post(self, cid, action, body=None, headers=None):
        return self.simulate_post(
            "/api/companies/%s/automation-recovery/%s" % (cid, action),
            json=body or {},
            headers=headers or self.admin_headers(),
        )

    def scheduler_enrolment_id(self, cid):
        return self.db.single("select id from automation_enrolments where cid = %s limit 1", cid)

    def scheduler_automation_id(self, cid):
        return self.db.single("select id from automations where cid = %s limit 1", cid)

    def set_scheduler_enrolment_data(self, cid, data):
        self.db.execute(
            "update automation_enrolments set data = data || %s where cid = %s",
            data,
            cid,
        )

    def test_customer_cannot_run_automation_recovery(self):
        cid = self.create_scheduler_candidate_account(status="ready")

        result = self.recovery_post(
            cid,
            "clear-stale-enrolment-claims",
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 401)

    def test_recovery_dry_run_for_each_action_mutates_nothing(self):
        cid = self.create_scheduler_candidate_account(status="ready")
        stale = (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z"
        self.set_scheduler_enrolment_data(cid, {
            "status": "running",
            "running_status": "ready",
            "claim_token": "stale-enrolment",
            "claimed_at": stale,
            "claimed_node_id": "node_add_tag_1",
        })
        self.db.execute(
            """
            insert into automation_trigger_events
                (id, cid, contact_id, contact_email, event_type, ts, data)
            values (%s, %s, 1, %s, 'tag_added', now(), %s)
            """,
            "trigger-dry-run-%s" % self.unique(),
            cid,
            "trigger-dry-run@example.com",
            {"status": "processing", "claimed_at": stale, "tag": "vip"},
        )
        self.db.execute(
            """
            insert into automation_segment_trigger_snapshots
                (id, cid, segment_id, status, hashlimit, last_hashval, claimed_at, claim_token, data)
            values (%s, %s, %s, 'baselining', 1, null, %s, 'stale-segment', %s)
            """,
            "snapshot-dry-run-%s" % self.unique(),
            cid,
            "segment-dry-run",
            stale,
            {"baseline_complete": False},
        )

        enrolment_result = self.recovery_post(cid, "clear-stale-enrolment-claims")
        trigger_result = self.recovery_post(cid, "clear-stale-trigger-event-claims")
        segment_result = self.recovery_post(cid, "clear-stale-segment-scanner-claims")

        for result in (enrolment_result, trigger_result, segment_result):
            self.assertEqual(result.status_code, 200, result.text)
            self.assertTrue(result.json["dry_run"])
            self.assertEqual(result.json["matched_count"], 1)
            self.assertEqual(result.json["changed_count"], 0)
        self.assertEqual(self.db.single("select data->>'status' from automation_enrolments where cid = %s", cid), "running")
        self.assertEqual(self.db.single("select data->>'status' from automation_trigger_events where cid = %s", cid), "processing")
        self.assertEqual(self.db.single("select status from automation_segment_trigger_snapshots where cid = %s", cid), "baselining")

    def test_recovery_apply_requires_confirmation(self):
        cid = self.create_scheduler_candidate_account(status="ready")

        result = self.recovery_post(
            cid,
            "clear-stale-enrolment-claims",
            {"dry_run": False},
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("confirmation is required", result.text)

    def test_recovery_apply_requires_exact_confirmation(self):
        cid = self.create_scheduler_candidate_account(status="ready")

        result = self.recovery_post(
            cid,
            "clear-stale-trigger-event-claims",
            {
                "dry_run": False,
                "confirm": "clear_stale_enrolment_claims",
            },
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("confirmation is required", result.text)

    def test_recovery_clears_only_eligible_stale_enrolment_claims(self):
        cid = self.create_scheduler_candidate_account(status="ready")
        other_cid = self.create_scheduler_candidate_account(status="ready")
        stale = (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z"
        fresh = datetime.utcnow().isoformat() + "Z"
        self.set_scheduler_enrolment_data(cid, {
            "status": "running",
            "running_status": "ready",
            "claim_token": "stale-enrolment",
            "claimed_at": stale,
            "claimed_node_id": "node_add_tag_1",
        })
        self.set_scheduler_enrolment_data(other_cid, {
            "status": "running",
            "running_status": "ready",
            "claim_token": "other-stale-enrolment",
            "claimed_at": stale,
        })
        blocked_cid = self.create_scheduler_candidate_account(status="ready")
        self.set_scheduler_enrolment_data(blocked_cid, {
            "status": "running",
            "running_status": "held",
            "claim_token": "held-stale-enrolment",
            "claimed_at": stale,
        })
        fresh_cid = self.create_scheduler_candidate_account(status="ready")
        self.set_scheduler_enrolment_data(fresh_cid, {
            "status": "running",
            "running_status": "ready",
            "claim_token": "fresh-enrolment",
            "claimed_at": fresh,
        })

        result = self.recovery_post(
            cid,
            "clear-stale-enrolment-claims",
            {
                "dry_run": False,
                "confirm": "clear_stale_enrolment_claims",
                "limit": 1,
            },
        )

        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json["dry_run"])
        self.assertEqual(result.json["matched_count"], 1)
        self.assertEqual(result.json["changed_count"], 1)
        self.assertEqual(len(result.json["items"]), 1)
        self.assertNotIn("data", result.json["items"][0])
        data = self.db.single("select data from automation_enrolments where cid = %s", cid)
        self.assertEqual(data["status"], "ready")
        self.assertIsNone(data.get("claim_token"))
        self.assertEqual(self.db.single("select data->>'claim_token' from automation_enrolments where cid = %s", other_cid), "other-stale-enrolment")
        self.assertEqual(self.db.single("select data->>'claim_token' from automation_enrolments where cid = %s", blocked_cid), "held-stale-enrolment")
        self.assertEqual(self.db.single("select data->>'claim_token' from automation_enrolments where cid = %s", fresh_cid), "fresh-enrolment")

    def test_recovery_clears_only_stale_trigger_event_claims(self):
        cid = self.create_scheduler_candidate_account(status="ready")
        other_cid = self.create_scheduler_candidate_account(status="ready")
        stale = (datetime.utcnow() - timedelta(minutes=31)).isoformat() + "Z"
        fresh = datetime.utcnow().isoformat() + "Z"
        for event_id, row_cid, claimed_at in (
            ("stale-trigger-%s" % self.unique(), cid, stale),
            ("fresh-trigger-%s" % self.unique(), cid, fresh),
            ("other-trigger-%s" % self.unique(), other_cid, stale),
        ):
            self.db.execute(
                """
                insert into automation_trigger_events
                    (id, cid, contact_id, contact_email, event_type, ts, data)
                values (%s, %s, 1, %s, 'tag_added', now(), %s)
                """,
                event_id,
                row_cid,
                "%s@example.com" % event_id,
                {"status": "processing", "claimed_at": claimed_at, "tag": "vip"},
            )

        result = self.recovery_post(
            cid,
            "clear-stale-trigger-event-claims",
            {
                "dry_run": False,
                "confirm": "clear_stale_trigger_event_claims",
                "limit": 1000,
            },
        )

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["limit"], 100)
        self.assertEqual(result.json["changed_count"], 1)
        self.assertEqual(self.db.single("select count(*) from automation_trigger_events where cid = %s and data->>'status' = 'pending'", cid), 1)
        self.assertEqual(self.db.single("select count(*) from automation_trigger_events where cid = %s and data->>'status' = 'processing'", cid), 1)
        self.assertEqual(self.db.single("select count(*) from automation_trigger_events where cid = %s and data->>'status' = 'processing'", other_cid), 1)
        self.assertNotIn("data", result.json["items"][0])

    def test_recovery_clears_only_stale_segment_scanner_claims(self):
        cid = self.create_scheduler_candidate_account(status="ready")
        other_cid = self.create_scheduler_candidate_account(status="ready")
        stale = datetime.utcnow() - timedelta(minutes=31)
        fresh = datetime.utcnow()
        for snapshot_id, row_cid, segment_id, status, claimed_at in (
            ("stale-snapshot-%s" % self.unique(), cid, "segment-stale", "diffing", stale),
            ("fresh-snapshot-%s" % self.unique(), cid, "segment-fresh", "diffing", fresh),
            ("completed-snapshot-%s" % self.unique(), cid, "segment-completed", "completed", stale),
            ("other-snapshot-%s" % self.unique(), other_cid, "segment-other", "baselining", stale),
        ):
            self.db.execute(
                """
                insert into automation_segment_trigger_snapshots
                    (id, cid, segment_id, status, hashlimit, last_hashval, claimed_at, claim_token, data)
                values (%s, %s, %s, %s, 1, 0, %s, 'claim-token', %s)
                """,
                snapshot_id,
                row_cid,
                segment_id,
                status,
                claimed_at,
                {"baseline_complete": True},
            )
        self.db.execute(
            """
            insert into automation_segment_trigger_members
                (cid, segment_id, contact_id, contact_email, bucket, first_seen_at, last_seen_at, scan_id)
            values (%s, 'segment-stale', 1, 'segment@example.com', 0, now(), now(), 'scan')
            """,
            cid,
        )

        result = self.recovery_post(
            cid,
            "clear-stale-segment-scanner-claims",
            {
                "dry_run": False,
                "confirm": "clear_stale_segment_scanner_claims",
            },
        )

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json["changed_count"], 1)
        self.assertEqual(self.db.single("select status from automation_segment_trigger_snapshots where cid = %s and segment_id = 'segment-stale'", cid), "idle")
        self.assertIsNone(self.db.single("select claim_token from automation_segment_trigger_snapshots where cid = %s and segment_id = 'segment-stale'", cid))
        self.assertEqual(self.db.single("select status from automation_segment_trigger_snapshots where cid = %s and segment_id = 'segment-fresh'", cid), "diffing")
        self.assertEqual(self.db.single("select status from automation_segment_trigger_snapshots where cid = %s and segment_id = 'segment-completed'", cid), "completed")
        self.assertEqual(self.db.single("select status from automation_segment_trigger_snapshots where cid = %s and segment_id = 'segment-other'", other_cid), "baselining")
        self.assertEqual(self.db.single("select count(*) from automation_segment_trigger_members where cid = %s and segment_id = 'segment-stale'", cid), 1)
        self.assertNotIn("data", result.json["items"][0])

    def test_scheduler_feature_flag_off_does_not_dispatch(self):
        os.environ.pop("automation_processing_enabled", None)
        self.set_customer_automation_processing(True)
        result, dispatched = self.run_scheduler_with_dispatch_patch([self.user_cookie["cid"]])

        self.assertEqual(result["enabled"], False)
        self.assertEqual(result["dispatched"], 0)
        self.assertEqual(dispatched, [])

    def test_scheduler_account_selection_ignores_customer_setting_false_or_absent(self):
        disabled = self.create_scheduler_candidate_account(
            status="ready",
            automation_processing_enabled=False,
        )
        absent = self.create_scheduler_candidate_account(
            status="ready",
            automation_processing_enabled=None,
        )

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertNotIn(disabled, cids)
        self.assertNotIn(absent, cids)

    def test_scheduler_account_selection_includes_customer_setting_true(self):
        cid = self.create_scheduler_candidate_account(
            status="ready",
            automation_processing_enabled=True,
        )

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertIn(cid, cids)

    def test_scheduler_enabled_dispatches_for_ready_account(self):
        os.environ["automation_processing_enabled"] = "true"
        result, dispatched = self.run_scheduler_with_dispatch_patch([self.user_cookie["cid"]])

        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["dispatched"], 1)
        self.assertEqual(dispatched[0]["task"], automations.process_automation_enrolments_task)
        self.assertEqual(dispatched[0]["cid"], self.user_cookie["cid"])
        self.assertIsNone(dispatched[0]["automation_id"])
        self.assertEqual(dispatched[0]["limit"], 25)

    def test_scheduler_enabled_dispatches_for_elapsed_waiting_account(self):
        os.environ["automation_processing_enabled"] = "1"
        result, dispatched = self.run_scheduler_with_dispatch_patch([self.user_cookie["cid"]])

        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["dispatched"], 1)
        self.assertEqual(dispatched[0]["cid"], self.user_cookie["cid"])

    def test_scheduler_account_selection_includes_ready_enrolment(self):
        cid = self.create_scheduler_candidate_account(status="ready")

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertIn(cid, cids)

    def test_scheduler_account_selection_ignores_future_retry_after(self):
        cid = self.create_scheduler_candidate_account(
            status="ready",
            retry_after=(datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z",
        )

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertNotIn(cid, cids)

    def test_scheduler_account_selection_treats_invalid_retry_after_as_elapsed(self):
        cid = self.create_scheduler_candidate_account(
            status="ready",
            retry_after="not-a-date",
        )

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertIn(cid, cids)

    def test_scheduler_does_not_dispatch_customer_setting_false(self):
        os.environ["automation_processing_enabled"] = "true"
        cid = self.create_scheduler_candidate_account(
            status="ready",
            automation_processing_enabled=False,
        )

        result, dispatched = self.run_scheduler_with_task_patch()

        self.assertEqual(result["enabled"], True)
        self.assertNotIn(cid, [item["cid"] for item in dispatched])

    def test_scheduler_dispatches_customer_setting_true_when_eligible(self):
        os.environ["automation_processing_enabled"] = "true"
        cid = self.create_scheduler_candidate_account(
            status="ready",
            automation_processing_enabled=True,
        )

        result, dispatched = self.run_scheduler_with_task_patch()

        self.assertEqual(result["enabled"], True)
        self.assertIn(cid, [item["cid"] for item in dispatched])

    def test_scheduler_account_selection_includes_elapsed_waiting_enrolment(self):
        cid = self.create_scheduler_candidate_account(
            status="waiting",
            wake_at=(datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z",
        )

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertIn(cid, cids)

    def test_scheduler_account_selection_ignores_non_elapsed_waiting(self):
        cid = self.create_scheduler_candidate_account(
            status="waiting",
            wake_at=(datetime.utcnow() + timedelta(minutes=5)).isoformat() + "Z",
        )

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertNotIn(cid, cids)

    def test_scheduler_account_selection_ignores_paused_automation(self):
        cid = self.create_scheduler_candidate_account(
            status="ready",
            automation_status="paused",
        )

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertNotIn(cid, cids)

    def test_scheduler_account_selection_respects_account_cap(self):
        first = self.create_scheduler_candidate_account(status="ready", modified_at="1970-01-01T00:00:00Z")
        second = self.create_scheduler_candidate_account(status="ready", modified_at="1970-01-01T00:00:01Z")

        cids = automations._automation_processing_account_ids(self.db, 1)

        self.assertEqual(len(cids), 1)
        self.assertTrue(first in cids or second in cids)

    def test_scheduler_account_selection_ignores_account_without_eligible_enrolments(self):
        cid = self.create_scheduler_candidate_account(status="completed")

        cids = automations._automation_processing_account_ids(self.db, 50)

        self.assertNotIn(cid, cids)

    def test_scheduler_ignores_non_elapsed_waiting_accounts_when_selection_is_empty(self):
        os.environ["automation_processing_enabled"] = "true"
        result, dispatched = self.run_scheduler_with_dispatch_patch([])

        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["dispatched"], 0)
        self.assertEqual(dispatched, [])

    def test_scheduler_ignores_paused_automation_accounts_when_selection_is_empty(self):
        os.environ["automation_processing_enabled"] = "true"
        result, dispatched = self.run_scheduler_with_dispatch_patch([])

        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["dispatched"], 0)
        self.assertEqual(dispatched, [])

    def test_scheduler_ignores_accounts_without_eligible_enrolments(self):
        os.environ["automation_processing_enabled"] = "true"
        result, dispatched = self.run_scheduler_with_dispatch_patch([])

        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["accounts"], 0)
        self.assertEqual(dispatched, [])

    def test_scheduler_account_cap_is_respected(self):
        os.environ["automation_processing_enabled"] = "true"
        os.environ["automation_processing_account_limit"] = "1"
        result, dispatched = self.run_scheduler_with_dispatch_patch([
            self.user_cookie["cid"],
            "other-account-cid",
        ])

        self.assertEqual(result["dispatched"], 1)
        self.assertEqual(result["account_limit"], 1)
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["cid"], self.user_cookie["cid"])

    def test_scheduler_process_limit_is_configurable_and_capped(self):
        os.environ["automation_processing_enabled"] = "true"
        os.environ["automation_processing_limit"] = "500"
        result, dispatched = self.run_scheduler_with_dispatch_patch([self.user_cookie["cid"]])

        self.assertEqual(result["limit"], 100)
        self.assertEqual(dispatched[0]["limit"], 100)

    def test_processing_budget_drains_backlog_without_executing_waits_early(self):
        from unittest.mock import patch
        a = self.create_wait_automation()
        self.addCleanup(self.cleanup, a["id"])
        enrolments = [self.enrol(a["id"], self.create_contact()[0]) for _ in range(5)]
        with patch.dict(os.environ, {"automation_processing_budget_seconds": "10"}):
            result = self.process_enrolments_task(a["id"], 2)
        self.assertEqual(result["processed"], 5)
        self.assertEqual(result["waiting"], 5)
        for e in enrolments:
            state = self.enrolment_data(e["id"])
            self.assertEqual(state["status"], "waiting")
            self.assertEqual(state["current_node_id"], a["published"]["nodes"][0]["id"])

    def test_processing_budget_deadline_stops_before_another_batch(self):
        from unittest.mock import patch
        a = self.create_automation()
        self.addCleanup(self.cleanup, a["id"])
        for _ in range(3):
            self.enrol(a["id"], self.create_contact()[0])
        with patch.dict(os.environ, {"automation_processing_budget_seconds": "5"}), \
                patch.object(automations.time, "monotonic", side_effect=[0, 6]):
            result = self.process_enrolments_task(a["id"], 1)
        self.assertEqual(result["processed"], 1)

    def test_processing_budget_invalid_setting_keeps_single_batch(self):
        from unittest.mock import patch
        a = self.create_automation()
        self.addCleanup(self.cleanup, a["id"])
        self.enrol(a["id"], self.create_contact()[0])
        with patch.dict(os.environ, {"automation_processing_budget_seconds": "invalid"}):
            result = self.process_enrolments_task(a["id"], 1)
        self.assertEqual(result["processed"], 1)

    def test_scheduler_one_node_only_relies_on_processor_task(self):
        email, contact_id = self.create_contact()
        automation = self.create_automation(
            nodes=[
                {
                    "id": "node_add_tag_1",
                    "type": "add_tag",
                    "label": "Add first scheduler tag",
                    "draft_tag": "scheduler-task-first-node",
                },
                {
                    "id": "node_add_tag_2",
                    "type": "add_tag",
                    "label": "Add second scheduler tag",
                    "draft_tag": "scheduler-task-second-node",
                },
            ]
        )
        enrolment = self.enrol(automation["id"], email)

        result = self.process_enrolments_task(automation["id"], 25)

        self.assertEqual(result["processed"], 1)
        self.assertTrue(self.has_tag(contact_id, "scheduler-task-first-node"))
        self.assertFalse(self.has_tag(contact_id, "scheduler-task-second-node"))
        data = self.enrolment_data(enrolment["id"])
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["current_node_id"], "node_add_tag_2")

        self.cleanup(automation["id"])

    def test_duplicate_published_node_ids_hold_before_any_action_or_target_resolution(self):
        from copy import deepcopy
        from unittest.mock import patch

        for action in ("add_tag", "send_email"):
            for duplicate_location in ("current", "unreachable"):
                with self.subTest(action=action, duplicate_location=duplicate_location):
                    email, contact_id = self.create_contact()
                    tag = "duplicate-guard-%s" % self.unique()
                    automation = self.create_automation(tag=tag) if action == "add_tag" else self.create_send_email_automation()
                    try:
                        enrolment = self.enrol(automation["id"], email)
                        published = deepcopy(automation["published"])
                        original_node_id = published["nodes"][0]["id"]
                        duplicate = deepcopy(published["nodes"][0 if duplicate_location == "current" else -1])
                        duplicate["label"] = "private-duplicate-label"
                        published["nodes"].append(duplicate)
                        self.db.set_cid(self.user_cookie["cid"])
                        self.db.automations.patch(automation["id"], {"published": published})
                        with patch.object(automations.contacts, "add_tag") as add_tag, \
                                patch.object(automations, "send_backend_mail") as send_mail, \
                                patch.object(automations, "_node_by_id") as target_lookup:
                            result = self.run_next(automation["id"], enrolment["id"])
                            add_tag.assert_not_called()
                            send_mail.assert_not_called()
                            target_lookup.assert_not_called()
                        self.assertEqual(result.status_code, 400, result.text)
                        self.assertEqual(result.json["title"], "Duplicate automation node IDs")
                        self.assertIn(duplicate["id"], result.json["description"])
                        self.assertNotIn("private-duplicate-label", result.text)
                        self.assertFalse(self.has_tag(contact_id, tag))
                        state = self.enrolment_data(enrolment["id"])
                        self.assertEqual(state["status"], "held")
                        self.assertEqual(state["current_node_id"], original_node_id)
                        self.assert_claim_cleared(state)
                        self.assertFalse(state["last_error"]["retryable"])
                        self.assertEqual(state["last_error"]["failure_class"], "configuration")
                        self.assertEqual(state["last_error"]["title"], "Duplicate automation node IDs")
                        self.assertNotIn("private-duplicate-label", str(state["last_error"]))
                        self.assertIsNone(state.get("last_failed_step_run_id"))
                        self.assertEqual(self.db.single(
                            "select count(*) from automation_step_runs where cid = %s and enrolment_id = %s",
                            self.user_cookie["cid"], enrolment["id"],
                        ), 0)
                        self.assertEqual(self.db.single(
                            "select count(*) from alltags where cid = %s and tag = %s",
                            self.user_cookie["cid"], tag,
                        ), 0)
                    finally:
                        self.cleanup(automation["id"])


    def publish_safety_call(self, db, automation_id, handler=None):
        from types import SimpleNamespace
        request = SimpleNamespace(context={
            "db": db, "uid": self.user_cookie["uid"], "admin": False, "api": False,
        })
        (handler or automations.AutomationPublish()).on_post(request, SimpleNamespace(), automation_id)
        return request.context["result"]

    def publish_safety_db(self):
        from api.shared.db import DB
        db = DB()
        db.set_cid(self.user_cookie["cid"])
        original_single = db.single
        def observed_single(sql, *args, **kwargs):
            if sql.startswith("select id from automations") and "for update" in sql:
                # The connection pool's protocol PID is not PostgreSQL's PID.
                # Capture the real server PID inside the worker transaction.
                db.publish_safety_pid = original_single("select pg_backend_pid()")
                db.execute("set local statement_timeout = '8s'")
            return original_single(sql, *args, **kwargs)
        db.single = observed_single
        self.addCleanup(db.close)
        return db

    def assert_publish_worker_waiting(self, observer, worker):
        import time
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            server_pid = worker.__dict__.get("publish_safety_pid")
            if server_pid and observer.single("select pg_backend_pid() = any(pg_blocking_pids(%s))", server_pid):
                return
            time.sleep(0.01)
        self.fail("Independent connection did not block on the automation row lock")

    def test_publish_safety_occupied_deletion_is_atomic_across_states(self):
        states = ("ready", "waiting", "held", "paused_ready", "paused_waiting", "running", "unknown")
        for status in states:
            with self.subTest(status=status):
                email, _ = self.create_contact()
                a = self.create_automation()
                self.addCleanup(self.cleanup, a["id"])
                e = self.enrol(a["id"], email)
                self.patch_enrolment_data(e["id"], {"status": status, "retry_count": 2})
                path = "/api/automations/" + a["id"]
                self.user_patch(path, json={"draft": {"nodes": a["published"]["nodes"][1:]}})
                before = self.user_get(path)
                enrolment_before = self.enrolment_data(e["id"])
                result = self.simulate_post(path + "/publish", headers=self.headers())
                self.assertEqual(result.status_code, 409, result.text)
                self.assertIn("execution" if status == "running" else "node_add_tag_1", result.text)
                self.assertNotIn(email, result.text)
                self.assertEqual(self.user_get(path), before)
                self.assertEqual(self.enrolment_data(e["id"]), enrolment_before)

    def test_publish_safety_unoccupied_and_terminal_nodes_can_be_removed(self):
        for status in (None,) + automations.TERMINAL_ENROLMENT_STATUSES:
            with self.subTest(status=status):
                a = self.create_automation()
                self.addCleanup(self.cleanup, a["id"])
                if status:
                    email, _ = self.create_contact()
                    e = self.enrol(a["id"], email)
                    self.patch_enrolment_data(e["id"], {"status": status})
                    before = self.enrolment_data(e["id"])
                path = "/api/automations/" + a["id"]
                self.user_patch(path, json={"draft": {"nodes": a["published"]["nodes"][1:]}})
                self.assertEqual(self.user_post(path + "/publish")["published_revision"], 2)
                if status:
                    self.assertEqual(self.enrolment_data(e["id"]), before)

    def test_publish_safety_paused_publish_preserves_wait_and_resume(self):
        a = self.create_automation(nodes=self.wait_nodes())
        self.addCleanup(self.cleanup, a["id"])
        email, _ = self.create_contact()
        e = self.enrol(a["id"], email)
        self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 200)
        path = "/api/automations/" + a["id"]
        self.user_post(path + "/pause")
        before = self.enrolment_data(e["id"])
        self.assertEqual(before["status"], "paused_waiting")
        self.assertEqual(self.user_post(path + "/publish")["status"], "paused")
        self.assertEqual(self.enrolment_data(e["id"]), before)
        email2, _ = self.create_contact()
        held = self.enrol(a["id"], email2)
        self.assertEqual(held["status"], "held")
        self.user_post(path + "/resume")
        after = self.enrolment_data(e["id"])
        self.assertEqual(after["status"], "waiting")
        self.assertEqual(after["wait"]["last_remaining_seconds"], before["wait"]["remaining_seconds"])
        self.assertEqual(self.enrolment_data(held["id"])["status"], "ready")

    def test_publish_safety_wait_type_and_duration_compatibility(self):
        from copy import deepcopy
        for paused in (False, True):
            with self.subTest(paused=paused):
                a = self.create_automation(nodes=self.wait_nodes())
                self.addCleanup(self.cleanup, a["id"])
                email, _ = self.create_contact()
                e = self.enrol(a["id"], email)
                self.run_next(a["id"], e["id"])
                path = "/api/automations/" + a["id"]
                if paused:
                    self.user_post(path + "/pause")
                nodes = deepcopy(a["published"]["nodes"])
                before = self.enrolment_data(e["id"])
                nodes[0] = {"id": nodes[0]["id"], "type": "exit", "label": "Exit"}
                self.user_patch(path, json={"draft": {"nodes": nodes}})
                automation_before = self.user_get(path)
                result = self.simulate_post(path + "/publish", headers=self.headers())
                self.assertEqual(result.status_code, 409, result.text)
                self.assertIn("remain Wait steps", result.text)
                self.assertEqual(self.user_get(path), automation_before)
                self.assertEqual(self.enrolment_data(e["id"]), before)
                nodes = deepcopy(a["published"]["nodes"])
                nodes[0]["duration"] = {"days": 3, "hours": 0, "minutes": 0}
                self.user_patch(path, json={"draft": {"nodes": nodes}})
                self.user_post(path + "/publish")
                self.assertEqual(self.enrolment_data(e["id"]), before)

    def test_publish_safety_old_action_blocks_publish_until_finished(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        a = self.create_automation(tag="publish-safety-action")
        self.addCleanup(self.cleanup, a["id"])
        email, _ = self.create_contact()
        e = self.enrol(a["id"], email)
        path = "/api/automations/" + a["id"]
        self.user_patch(path, json={"draft": {"nodes": a["published"]["nodes"][1:]}})
        worker = self.publish_safety_db()
        entered, release = Event(), Event()
        original = automations.contacts.add_tag
        def blocked_action(*args, **kwargs):
            self.assertFalse(worker.conn.autocommit, "The tag batch owns a short transaction, separate from the released claim lock")
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test did not release action")
            return original(*args, **kwargs)
        with patch.object(automations.contacts, "add_tag", side_effect=blocked_action), ThreadPoolExecutor(1) as pool:
            future = pool.submit(automations._run_next_automation_enrolment, worker, self.user_cookie["cid"], a["id"], e["id"])
            try:
                self.assertTrue(entered.wait(4))
                before = self.user_get(path)
                claimed = self.enrolment_data(e["id"])
                response = self.simulate_post(path + "/publish", headers=self.headers())
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.user_get(path), before)
                self.assertEqual(self.enrolment_data(e["id"]), claimed)
            finally:
                release.set()
            future.result(timeout=5)
        self.assertEqual(self.enrolment_data(e["id"])["current_node_id"], "node_exit_1")
        self.assertEqual(self.user_post(path + "/publish")["published_revision"], 2)

    def test_publish_safety_executor_waits_for_publish_and_reads_new_snapshot(self):
        from concurrent.futures import ThreadPoolExecutor
        a = self.create_automation(tag="old-publish-tag")
        self.addCleanup(self.cleanup, a["id"])
        email, contact_id = self.create_contact()
        e = self.enrol(a["id"], email)
        worker = self.publish_safety_db()
        publisher = self.publish_safety_db()
        stale = worker.automations.get(a["id"])
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(publisher, self.user_cookie["cid"], a["id"]):
                future = pool.submit(automations._run_next_automation_enrolment, worker, self.user_cookie["cid"], a["id"], e["id"])
                self.assert_publish_worker_waiting(publisher, worker)
                node = dict(stale["published"]["nodes"][0], draft_tag="new-publish-tag")
                publisher.automations.patch(a["id"], {"draft": {"nodes": [node]}})
                self.publish_safety_call(publisher, a["id"])
            result = future.result(timeout=5)
        self.assertTrue(self.has_tag(contact_id, "new-publish-tag"))
        self.assertFalse(self.has_tag(contact_id, "old-publish-tag"))
        self.assertEqual(result["step_run"]["published_revision"], 2)
        self.assertEqual(self.enrolment_data(e["id"])["status"], "completed")

    def test_publish_safety_concurrent_enrolment_uses_new_first_node(self):
        from concurrent.futures import ThreadPoolExecutor
        for reentry in (False, True):
            with self.subTest(reentry=reentry):
                a = self.create_automation(reentry="multiple" if reentry else "once")
                self.addCleanup(self.cleanup, a["id"])
                email, contact_id = self.create_contact()
                if reentry:
                    e = self.enrol(a["id"], email)
                    self.patch_enrolment_data(e["id"], {"status": "completed"})
                worker, publisher = self.publish_safety_db(), self.publish_safety_db()
                stale = worker.automations.get(a["id"])
                with ThreadPoolExecutor(1) as pool:
                    with automations._locked_automation(publisher, self.user_cookie["cid"], a["id"]):
                        future = pool.submit(automations._create_enrolment_for_contact, worker, self.user_cookie["cid"], a["id"], stale, contact_id, email, "manual")
                        self.assert_publish_worker_waiting(publisher, worker)
                        publisher.automations.patch(a["id"], {"draft": {"nodes": a["published"]["nodes"][1:]}})
                        self.publish_safety_call(publisher, a["id"])
                    outcome = future.result(timeout=5)
                state = self.enrolment_data(outcome["enrolment_id"])
                self.assertEqual(state["current_node_id"], "node_exit_1")
                self.assertEqual(state["published_revision"], 2)

    def test_publish_safety_publish_waits_for_new_enrolment(self):
        from concurrent.futures import ThreadPoolExecutor
        a = self.create_automation()
        self.addCleanup(self.cleanup, a["id"])
        email, contact_id = self.create_contact()
        creator, publisher = self.publish_safety_db(), self.publish_safety_db()
        self.user_patch("/api/automations/" + a["id"], json={"draft": {"nodes": a["published"]["nodes"][1:]}})
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(creator, self.user_cookie["cid"], a["id"]):
                outcome = automations._create_enrolment_for_contact(creator, self.user_cookie["cid"], a["id"], a, contact_id, email, "manual")
                future = pool.submit(self.publish_safety_call, publisher, a["id"])
                self.assert_publish_worker_waiting(creator, publisher)
            with self.assertRaises(falcon.HTTPConflict):
                future.result(timeout=5)
        self.assertEqual(self.enrolment_data(outcome["enrolment_id"])["current_node_id"], "node_add_tag_1")
        self.assertEqual(publisher.automations.get(a["id"])["published_revision"], 1)

    def test_publish_safety_serializes_publishers_and_resume(self):
        from concurrent.futures import ThreadPoolExecutor
        for handler in (automations.AutomationPublish, automations.AutomationResume):
            with self.subTest(handler=handler.__name__):
                a = self.create_automation()
                self.addCleanup(self.cleanup, a["id"])
                email, _ = self.create_contact()
                e = self.enrol(a["id"], email)
                self.user_post("/api/automations/" + a["id"] + "/pause")
                publisher, worker = self.publish_safety_db(), self.publish_safety_db()
                with ThreadPoolExecutor(1) as pool:
                    with automations._locked_automation(publisher, self.user_cookie["cid"], a["id"]):
                        future = pool.submit(self.publish_safety_call, worker, a["id"], handler())
                        self.assert_publish_worker_waiting(publisher, worker)
                        self.assertEqual(self.publish_safety_call(publisher, a["id"])["status"], "paused")
                    result = future.result(timeout=5)
                if handler is automations.AutomationPublish:
                    self.assertEqual(result["published_revision"], 3)
                    self.assertEqual(result["status"], "paused")
                else:
                    self.assertEqual(result["published_revision"], 2)
                    self.assertEqual(result["status"], "published")
                    self.assertEqual(self.enrolment_data(e["id"])["status"], "ready")

    def test_publish_safety_stale_claim_requires_explicit_recovery(self):
        a = self.create_automation()
        self.addCleanup(self.cleanup, a["id"])
        email, _ = self.create_contact()
        e = self.enrol(a["id"], email)
        self.patch_enrolment_data(e["id"], {
            "status": "running", "running_status": "ready", "claim_token": "stale-publish-claim",
            "claimed_at": (datetime.utcnow() - timedelta(hours=2)).isoformat() + "Z",
        })
        path = "/api/automations/" + a["id"]
        before = self.enrolment_data(e["id"])
        response = self.simulate_post(path + "/publish", headers=self.headers())
        self.assertEqual(response.status_code, 409)
        self.assertIn("recovery", response.text)
        self.assertEqual(self.enrolment_data(e["id"]), before)
        from concurrent.futures import ThreadPoolExecutor
        self.db.set_cid(self.user_cookie["cid"])
        recovery = self.publish_safety_db()
        # Recovery already locks the joined automation/enrolment rows with
        # SKIP LOCKED; it must not clear claims across a publication boundary.
        with ThreadPoolExecutor(1) as pool:
            with automations._locked_automation(self.db, self.user_cookie["cid"], a["id"]):
                future = pool.submit(
                    automations.recover_stale_automation_enrolment_claims,
                    recovery, self.user_cookie["cid"], dry_run=False, automation_id=a["id"],
                )
                self.assertEqual(future.result(timeout=5)["changed_count"], 0)
        self.assertEqual(self.enrolment_data(e["id"]), before)
        result = automations.recover_stale_automation_enrolment_claims(
            self.db, self.user_cookie["cid"], dry_run=False, automation_id=a["id"],
        )
        self.assertEqual(result["changed_count"], 1)
        self.assertEqual(self.user_post(path + "/publish")["published_revision"], 2)

    def test_publish_safety_audit_failure_rolls_back_snapshot(self):
        from unittest.mock import patch
        a = self.create_automation()
        self.addCleanup(self.cleanup, a["id"])
        path = "/api/automations/" + a["id"]
        before = self.user_get(path)
        db = self.publish_safety_db()
        with patch.object(automations, "user_log", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.publish_safety_call(db, a["id"])
        self.assertEqual(self.user_get(path), before)

    def test_negative_conditions_plural_none_match_and_group_modes(self):
        email, contact_id = self.create_contact()
        member_list = self.contact_list_ids(contact_id)[0]
        other = self.create_empty_list()["id"]
        automation = self.create_compound_condition_automation(items=[
            {"type": "missing_tag", "tags": ["blocked", "inactive"]},
            {"type": "not_in_list", "list_ids": [other]},
        ])
        self.addCleanup(self.cleanup, automation["id"])
        enrolment = self.enrol(automation["id"], email)
        cid = self.user_cookie["cid"]
        def evaluate(items, mode="all"):
            return automations._evaluate_automation_condition_group(
                self.db, cid, automation["id"], enrolment["id"], contact_id,
                {"mode": mode, "items": items})["result"]
        for ids, expected in [([other], True), ([other, member_list], False), ([member_list, other], False)]:
            self.assertEqual(evaluate([{"type": "not_in_list", "list_ids": ids}]), expected)
        self.add_existing_tag(contact_id, "blocked")
        for tags, expected in [(["inactive"], True), (["inactive", "blocked"], False), (["blocked", "inactive"], False)]:
            self.assertEqual(evaluate([{"type": "missing_tag", "tags": tags}]), expected)
        items = [{"type": "missing_tag", "tags": ["blocked"]}, {"type": "not_in_list", "list_ids": [other]}]
        self.assertFalse(evaluate(items, "all"))
        self.assertTrue(evaluate(items, "any"))
        # The persisted executable condition uses the same semantics and advances once.
        result = self.run_next(automation["id"], enrolment["id"])
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json["step_run"]["result"])
        self.assertEqual(result.json["enrolment"]["current_node_id"], "node_exit_1")

    def test_negative_conditions_email_scope_and_matching(self):
        email, contact_id = self.create_contact()
        a = self.create_compound_condition_automation(reentry="multiple")
        self.addCleanup(self.cleanup, a["id"])
        owned = self.user_post("/api/automations/%s/emails" % a["id"], json={
            "name": "Negative engagement test", "subject": "No delivery", "rawText": "<p>Test</p>"})
        cid = self.user_cookie["cid"]
        for kind, event_type in [("not_opened_email", "open"), ("not_clicked_email", "click")]:
            for match in (["any"] if event_type == "open" else ["any", "url", "url_exact", "url_prefix"]):
                with self.subTest(kind=kind, match=match):
                    item = {"type": kind, "automation_email_id": owned["id"]}
                    if event_type == "click":
                        item.update(click_match=match, link_url="https://example.com/Offer")
                    nodes = a["draft"]["nodes"]
                    nodes[0]["condition"]["items"] = [item]
                    self.user_patch("/api/automations/" + a["id"], json=self.workflow(nodes=nodes, reentry="multiple"))
                    result = self.simulate_post("/api/automations/%s/publish" % a["id"], headers=self.headers())
                    self.assertEqual(result.status_code, 200)
                    deletion = self.simulate_delete("/api/automations/%s/emails/%s" % (a["id"], owned["id"]), headers=self.headers())
                    self.assertEqual(deletion.status_code, 400)
                    e = self.enrol(a["id"], email)
                    def evaluate():
                        return automations._evaluate_automation_condition_item(
                            self.db, cid, a["id"], e["id"], contact_id, item, 0)["result"]
                    self.assertTrue(evaluate())  # No send/event yet: no implicit wait.
                    data = {"link_url": "HTTPS://EXAMPLE.COM/Offer", "test_id": self.test_id}
                    for override in [{"event_enrolment_id": "previous-enrolment"},
                                     {"event_automation_email_id": "another-email"},
                                     {"event_contact_id": contact_id + 1000000},
                                     {"event_cid": "another-account"}]:
                        self.insert_open_event(a["id"], e["id"], contact_id, email, owned["id"],
                                               event_type=event_type, event_data=data, **override)
                        self.assertTrue(evaluate())
                    if event_type == "click" and match != "any":
                        self.insert_open_event(a["id"], e["id"], contact_id, email, owned["id"],
                            event_type="click", event_data={"link_url": "https://example.com/Other"})
                        self.assertTrue(evaluate())
                    if match == "url_prefix":
                        data["link_url"] += "?utm=one"
                    self.insert_open_event(a["id"], e["id"], contact_id, email, owned["id"], event_type=event_type, event_data=data)
                    self.assertFalse(evaluate())
                    outcome = self.run_next(a["id"], e["id"])
                    self.assertEqual(outcome.status_code, 200)
                    self.assertFalse(outcome.json["step_run"]["result"])
                    self.assertEqual(outcome.json["enrolment"]["current_node_id"], "node_exit_1")
                    self.assertEqual(self.run_next(a["id"], e["id"]).status_code, 200)
        # A fresh enrolment must not inherit engagement from any previous run.
        e = self.enrol(a["id"], email)
        outcome = self.run_next(a["id"], e["id"])
        self.assertTrue(outcome.json["step_run"]["result"])
        self.assertEqual(outcome.json["enrolment"]["current_node_id"], "node_add_tag_1")

    def test_negative_conditions_draft_publish_validation(self):
        a = self.create_compound_condition_automation()
        self.addCleanup(self.cleanup, a["id"])
        nodes = a["draft"]["nodes"]
        def save(item):
            nodes[0]["condition"]["items"] = [item]
            return self.simulate_patch("/api/automations/" + a["id"], headers=self.headers(), json=self.workflow(nodes=nodes))
        for item in [
            {"type": "missing_tag", "tag": "one", "tags": ["two"]},
            {"type": "missing_tag", "tags": ["one", "one"]},
            {"type": "missing_tag", "tags": [1]},
            {"type": "not_in_list", "list_ids": [1]},
            {"type": "not_in_list", "list_ids": ["one", "one"]},
            {"type": "not_in_list", "list_id": "one", "list_ids": ["two"]},
            {"type": "not_opened_email", "automation_email_id": "one", "link_url": "unexpected"},
        ]:
            with self.subTest(item=item): self.assertEqual(save(item).status_code, 400)
        # Incomplete drafts are editable, but never executable.
        for item in [
            {"type": "missing_tag", "tags": []}, {"type": "missing_tag", "tags": [" "]},
            {"type": "not_in_list", "list_ids": []}, {"type": "not_in_list", "list_ids": ["missing-list"]},
            {"type": "not_opened_email", "automation_email_id": ""},
            {"type": "not_clicked_email", "automation_email_id": "missing-email"},
        ]:
            with self.subTest(item=item):
                self.assertEqual(save(item).status_code, 200)
                result = self.simulate_post("/api/automations/%s/publish" % a["id"], headers=self.headers())
                self.assertEqual(result.status_code, 400)
        foreign = self.create_compound_condition_automation()
        self.addCleanup(self.cleanup, foreign["id"])
        foreign_email = self.user_post("/api/automations/%s/emails" % foreign["id"], json={
            "name": "Other owned email", "subject": "No delivery", "rawText": "<p>Test</p>"})
        for kind in ["not_opened_email", "not_clicked_email"]:
            self.assertEqual(save({"type": kind, "automation_email_id": foreign_email["id"]}).status_code, 200)
            result = self.simulate_post("/api/automations/%s/publish" % a["id"], headers=self.headers())
            self.assertEqual(result.status_code, 400)
            self.assertIn("email from this automation", result.text)
        owned = self.user_post("/api/automations/%s/emails" % a["id"], json={
            "name": "URL validation email", "subject": "No delivery", "rawText": "<p>Test</p>"})
        self.assertEqual(save({"type": "not_clicked_email", "automation_email_id": owned["id"],
                               "click_match": "url_exact", "link_url": ""}).status_code, 200)
        result = self.simulate_post("/api/automations/%s/publish" % a["id"], headers=self.headers())
        self.assertEqual(result.status_code, 400)
        self.assertIn("link URL", result.text)
        foreign_list = self.create_empty_list()["id"]
        try:
            self.db.execute("update lists set cid = 'other-account' where id = %s", foreign_list)
            self.assertEqual(save({"type": "not_in_list", "list_ids": [foreign_list]}).status_code, 200)
            result = self.simulate_post("/api/automations/%s/publish" % a["id"], headers=self.headers())
            self.assertEqual(result.status_code, 400)
            self.assertIn("list from this account", result.text)
        finally:
            self.db.execute("update lists set cid = %s where id = %s", self.user_cookie["cid"], foreign_list)

    def test_positive_plural_conditions_save_publish_and_match_any_selection(self):
        email, contact_id = self.create_contact()
        member_list = self.contact_list_ids(contact_id)[0]
        other_list = self.create_empty_list()["id"]
        self.add_existing_tag(contact_id, "customer")
        cases = [
            ({"type": "has_tag", "tags": ["absent", "customer"]}, True),
            ({"type": "has_tag", "tags": ["customer", "absent"]}, True),
            ({"type": "has_tag", "tags": ["absent", "another"]}, False),
            ({"type": "in_list", "list_ids": [other_list, member_list]}, True),
            ({"type": "in_list", "list_ids": [member_list, other_list]}, True),
            ({"type": "in_list", "list_ids": [other_list]}, False),
            ({"type": "has_tag", "tag": "customer"}, True),
            ({"type": "in_list", "list_id": member_list}, True),
        ]
        for item, expected in cases:
            with self.subTest(item=item):
                a = self.create_compound_condition_automation(items=[item])
                self.addCleanup(self.cleanup, a["id"])
                reloaded = self.user_get("/api/automations/" + a["id"])
                self.assertEqual(reloaded["draft"]["nodes"][0]["condition"]["items"], [item])
                self.assertEqual(reloaded["published"]["nodes"][0]["condition"]["items"], [item])
                e = self.enrol(a["id"], email)
                result = self.run_next(a["id"], e["id"])
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json["step_run"]["result"], expected)
                self.assertEqual(result.json["enrolment"]["current_node_id"],
                                 "node_add_tag_1" if expected else "node_exit_1")

    def test_positive_plural_conditions_validate_like_negative_selections(self):
        a = self.create_compound_condition_automation()
        self.addCleanup(self.cleanup, a["id"])
        nodes = a["draft"]["nodes"]
        for kind, field, singular in [("has_tag", "tags", "tag"), ("in_list", "list_ids", "list_id")]:
            for values, draft_status in [([], 200), ([""], 200), ([1], 400), (["x", "x"], 400),
                                         ([str(i) for i in range(101)], 400)]:
                with self.subTest(kind=kind, values=values):
                    nodes[0]["condition"]["items"] = [{"type": kind, field: values}]
                    result = self.simulate_patch("/api/automations/" + a["id"], headers=self.headers(), json=self.workflow(nodes=nodes))
                    self.assertEqual(result.status_code, draft_status)
                    if draft_status == 200:
                        published = self.simulate_post("/api/automations/%s/publish" % a["id"], headers=self.headers())
                        self.assertEqual(published.status_code, 400)
            nodes[0]["condition"]["items"] = [{"type": kind, field: ["x"], singular: "x"}]
            result = self.simulate_patch("/api/automations/" + a["id"], headers=self.headers(), json=self.workflow(nodes=nodes))
            self.assertEqual(result.status_code, 400)

    def test_concurrent_plural_list_actions_do_not_duplicate_change_events(self):
        self.assert_concurrent_list_batch("add_to_list")

    def test_concurrent_plural_list_removals_do_not_duplicate_change_events(self):
        self.assert_concurrent_list_batch("remove_from_list")

    def assert_concurrent_list_batch(self, action):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        email, contact_id = self.create_contact()
        ids = [self.create_empty_list()["id"], self.create_empty_list()["id"]]
        if action == "remove_from_list":
            for value in ids:
                automations._add_contact_to_list(self.db, self.user_cookie["cid"], contact_id, email, value)
        nodes = [{"id":"lists", "type":action, "label":"Lists", "list_ids": ids}]
        first = self.create_automation(nodes=nodes)
        second = self.create_automation(nodes=nodes)
        self.addCleanup(self.cleanup, first["id"], second["id"])
        one, two = self.enrol(first["id"], email), self.enrol(second["id"], email)
        db1, db2 = self.publish_safety_db(), self.publish_safety_db()
        entered, release, second_started = Event(), Event(), Event()
        helper_name = "_add_contact_to_list" if action == "add_to_list" else "_remove_contact_from_list"
        original = getattr(automations, helper_name)
        original_execute = db2.execute
        def observed_execute(sql, *args, **kwargs):
            if sql.startswith('select contact_id from contacts.') and 'for update' in sql:
                db2.list_batch_pid = db2.single("select pg_backend_pid()")
                second_started.set()
            return original_execute(sql, *args, **kwargs)
        db2.execute = observed_execute
        def blocked(db, *args, **kwargs):
            if db is db1:
                db1.list_batch_pid = db.single("select pg_backend_pid()")
                entered.set()
                if not release.wait(5): raise AssertionError("List batch was not released")
            return original(db, *args, **kwargs)
        def run_second():
            return automations._run_next_automation_enrolment(db2, self.user_cookie["cid"], second["id"], two["id"])
        with patch.dict(os.environ, {"automation_trigger_emission_enabled":"true"}), patch.object(automations.contacts, "matching_list_trigger_automation_exists", return_value=True), patch.object(automations, helper_name, side_effect=blocked), ThreadPoolExecutor(2) as pool:
            f1 = pool.submit(automations._run_next_automation_enrolment, db1, self.user_cookie["cid"], first["id"], one["id"])
            try:
                self.assertTrue(entered.wait(4))
                f2 = pool.submit(run_second)
                self.assertTrue(second_started.wait(4))
                import time
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    blockers = self.db.single("select pg_blocking_pids(%s)", db2.list_batch_pid)
                    if db1.list_batch_pid in blockers: break
                    time.sleep(0.01)
                self.assertIn(db1.list_batch_pid, blockers, "The second batch must wait for the first contact lock")
            finally:
                release.set()
            f1.result(timeout=5)
            f2.result(timeout=5)
        rows = self.db.execute("select data from automation_trigger_events where cid = %s and contact_id = %s", self.user_cookie["cid"], contact_id).fetchall()
        self.addCleanup(self.db.execute, "delete from automation_trigger_events where cid = %s and contact_id = %s", self.user_cookie["cid"], contact_id)
        self.assertEqual(sorted(row[0]["list_id"] for row in rows), sorted(ids))
        for value in ids:
            self.assertEqual(self.list_count(value), 1 if action == "add_to_list" else 0)
        self.assert_claim_cleared(self.enrolment_data(one["id"]))
        self.assert_claim_cleared(self.enrolment_data(two["id"]))
