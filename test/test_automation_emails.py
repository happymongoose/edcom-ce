import shortuuid
from unittest.mock import patch

import test_base


class TestAutomationEmails(test_base.TestBase):

    def setUp(self):
        super(TestAutomationEmails, self).setUp()
        self.created_automation_ids = []
        self.created_email_ids = []
        self.created_txn_template_ids = []
        self.created_campaign_ids = []
        self.created_funnel_ids = []
        self.created_message_ids = []

    def tearDown(self):
        cid = self.user_cookie["cid"]
        if self.created_email_ids:
            self.db.execute(
                "delete from automation_emails where id = any(%s) and cid = %s",
                self.created_email_ids,
                cid,
            )
        if self.created_automation_ids:
            self.db.execute(
                "delete from automation_emails where automation_id = any(%s) and cid = %s",
                self.created_automation_ids,
                cid,
            )
            self.db.execute(
                "delete from automations where id = any(%s) and cid = %s",
                self.created_automation_ids,
                cid,
            )
        if self.created_txn_template_ids:
            self.db.execute(
                "delete from txntemplates where id = any(%s) and cid = %s",
                self.created_txn_template_ids,
                cid,
            )
        if self.created_campaign_ids:
            self.db.execute(
                "delete from campaigns where id = any(%s) and cid = %s",
                self.created_campaign_ids,
                cid,
            )
        if self.created_message_ids:
            self.db.execute(
                "delete from messages where id = any(%s) and cid = %s",
                self.created_message_ids,
                cid,
            )
        if self.created_funnel_ids:
            self.db.execute(
                "delete from funnels where id = any(%s) and cid = %s",
                self.created_funnel_ids,
                cid,
            )
        super(TestAutomationEmails, self).tearDown()

    def unique(self):
        return shortuuid.uuid().lower()

    def headers(self):
        return {
            "X-Auth-UID": self.user_cookie["uid"],
            "X-Auth-Cookie": self.user_cookie["id"],
        }

    def create_automation(self):
        automation = self.user_post(
            "/api/automations",
            json={"name": "automation_emails_%s" % self.unique()},
        )
        self.created_automation_ids.append(automation["id"])
        return automation

    def create_email(self, automation_id, **overrides):
        doc = {
            "name": "Email %s" % self.unique(),
            "subject": "Subject",
            "preheader": "Preview",
            "rawText": "<p>Hello</p>",
        }
        doc.update(overrides)
        email = self.user_post(
            "/api/automations/%s/emails" % automation_id,
            json=doc,
        )
        self.created_email_ids.append(email["id"])
        return email

    def create_txn_template(self, **overrides):
        doc = {
            "name": "Txn template %s" % self.unique(),
            "subject": "Txn subject",
            "preheader": "Txn preview",
            "type": "raw",
            "rawText": "<p>Transactional</p>",
            "parts": [],
            "bodyStyle": {},
            "fromname": "Txn Sender",
            "fromemail": "from@example.com",
            "replyto": "reply@example.com",
            "returnpath": "bounce@example.com",
            "tag": "do-not-copy",
        }
        doc.update(overrides)
        template_id = shortuuid.uuid()
        self.db.execute(
            "insert into txntemplates (id, cid, data) values (%s, %s, %s)",
            template_id,
            self.user_cookie["cid"],
            doc,
        )
        self.created_txn_template_ids.append(template_id)
        template = self.db.txntemplates.get(template_id)
        template["id"] = template_id
        return template

    def create_campaign(self, **overrides):
        doc = {
            "name": "Broadcast %s" % self.unique(),
            "subject": "Broadcast subject",
            "preheader": "Broadcast preview",
            "type": "raw",
            "rawText": "<p>Broadcast</p>",
            "parts": [],
            "bodyStyle": {},
            "fromname": "Broadcast Sender",
            "fromemail": "from@example.com",
            "replyto": "reply@example.com",
            "returnpath": "bounce@example.com",
            "when": "draft",
            "lists": [],
            "segments": [],
            "tags": [],
            "supplists": [],
            "suppsegs": [],
            "supptags": [],
        }
        doc.update(overrides)
        campaign_id = shortuuid.uuid()
        self.db.execute(
            "insert into campaigns (id, cid, data) values (%s, %s, %s)",
            campaign_id,
            self.user_cookie["cid"],
            doc,
        )
        self.created_campaign_ids.append(campaign_id)
        campaign = self.db.campaigns.get(campaign_id)
        campaign["id"] = campaign_id
        return campaign

    def create_funnel_message(self, funnel_overrides=None, message_overrides=None, meta_overrides=None):
        message_id = shortuuid.uuid()
        funnel_doc = {
            "name": "Funnel %s" % self.unique(),
            "type": "tags",
            "active": True,
            "messages": [
                {
                    "id": message_id,
                    "whennum": 1,
                    "whentype": "days",
                    "whentime": "",
                    "fromname": "Funnel Sender",
                    "returnpath": "bounce@example.com",
                    "fromemail": "from@example.com",
                    "replyto": "reply@example.com",
                    "msgroute": "do-not-copy",
                }
            ],
        }
        if meta_overrides is not None:
            funnel_doc["messages"][0].update(meta_overrides)
        if funnel_overrides:
            funnel_doc.update(funnel_overrides)
        funnel_id = shortuuid.uuid()
        self.db.execute(
            "insert into funnels (id, cid, data) values (%s, %s, %s)",
            funnel_id,
            self.user_cookie["cid"],
            funnel_doc,
        )
        self.created_funnel_ids.append(funnel_id)

        message_doc = {
            "funnel": funnel_id,
            "subject": "Funnel subject",
            "preheader": "Funnel preview",
            "type": "raw",
            "rawText": "<p>Funnel</p>",
            "parts": [],
            "bodyStyle": {},
            "modified": "2026-08-16T12:00:00Z",
            "delivered": 10,
            "send": 10,
            "soft": 1,
            "hard": 1,
            "opened": 2,
            "clicked": 3,
            "opened_all": 4,
            "clicked_all": 5,
            "unsubscribed": 1,
            "complained": 1,
            "bounced": 1,
            "linkurls": ["https://example.com"],
            "linkclicks": [1],
            "openaddtags": ["do-not-copy"],
            "openremtags": ["do-not-copy"],
            "clickaddtags": ["do-not-copy"],
            "clickremtags": ["do-not-copy"],
            "sendaddtags": ["do-not-copy"],
            "sendremtags": ["do-not-copy"],
            "supplists": ["do-not-copy"],
            "supptags": ["do-not-copy"],
            "suppsegs": ["do-not-copy"],
            "who": "all",
            "days": [True, True, True, True, True, True, True],
            "dayoffset": 0,
            "arbitrary_metadata": {"nested": "do-not-copy"},
        }
        if message_overrides:
            message_doc.update(message_overrides)
        self.db.execute(
            "insert into messages (id, cid, data) values (%s, %s, %s)",
            message_id,
            self.user_cookie["cid"],
            message_doc,
        )
        self.created_message_ids.append(message_id)
        message = self.db.messages.get(message_id)
        message["id"] = message_id
        funnel = self.db.funnels.get(funnel_id)
        funnel["id"] = funnel_id
        return funnel, message

    def route_id(self):
        company = self.db.companies.get(self.user_cookie["cid"])
        return company["routes"][0]

    def test_create_list_get_patch_duplicate_and_delete_email(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        self.assertEqual(email["automation_id"], automation["id"])
        self.assertEqual(email["name"].startswith("Email "), True)
        self.assertEqual(email["subject"], "Subject")
        self.assertEqual(email["preheader"], "Preview")
        self.assertEqual(email["type"], "raw")
        self.assertEqual(email["rawText"], "<p>Hello</p>")
        self.assertEqual(email["parts"], [])
        self.assertEqual(email["bodyStyle"], {})
        self.assertEqual(email["fromname"], "")
        self.assertEqual(email["fromemail"], "")
        self.assertEqual(email["replyto"], "")
        self.assertEqual(email["returnpath"], "")
        self.assertIn("created", email)
        self.assertIn("modified", email)

        emails = self.user_get("/api/automations/%s/emails" % automation["id"])
        self.assertEqual([item["id"] for item in emails], [email["id"]])

        fetched = self.user_get(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"])
        )
        self.assertEqual(fetched["id"], email["id"])

        patched = self.user_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={
                "name": "Updated name",
                "subject": "Updated subject",
                "preheader": "Updated preview",
                "rawText": "<p>Updated</p>",
            },
        )
        self.assertEqual(patched["name"], "Updated name")
        self.assertEqual(patched["subject"], "Updated subject")
        self.assertEqual(patched["rawText"], "<p>Updated</p>")
        self.assertEqual(patched["fromname"], "")
        self.assertEqual(patched["fromemail"], "")
        self.assertEqual(patched["replyto"], "")
        self.assertEqual(patched["returnpath"], "")

        duplicated = self.user_post(
            "/api/automations/%s/emails/%s/duplicate" % (automation["id"], email["id"]),
            json={},
        )
        self.created_email_ids.append(duplicated["id"])
        self.assertNotEqual(duplicated["id"], email["id"])
        self.assertEqual(duplicated["subject"], "Updated subject")
        self.assertEqual(duplicated["rawText"], "<p>Updated</p>")
        self.assertEqual(duplicated["name"], "Updated name (2)")

        self.user_delete(
            "/api/automations/%s/emails/%s" % (automation["id"], duplicated["id"])
        )
        emails = self.user_get("/api/automations/%s/emails" % automation["id"])
        self.assertEqual([item["id"] for item in emails], [email["id"]])

    def test_email_copy_sources_list_same_and_other_automation_sources(self):
        target = self.create_automation()
        other = self.create_automation()
        same_email = self.create_email(
            target["id"],
            name="Same source",
            subject="Same subject",
        )
        other_email = self.create_email(
            other["id"],
            name="Other source",
            subject="Other subject",
        )

        all_sources = self.user_get(
            "/api/automations/%s/email-copy-sources" % target["id"]
        )
        this_sources = self.user_get(
            "/api/automations/%s/email-copy-sources?source_filter=this" % target["id"]
        )
        other_sources = self.user_get(
            "/api/automations/%s/email-copy-sources?source_filter=other" % target["id"]
        )

        self.assertIn(same_email["id"], [item["source_id"] for item in all_sources])
        self.assertIn(other_email["id"], [item["source_id"] for item in all_sources])
        self.assertEqual([item["source_id"] for item in this_sources], [same_email["id"]])
        self.assertIn(other_email["id"], [item["source_id"] for item in other_sources])
        self.assertNotIn(same_email["id"], [item["source_id"] for item in other_sources])
        self.assertEqual(this_sources[0]["source_type"], "automation_email")
        self.assertEqual(this_sources[0]["source_automation_id"], target["id"])
        self.assertEqual(this_sources[0]["source_automation_name"], target["name"])
        self.assertNotIn("rawText", this_sources[0])
        self.assertNotIn("parts", this_sources[0])
        self.assertNotIn("bodyStyle", this_sources[0])

    def test_email_copy_sources_search_and_invalid_filter(self):
        target = self.create_automation()
        other = self.create_automation()
        wanted = self.create_email(other["id"], name="Find this source", subject="Needle")
        self.create_email(other["id"], name="Ignore this source", subject="Haystack")

        sources = self.user_get(
            "/api/automations/%s/email-copy-sources?q=needle" % target["id"]
        )
        result = self.simulate_get(
            "/api/automations/%s/email-copy-sources?source_filter=bad" % target["id"],
            headers=self.headers(),
        )

        self.assertEqual([item["source_id"] for item in sources], [wanted["id"]])
        self.assertEqual(result.status_code, 400)
        self.assertIn(
            "Source filter must be this, other, all, transactional_templates, broadcasts or funnel_messages",
            result.text,
        )

    def test_email_copy_sources_list_transactional_templates_metadata_only(self):
        target = self.create_automation()
        template = self.create_txn_template(
            name="Transactional copy source",
            subject="Transactional needle",
            type="wysiwyg",
            rawText="<h1>Hidden body</h1>",
            parts=[{"type": "text", "value": "hidden"}],
            bodyStyle={"hidden": True},
        )
        self.create_txn_template(name="Ignore me", subject="Haystack")

        sources = self.user_get(
            "/api/automations/%s/email-copy-sources?source_filter=transactional_templates&q=needle"
            % target["id"]
        )

        self.assertEqual([item["source_id"] for item in sources], [template["id"]])
        self.assertEqual(sources[0]["source_type"], "transactional_template")
        self.assertEqual(sources[0]["name"], "Transactional copy source")
        self.assertEqual(sources[0]["subject"], "Transactional needle")
        self.assertEqual(sources[0]["editor_type"], "wysiwyg")
        self.assertEqual(sources[0]["source_label"], "Transactional template")
        self.assertNotIn("rawText", sources[0])
        self.assertNotIn("parts", sources[0])
        self.assertNotIn("bodyStyle", sources[0])

    def test_email_copy_sources_list_broadcasts_metadata_only(self):
        target = self.create_automation()
        draft = self.create_campaign(
            name="Draft broadcast source",
            subject="Draft broadcast needle",
            type="wysiwyg",
            rawText="<h1>Hidden draft body</h1>",
            parts=[{"type": "text", "value": "hidden"}],
            bodyStyle={"hidden": True},
        )
        sent = self.create_campaign(
            name="Sent broadcast source",
            subject="Sent broadcast needle",
            sent_at="2026-08-16T12:00:00Z",
        )
        self.create_campaign(
            name="Hidden broadcast source",
            subject="Hidden broadcast needle",
            hidden=True,
        )

        sources = self.user_get(
            "/api/automations/%s/email-copy-sources?source_filter=broadcasts&q=broadcast%%20needle"
            % target["id"]
        )
        source_ids = [item["source_id"] for item in sources]

        self.assertIn(draft["id"], source_ids)
        self.assertIn(sent["id"], source_ids)
        self.assertNotIn("rawText", sources[0])
        self.assertNotIn("parts", sources[0])
        self.assertNotIn("bodyStyle", sources[0])
        draft_source = [item for item in sources if item["source_id"] == draft["id"]][0]
        sent_source = [item for item in sources if item["source_id"] == sent["id"]][0]
        self.assertEqual(draft_source["source_type"], "broadcast")
        self.assertEqual(draft_source["source_label"], "Broadcast")
        self.assertEqual(draft_source["status"], "draft")
        self.assertEqual(sent_source["status"], "sent")

    def test_email_copy_sources_list_funnel_messages_metadata_only(self):
        target = self.create_automation()
        funnel, message = self.create_funnel_message(
            funnel_overrides={"name": "Welcome funnel needle"},
            message_overrides={
                "subject": "Funnel message needle",
                "type": "wysiwyg",
                "rawText": "<h1>Hidden funnel body</h1>",
                "parts": [{"type": "text", "value": "hidden"}],
                "bodyStyle": {"hidden": True},
            },
        )
        self.create_funnel_message(
            funnel_overrides={"name": "Ignore funnel"},
            message_overrides={"subject": "Haystack"},
        )

        sources = self.user_get(
            "/api/automations/%s/email-copy-sources?source_filter=funnel_messages&q=needle"
            % target["id"]
        )

        self.assertEqual([item["source_id"] for item in sources], [message["id"]])
        self.assertEqual(sources[0]["source_type"], "funnel_message")
        self.assertEqual(sources[0]["name"], "Welcome funnel needle: Funnel message needle")
        self.assertEqual(sources[0]["subject"], "Funnel message needle")
        self.assertEqual(sources[0]["editor_type"], "wysiwyg")
        self.assertEqual(sources[0]["source_funnel_id"], funnel["id"])
        self.assertEqual(sources[0]["source_funnel_name"], "Welcome funnel needle")
        self.assertEqual(sources[0]["source_label"], "Funnel: Welcome funnel needle")
        self.assertEqual(sources[0]["sequence_label"], "After 1 days")
        self.assertNotIn("rawText", sources[0])
        self.assertNotIn("parts", sources[0])
        self.assertNotIn("bodyStyle", sources[0])
        self.assertNotIn("messages", sources[0])
        self.assertNotIn("funnel", sources[0])
        self.assertNotIn("data", sources[0])

    def test_email_copy_sources_exclude_cross_account_sources(self):
        target = self.create_automation()
        other = self.create_automation()
        other_email = self.create_email(other["id"], name="Cross account source")
        self.db.execute(
            "update automation_emails set cid = %s where id = %s",
            "other-account-cid",
            other_email["id"],
        )

        try:
            sources = self.user_get(
                "/api/automations/%s/email-copy-sources" % target["id"]
            )
            self.assertNotIn(other_email["id"], [item["source_id"] for item in sources])
        finally:
            self.db.execute(
                "delete from automation_emails where id = %s and cid = %s",
                other_email["id"],
                "other-account-cid",
            )
            self.created_email_ids.remove(other_email["id"])

    def test_email_copy_sources_exclude_cross_account_transactional_templates(self):
        target = self.create_automation()
        template = self.create_txn_template(name="Cross account txn source")
        self.db.execute(
            "update txntemplates set cid = %s where id = %s",
            "other-account-cid",
            template["id"],
        )

        try:
            sources = self.user_get(
                "/api/automations/%s/email-copy-sources?source_filter=transactional_templates"
                % target["id"]
            )
            self.assertNotIn(template["id"], [item["source_id"] for item in sources])
        finally:
            self.db.execute(
                "delete from txntemplates where id = %s and cid = %s",
                template["id"],
                "other-account-cid",
            )
            self.created_txn_template_ids.remove(template["id"])

    def test_email_copy_sources_exclude_cross_account_broadcasts(self):
        target = self.create_automation()
        campaign = self.create_campaign(name="Cross account broadcast source")
        self.db.execute(
            "update campaigns set cid = %s where id = %s",
            "other-account-cid",
            campaign["id"],
        )

        try:
            sources = self.user_get(
                "/api/automations/%s/email-copy-sources?source_filter=broadcasts"
                % target["id"]
            )
            self.assertNotIn(campaign["id"], [item["source_id"] for item in sources])
        finally:
            self.db.execute(
                "delete from campaigns where id = %s and cid = %s",
                campaign["id"],
                "other-account-cid",
            )
            self.created_campaign_ids.remove(campaign["id"])

    def test_email_copy_sources_exclude_cross_account_and_inconsistent_funnel_messages(self):
        target = self.create_automation()
        funnel, message = self.create_funnel_message(
            funnel_overrides={"name": "Cross account funnel source"},
            message_overrides={"subject": "Cross account funnel message"},
        )
        inconsistent_funnel, inconsistent = self.create_funnel_message(
            funnel_overrides={"name": "Inconsistent funnel source", "messages": []},
            message_overrides={"subject": "Inconsistent funnel message"},
        )
        self.db.execute(
            "update messages set cid = %s where id = %s",
            "other-account-cid",
            message["id"],
        )

        try:
            sources = self.user_get(
                "/api/automations/%s/email-copy-sources?source_filter=funnel_messages"
                % target["id"]
            )
            source_ids = [item["source_id"] for item in sources]
            self.assertNotIn(message["id"], source_ids)
            self.assertNotIn(inconsistent["id"], source_ids)
        finally:
            self.db.execute(
                "delete from messages where id = %s and cid = %s",
                message["id"],
                "other-account-cid",
            )
            self.created_message_ids.remove(message["id"])

    def test_email_copy_sources_exclude_message_with_unowned_funnel(self):
        target = self.create_automation()
        funnel, message = self.create_funnel_message(
            funnel_overrides={"name": "Unowned linked funnel"},
            message_overrides={"subject": "Message linked to unowned funnel"},
        )
        self.db.execute(
            "update funnels set cid = %s where id = %s",
            "other-account-cid",
            funnel["id"],
        )

        try:
            sources = self.user_get(
                "/api/automations/%s/email-copy-sources?source_filter=funnel_messages"
                % target["id"]
            )
            self.assertNotIn(message["id"], [item["source_id"] for item in sources])

            result = self.simulate_post(
                "/api/automations/%s/emails/from-source" % target["id"],
                json={"source_type": "funnel_message", "source_id": message["id"]},
                headers=self.headers(),
            )
            self.assertEqual(result.status_code, 403)
        finally:
            self.db.execute(
                "delete from funnels where id = %s and cid = %s",
                funnel["id"],
                "other-account-cid",
            )
            self.created_funnel_ids.remove(funnel["id"])

    def test_create_email_from_automation_email_source_preserves_supported_fields(self):
        target = self.create_automation()
        source_automation = self.create_automation()
        source = self.create_email(
            source_automation["id"],
            name="Source email",
            subject="Source subject",
            preheader="Source preheader",
            type="wysiwyg",
            rawText="<h1>Source body</h1>",
            parts=[{"type": "text", "value": "hello"}],
            bodyStyle={"background": "#fff"},
            fromname="Sender",
            fromemail="from@example.com",
            replyto="reply@example.com",
            returnpath="bounce@example.com",
        )
        self.db.execute(
            """
            update automation_emails
            set data = data || %s
            where id = %s and cid = %s
            """,
            {
                "send_log_id": "do-not-copy",
                "stats": {"sent": 99},
                "automation_email_id": "do-not-copy",
            },
            source["id"],
            self.user_cookie["cid"],
        )

        copied = self.user_post(
            "/api/automations/%s/emails/from-source" % target["id"],
            json={"source_type": "automation_email", "source_id": source["id"]},
        )
        self.created_email_ids.append(copied["id"])

        self.assertNotEqual(copied["id"], source["id"])
        self.assertEqual(copied["automation_id"], target["id"])
        self.assertEqual(copied["name"], "Copy of Source email")
        self.assertEqual(copied["subject"], "Source subject")
        self.assertEqual(copied["preheader"], "Source preheader")
        self.assertEqual(copied["type"], "wysiwyg")
        self.assertEqual(copied["rawText"], "<h1>Source body</h1>")
        self.assertEqual(copied["parts"], [{"type": "text", "value": "hello"}])
        self.assertEqual(copied["bodyStyle"], {"background": "#fff"})
        self.assertEqual(copied["fromname"], "Sender")
        self.assertEqual(copied["fromemail"], "from@example.com")
        self.assertEqual(copied["replyto"], "reply@example.com")
        self.assertEqual(copied["returnpath"], "bounce@example.com")
        self.assertNotEqual(copied["created"], source["created"])
        self.assertNotEqual(copied["modified"], source["modified"])
        self.assertNotIn("send_log_id", copied)
        self.assertNotIn("stats", copied)

        fetched = self.user_get(
            "/api/automations/%s/emails/%s" % (target["id"], copied["id"])
        )
        self.assertEqual(fetched["id"], copied["id"])

        type_change = self.simulate_patch(
            "/api/automations/%s/emails/%s" % (target["id"], copied["id"]),
            json={"type": "raw"},
            headers=self.headers(),
        )
        self.assertEqual(type_change.status_code, 400)
        self.assertIn("editor type is fixed", type_change.text)

    def test_create_email_from_transactional_template_preserves_whitelisted_fields(self):
        target = self.create_automation()
        template = self.create_txn_template(
            name="Transactional source",
            subject="Transactional subject",
            preheader="Transactional preheader",
            type="beefree",
            rawText='{"html":"<p>Txn</p>","json":{}}',
            parts=[{"type": "image", "src": "example"}],
            bodyStyle={"background": "#eee"},
            fromname="Txn Sender",
            fromemail="sender@example.com",
            replyto="reply@example.com",
            returnpath="bounce@example.com",
            tag="api-tag",
            route="do-not-copy",
            stats={"sent": 10},
            template="do-not-copy",
            example=True,
            test_send_metadata={"to": "test@example.com"},
            arbitrary_metadata={"nested": "do-not-copy"},
        )

        copied = self.user_post(
            "/api/automations/%s/emails/from-source" % target["id"],
            json={"source_type": "transactional_template", "source_id": template["id"]},
        )
        self.created_email_ids.append(copied["id"])

        self.assertEqual(copied["automation_id"], target["id"])
        self.assertEqual(copied["name"], "Copy of Transactional source")
        self.assertEqual(copied["subject"], "Transactional subject")
        self.assertEqual(copied["preheader"], "Transactional preheader")
        self.assertEqual(copied["type"], "beefree")
        self.assertEqual(copied["rawText"], '{"html":"<p>Txn</p>","json":{}}')
        self.assertEqual(copied["parts"], [{"type": "image", "src": "example"}])
        self.assertEqual(copied["bodyStyle"], {"background": "#eee"})
        self.assertEqual(copied["fromname"], "Txn Sender")
        self.assertEqual(copied["fromemail"], "sender@example.com")
        self.assertEqual(copied["replyto"], "reply@example.com")
        self.assertEqual(copied["returnpath"], "bounce@example.com")
        self.assertNotEqual(copied["id"], template["id"])
        self.assertNotIn("tag", copied)
        self.assertNotIn("route", copied)
        self.assertNotIn("stats", copied)
        self.assertNotIn("template", copied)
        self.assertNotIn("example", copied)
        self.assertNotIn("test_send_metadata", copied)
        self.assertNotIn("arbitrary_metadata", copied)

        type_change = self.simulate_patch(
            "/api/automations/%s/emails/%s" % (target["id"], copied["id"]),
            json={"type": "raw"},
            headers=self.headers(),
        )
        self.assertEqual(type_change.status_code, 400)

    def test_create_email_from_broadcast_preserves_whitelisted_fields(self):
        target = self.create_automation()
        campaign = self.create_campaign(
            name="Broadcast source",
            subject="Broadcast source subject",
            preheader="Broadcast source preheader",
            type="wysiwyg",
            rawText="<h1>Broadcast body</h1>",
            parts=[{"type": "text", "value": "body"}],
            bodyStyle={"background": "#abc"},
            fromname="Broadcast Sender",
            fromemail="sender@example.com",
            replyto="reply@example.com",
            returnpath="bounce@example.com",
            lists=["do-not-copy"],
            segments=["do-not-copy"],
            tags=["do-not-copy"],
            supplists=["do-not-copy"],
            suppsegs=["do-not-copy"],
            supptags=["do-not-copy"],
            when="schedule",
            scheduled_for="2026-08-16T12:00:00Z",
            sent_at="2026-08-16T12:30:00Z",
            started=True,
            finished_at="2026-08-16T12:35:00Z",
            canceled=True,
            route="do-not-copy",
            delivered=10,
            send=10,
            soft=1,
            hard=1,
            opened=2,
            clicked=3,
            bounced=1,
            complained=1,
            unsubscribed=1,
            resendsubject="do-not-copy",
            resendpreheader="do-not-copy",
            linkurls=["https://example.com"],
            linkclicks=[1],
            image="do-not-copy",
            archive_key="do-not-copy",
            openaddtags=["do-not-copy"],
            openremtags=["do-not-copy"],
            clickaddtags=["do-not-copy"],
            clickremtags=["do-not-copy"],
            sendaddtags=["do-not-copy"],
            sendremtags=["do-not-copy"],
            disableopens=True,
            arbitrary_metadata={"nested": "do-not-copy"},
        )

        copied = self.user_post(
            "/api/automations/%s/emails/from-source" % target["id"],
            json={"source_type": "broadcast", "source_id": campaign["id"]},
        )
        self.created_email_ids.append(copied["id"])

        self.assertEqual(copied["automation_id"], target["id"])
        self.assertEqual(copied["name"], "Copy of Broadcast source")
        self.assertEqual(copied["subject"], "Broadcast source subject")
        self.assertEqual(copied["preheader"], "Broadcast source preheader")
        self.assertEqual(copied["type"], "wysiwyg")
        self.assertEqual(copied["rawText"], "<h1>Broadcast body</h1>")
        self.assertEqual(copied["parts"], [{"type": "text", "value": "body"}])
        self.assertEqual(copied["bodyStyle"], {"background": "#abc"})
        self.assertEqual(copied["fromname"], "Broadcast Sender")
        self.assertEqual(copied["fromemail"], "sender@example.com")
        self.assertEqual(copied["replyto"], "reply@example.com")
        self.assertEqual(copied["returnpath"], "bounce@example.com")
        self.assertNotEqual(copied["id"], campaign["id"])

        for field in (
            "lists",
            "segments",
            "tags",
            "supplists",
            "suppsegs",
            "supptags",
            "when",
            "scheduled_for",
            "sent_at",
            "started",
            "finished_at",
            "canceled",
            "route",
            "delivered",
            "send",
            "soft",
            "hard",
            "opened",
            "clicked",
            "bounced",
            "complained",
            "unsubscribed",
            "resendsubject",
            "resendpreheader",
            "linkurls",
            "linkclicks",
            "image",
            "archive_key",
            "openaddtags",
            "openremtags",
            "clickaddtags",
            "clickremtags",
            "sendaddtags",
            "sendremtags",
            "disableopens",
            "arbitrary_metadata",
        ):
            self.assertNotIn(field, copied)

        type_change = self.simulate_patch(
            "/api/automations/%s/emails/%s" % (target["id"], copied["id"]),
            json={"type": "raw"},
            headers=self.headers(),
        )
        self.assertEqual(type_change.status_code, 400)

    def test_create_email_from_funnel_message_preserves_whitelisted_fields_and_sender_metadata(self):
        target = self.create_automation()
        funnel, message = self.create_funnel_message(
            funnel_overrides={
                "name": "Copy funnel",
                "route": "do-not-copy",
                "tags": ["do-not-copy"],
                "exittags": ["do-not-copy"],
                "count": 99,
            },
            message_overrides={
                "subject": "Funnel copy subject",
                "preheader": "Funnel copy preheader",
                "type": "beefree",
                "rawText": '{"html":"<p>Funnel</p>","json":{}}',
                "parts": [{"type": "image", "src": "example"}],
                "bodyStyle": {"background": "#ddd"},
            },
            meta_overrides={
                "fromname": "Meta Sender",
                "returnpath": "meta-bounce@example.com",
                "fromemail": "meta-from@example.com",
                "replyto": "meta-reply@example.com",
                "whennum": 3,
                "whentype": "hours",
                "unpublished": True,
                "msgroute": "do-not-copy",
                "arbitrary_meta": "do-not-copy",
            },
        )

        copied = self.user_post(
            "/api/automations/%s/emails/from-source" % target["id"],
            json={"source_type": "funnel_message", "source_id": message["id"]},
        )
        self.created_email_ids.append(copied["id"])

        self.assertEqual(copied["automation_id"], target["id"])
        self.assertEqual(copied["name"], "Copy of Copy funnel: Funnel copy subject")
        self.assertEqual(copied["subject"], "Funnel copy subject")
        self.assertEqual(copied["preheader"], "Funnel copy preheader")
        self.assertEqual(copied["type"], "beefree")
        self.assertEqual(copied["rawText"], '{"html":"<p>Funnel</p>","json":{}}')
        self.assertEqual(copied["parts"], [{"type": "image", "src": "example"}])
        self.assertEqual(copied["bodyStyle"], {"background": "#ddd"})
        self.assertEqual(copied["fromname"], "Meta Sender")
        self.assertEqual(copied["returnpath"], "meta-bounce@example.com")
        self.assertEqual(copied["fromemail"], "meta-from@example.com")
        self.assertEqual(copied["replyto"], "meta-reply@example.com")

        for field in (
            "funnel",
            "initialize",
            "days",
            "dayoffset",
            "who",
            "supplists",
            "supptags",
            "suppsegs",
            "openaddtags",
            "openremtags",
            "clickaddtags",
            "clickremtags",
            "sendaddtags",
            "sendremtags",
            "delivered",
            "send",
            "soft",
            "hard",
            "opened",
            "clicked",
            "opened_all",
            "clicked_all",
            "unsubscribed",
            "complained",
            "bounced",
            "linkurls",
            "linkclicks",
            "arbitrary_metadata",
            "source_funnel_id",
            "source_funnel_name",
            "whennum",
            "whentype",
            "unpublished",
            "msgroute",
            "arbitrary_meta",
            "route",
            "tags",
            "exittags",
            "count",
        ):
            self.assertNotIn(field, copied)

        type_change = self.simulate_patch(
            "/api/automations/%s/emails/%s" % (target["id"], copied["id"]),
            json={"type": "raw"},
            headers=self.headers(),
        )
        self.assertEqual(type_change.status_code, 400)

    def test_create_email_from_funnel_message_missing_sender_metadata_uses_empty_strings(self):
        target = self.create_automation()
        _, message = self.create_funnel_message(
            funnel_overrides={"name": "No sender funnel"},
            message_overrides={"subject": "No sender message"},
            meta_overrides={
                "fromname": "",
                "returnpath": "",
                "fromemail": "",
                "replyto": "",
            },
        )

        copied = self.user_post(
            "/api/automations/%s/emails/from-source" % target["id"],
            json={"source_type": "funnel_message", "source_id": message["id"]},
        )
        self.created_email_ids.append(copied["id"])

        self.assertEqual(copied["fromname"], "")
        self.assertEqual(copied["returnpath"], "")
        self.assertEqual(copied["fromemail"], "")
        self.assertEqual(copied["replyto"], "")

    def test_create_email_from_source_rejects_cross_account_and_unsupported_source(self):
        target = self.create_automation()
        source_automation = self.create_automation()
        source = self.create_email(source_automation["id"], name="Other account source")
        self.db.execute(
            "update automation_emails set cid = %s where id = %s",
            "other-account-cid",
            source["id"],
        )

        try:
            cross_account = self.simulate_post(
                "/api/automations/%s/emails/from-source" % target["id"],
                json={"source_type": "automation_email", "source_id": source["id"]},
                headers=self.headers(),
            )
            unsupported = self.simulate_post(
                "/api/automations/%s/emails/from-source" % target["id"],
                json={"source_type": "form_template", "source_id": source["id"]},
                headers=self.headers(),
            )

            self.assertEqual(cross_account.status_code, 403)
            self.assertEqual(unsupported.status_code, 400)
        finally:
            self.db.execute(
                "delete from automation_emails where id = %s and cid = %s",
                source["id"],
                "other-account-cid",
            )
            self.created_email_ids.remove(source["id"])

    def test_create_email_from_transactional_template_rejects_cross_account(self):
        target = self.create_automation()
        template = self.create_txn_template(name="Other account txn source")
        self.db.execute(
            "update txntemplates set cid = %s where id = %s",
            "other-account-cid",
            template["id"],
        )

        try:
            cross_account = self.simulate_post(
                "/api/automations/%s/emails/from-source" % target["id"],
                json={"source_type": "transactional_template", "source_id": template["id"]},
                headers=self.headers(),
            )

            self.assertEqual(cross_account.status_code, 403)
        finally:
            self.db.execute(
                "delete from txntemplates where id = %s and cid = %s",
                template["id"],
                "other-account-cid",
            )
            self.created_txn_template_ids.remove(template["id"])

    def test_create_email_from_broadcast_rejects_cross_account(self):
        target = self.create_automation()
        campaign = self.create_campaign(name="Other account broadcast source")
        self.db.execute(
            "update campaigns set cid = %s where id = %s",
            "other-account-cid",
            campaign["id"],
        )

        try:
            cross_account = self.simulate_post(
                "/api/automations/%s/emails/from-source" % target["id"],
                json={"source_type": "broadcast", "source_id": campaign["id"]},
                headers=self.headers(),
            )

            self.assertEqual(cross_account.status_code, 403)
        finally:
            self.db.execute(
                "delete from campaigns where id = %s and cid = %s",
                campaign["id"],
                "other-account-cid",
            )
            self.created_campaign_ids.remove(campaign["id"])

    def test_create_email_from_funnel_message_rejects_cross_account_and_inconsistent_sources(self):
        target = self.create_automation()
        _, cross_account = self.create_funnel_message(
            funnel_overrides={"name": "Other account funnel source"},
            message_overrides={"subject": "Other account funnel message"},
        )
        _, inconsistent = self.create_funnel_message(
            funnel_overrides={"name": "Broken funnel source", "messages": []},
            message_overrides={"subject": "Broken funnel message"},
        )
        self.db.execute(
            "update messages set cid = %s where id = %s",
            "other-account-cid",
            cross_account["id"],
        )

        try:
            cross_result = self.simulate_post(
                "/api/automations/%s/emails/from-source" % target["id"],
                json={"source_type": "funnel_message", "source_id": cross_account["id"]},
                headers=self.headers(),
            )
            inconsistent_result = self.simulate_post(
                "/api/automations/%s/emails/from-source" % target["id"],
                json={"source_type": "funnel_message", "source_id": inconsistent["id"]},
                headers=self.headers(),
            )

            self.assertEqual(cross_result.status_code, 403)
            self.assertEqual(inconsistent_result.status_code, 400)
            self.assertIn("not referenced by its funnel metadata", inconsistent_result.text)
        finally:
            self.db.execute(
                "delete from messages where id = %s and cid = %s",
                cross_account["id"],
                "other-account-cid",
            )
            self.created_message_ids.remove(cross_account["id"])

    def test_default_email_shape(self):
        automation = self.create_automation()

        email = self.user_post(
            "/api/automations/%s/emails" % automation["id"],
            json={},
        )
        self.created_email_ids.append(email["id"])

        self.assertEqual(email["name"], "New automation email")
        self.assertEqual(email["subject"], "Click Here to Edit")
        self.assertEqual(email["type"], "raw")
        self.assertEqual(email["rawText"], "<p>Hello</p>")
        self.assertEqual(email["fromname"], "")
        self.assertEqual(email["fromemail"], "")
        self.assertEqual(email["replyto"], "")
        self.assertEqual(email["returnpath"], "")

    def test_sender_fields_can_be_saved_and_fetched(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        patched = self.user_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={
                "fromname": "  Automation Sender  ",
                "fromemail": "  from@example.com  ",
                "replyto": "  reply@example.com  ",
                "returnpath": "  bounce@example.com  ",
            },
        )

        self.assertEqual(patched["fromname"], "Automation Sender")
        self.assertEqual(patched["fromemail"], "from@example.com")
        self.assertEqual(patched["replyto"], "reply@example.com")
        self.assertEqual(patched["returnpath"], "bounce@example.com")

        fetched = self.user_get(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"])
        )
        self.assertEqual(fetched["fromname"], "Automation Sender")
        self.assertEqual(fetched["fromemail"], "from@example.com")
        self.assertEqual(fetched["replyto"], "reply@example.com")
        self.assertEqual(fetched["returnpath"], "bounce@example.com")

    def test_empty_sender_fields_do_not_block_content_edits(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        patched = self.user_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={
                "subject": "Content edit only",
                "rawText": "<p>Edited without sender settings</p>",
            },
        )

        self.assertEqual(patched["subject"], "Content edit only")
        self.assertEqual(patched["rawText"], "<p>Edited without sender settings</p>")
        self.assertEqual(patched["fromname"], "")
        self.assertEqual(patched["returnpath"], "")

    def test_editor_type_is_set_at_creation(self):
        automation = self.create_automation()

        for email_type in ("beefree", "", "wysiwyg", "raw"):
            email = self.user_post(
                "/api/automations/%s/emails" % automation["id"],
                json={"type": email_type},
            )
            self.created_email_ids.append(email["id"])
            self.assertEqual(email["type"], email_type)

    def test_editor_compatible_fields_can_be_saved(self):
        automation = self.create_automation()
        email = self.create_email(
            automation["id"],
            type="beefree",
            rawText='{"page": {"body": {}}}',
        )

        beefree = self.user_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={
                "type": "beefree",
                "rawText": '{"page": {"body": {}}}',
                "parts": [],
                "bodyStyle": {},
            },
        )
        self.assertEqual(beefree["type"], "beefree")
        self.assertEqual(beefree["rawText"], '{"page": {"body": {}}}')

    def test_legacy_editor_fields_can_be_saved(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"], type="")

        legacy = self.user_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={
                "type": "",
                "parts": [{"type": "text"}],
                "bodyStyle": {"version": 3},
            },
        )
        self.assertEqual(legacy["type"], "")
        self.assertEqual(legacy["parts"], [{"type": "text"}])
        self.assertEqual(legacy["bodyStyle"], {"version": 3})

    def test_editor_type_cannot_be_changed_after_creation(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"], type="raw")

        result = self.simulate_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={"type": "wysiwyg"},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("editor type is fixed", result.text)

    def test_invalid_editor_type_is_rejected(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        result = self.simulate_patch(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            json={"type": "broadcast"},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)

    @patch("api.automations.send_backend_mail")
    def test_send_test_email_requires_to_address(self, send_backend_mail):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        result = self.simulate_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={"route": self.route_id()},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        send_backend_mail.assert_not_called()

    @patch("api.automations.check_test_limit")
    @patch("api.automations.send_backend_mail")
    def test_send_test_email_uses_automation_email(self, send_backend_mail, check_test_limit):
        automation = self.create_automation()
        email = self.create_email(
            automation["id"],
            subject="Automation Test Subject",
            rawText="<h1>Automation Test Body</h1>",
        )

        result = self.user_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={"to": "recipient@example.com", "route": self.route_id()},
        )

        self.assertEqual(result, {})
        check_test_limit.assert_called_once()
        send_backend_mail.assert_called_once()
        args = send_backend_mail.call_args[0]
        self.assertEqual(args[1], self.user_cookie["cid"])
        self.assertIn("Automation Test Body", args[3])
        self.assertEqual(args[8], "recipient@example.com")
        self.assertEqual(args[10], "Automation Test Subject")

        user = self.db.users.get(self.user_cookie["uid"])
        self.assertEqual(user["lasttest"]["to"], "recipient@example.com")
        self.assertEqual(user["lasttest"]["route"], self.route_id())

    @patch("api.automations.add_test_txn_log")
    @patch("api.automations.check_test_limit")
    @patch("api.automations.send_backend_mail")
    def test_send_test_email_can_be_included_in_transactional_log(
        self,
        send_backend_mail,
        check_test_limit,
        add_test_txn_log,
    ):
        automation = self.create_automation()
        email = self.create_email(
            automation["id"],
            subject="Logged Automation Test Subject",
        )

        result = self.user_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={
                "to": "recipient@example.com",
                "route": self.route_id(),
                "include_in_log": True,
            },
        )

        self.assertEqual(result, {})
        send_backend_mail.assert_called_once()
        check_test_limit.assert_called_once()
        add_test_txn_log.assert_called_once()
        args = add_test_txn_log.call_args[0]
        self.assertEqual(args[1], self.user_cookie["cid"])
        self.assertEqual(args[2], "recipient@example.com")
        self.assertEqual(args[3], "Logged Automation Test Subject")
        self.assertEqual(args[4], "automation:%s" % automation["id"])
        self.assertEqual(args[8], self.route_id())
        self.assertEqual(add_test_txn_log.call_args[1]["status"], "Sent")

    @patch("api.automations.add_test_txn_log")
    @patch("api.automations.check_test_limit")
    @patch("api.automations.send_backend_mail")
    def test_send_test_email_does_not_log_by_default(
        self,
        send_backend_mail,
        check_test_limit,
        add_test_txn_log,
    ):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        result = self.user_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={"to": "recipient@example.com", "route": self.route_id()},
        )

        self.assertEqual(result, {})
        send_backend_mail.assert_called_once()
        check_test_limit.assert_called_once()
        add_test_txn_log.assert_not_called()

    @patch("api.automations.send_backend_mail")
    def test_send_test_email_rejects_invalid_include_in_log(self, send_backend_mail):
        automation = self.create_automation()
        email = self.create_email(automation["id"])

        result = self.simulate_post(
            "/api/automations/%s/emails/%s/test" % (automation["id"], email["id"]),
            json={
                "to": "recipient@example.com",
                "route": self.route_id(),
                "include_in_log": "yes",
            },
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        send_backend_mail.assert_not_called()

    @patch("api.automations.send_backend_mail")
    def test_send_test_email_requires_email_ownership(self, send_backend_mail):
        first = self.create_automation()
        second = self.create_automation()
        email = self.create_email(first["id"])

        result = self.simulate_post(
            "/api/automations/%s/emails/%s/test" % (second["id"], email["id"]),
            json={"to": "recipient@example.com", "route": self.route_id()},
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)
        send_backend_mail.assert_not_called()

    def test_email_endpoints_require_automation_ownership(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])
        self.db.execute(
            "update automations set cid = %s where id = %s",
            "other-account-cid",
            automation["id"],
        )

        listed = self.simulate_get(
            "/api/automations/%s/emails" % automation["id"],
            headers=self.headers(),
        )
        fetched = self.simulate_get(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(listed.status_code, 403)
        self.assertEqual(fetched.status_code, 403)
        self.db.execute(
            "delete from automation_emails where id = %s and cid = %s",
            email["id"],
            self.user_cookie["cid"],
        )
        self.db.execute(
            "delete from automations where id = %s and cid = %s",
            automation["id"],
            "other-account-cid",
        )

    def test_email_must_belong_to_automation(self):
        first = self.create_automation()
        second = self.create_automation()
        email = self.create_email(first["id"])

        result = self.simulate_get(
            "/api/automations/%s/emails/%s" % (second["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 403)

    def test_delete_rejects_draft_reference(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])
        self.db.automations.patch(
            automation["id"],
            {
                "draft": {
                    "nodes": [
                        {
                            "id": "node_send_email_1",
                            "type": "send_email",
                            "label": "Send email",
                            "automation_email_id": email["id"],
                        }
                    ]
                }
            },
        )

        result = self.simulate_delete(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("referenced by draft step 1", result.text)

    def test_delete_rejects_published_reference(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])
        self.db.automations.patch(
            automation["id"],
            {
                "published": {
                    "nodes": [
                        {
                            "id": "node_send_email_1",
                            "type": "send_email",
                            "label": "Send email",
                            "automation_email_id": email["id"],
                        }
                    ]
                }
            },
        )

        result = self.simulate_delete(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("referenced by published step 1", result.text)

    def test_delete_rejects_draft_email_engagement_condition_reference(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])
        self.db.automations.patch(
            automation["id"],
            {
                "draft": {
                    "nodes": [
                        {
                            "id": "node_if_opened_email_1",
                            "type": "if_opened_email",
                            "label": "If opened email",
                            "automation_email_id": email["id"],
                            "yes_node_id": "node_exit_1",
                            "no_node_id": "node_exit_1",
                        },
                        {
                            "id": "node_exit_1",
                            "type": "exit",
                            "label": "Exit automation",
                        },
                    ]
                }
            },
        )

        result = self.simulate_delete(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("referenced by draft step 1", result.text)
        self.assertIn("If opened email", result.text)

    def test_delete_rejects_published_email_engagement_condition_reference(self):
        automation = self.create_automation()
        email = self.create_email(automation["id"])
        self.db.automations.patch(
            automation["id"],
            {
                "published": {
                    "nodes": [
                        {
                            "id": "node_if_clicked_email_1",
                            "type": "if_clicked_email",
                            "label": "If clicked email",
                            "automation_email_id": email["id"],
                            "yes_node_id": "node_exit_1",
                            "no_node_id": "node_exit_1",
                        },
                        {
                            "id": "node_exit_1",
                            "type": "exit",
                            "label": "Exit automation",
                        },
                    ]
                }
            },
        )

        result = self.simulate_delete(
            "/api/automations/%s/emails/%s" % (automation["id"], email["id"]),
            headers=self.headers(),
        )

        self.assertEqual(result.status_code, 400)
        self.assertIn("referenced by published step 1", result.text)
        self.assertIn("If clicked email", result.text)
