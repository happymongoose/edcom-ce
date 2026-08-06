import shortuuid

import test_base


class TestSegmentContacts(test_base.TestBase):

    def setUp(self):
        super(TestSegmentContacts, self).setUp()
        self.created_emails = []
        self.created_list_ids = []
        self.created_segment_ids = []

    def tearDown(self):
        cid = self.user_cookie["cid"]
        if self.created_emails:
            contact_ids = [
                row[0]
                for row in self.db.execute(
                    f"""select contact_id from contacts."contacts_{cid}" where email = any(%s)""",
                    self.created_emails,
                )
            ]
            if contact_ids:
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
        if self.created_segment_ids:
            self.db.execute(
                "delete from segments where id = any(%s) and cid = %s",
                self.created_segment_ids,
                cid,
            )
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
        super(TestSegmentContacts, self).tearDown()

    def create_contact_list(self):
        suffix = shortuuid.uuid().lower()
        result = self.user_post(
            "/api/lists",
            json={"name": "segment_contacts_%s" % suffix},
        )
        self.created_list_ids.append(result["id"])
        return result

    def add_contact(self, list_id, email):
        self.user_post(
            "/api/lists/%s/feed" % list_id,
            json={
                "email": email,
                "data": {
                    "First Name": "Segment",
                },
            },
        )
        self.created_emails.append(email)

    def create_segment(self, prefix):
        segment = self.user_post(
            "/api/segments",
            json={
                "name": "segment_contacts_%s" % shortuuid.uuid().lower(),
                "operator": "and",
                "parts": [{
                    "type": "Info",
                    "prop": "Email",
                    "operator": "contains",
                    "value": prefix,
                }],
                "subset": False,
                "subsettype": "percent",
                "subsetpct": 10,
                "subsetnum": 2000,
            },
        )
        self.created_segment_ids.append(segment["id"])
        return segment

    def test_segment_contacts_are_paginated_and_searchable(self):
        suffix = shortuuid.uuid().lower()
        prefix = "segment-contacts-%s" % suffix
        contact_list = self.create_contact_list()
        self.add_contact(contact_list["id"], "%s-0@example.com" % prefix)
        self.add_contact(contact_list["id"], "%s-1@example.com" % prefix)
        self.add_contact(contact_list["id"], "segment-contacts-other-%s@example.com" % suffix)
        segment = self.create_segment(prefix)

        first_page = self.user_get(
            "/api/segments/%s/contacts?page=1&page_size=1" % segment["id"]
        )

        assert first_page["segment"]["id"] == segment["id"]
        assert first_page["total"] == 2
        assert first_page["total_pages"] == 2
        assert len(first_page["contacts"]) == 1
        assert set(first_page["contacts"][0].keys()) == {"contact_id", "email", "added"}

        second_page = self.user_get(
            "/api/segments/%s/contacts?page=2&page_size=1" % segment["id"]
        )
        assert len(second_page["contacts"]) == 1
        assert second_page["contacts"][0]["email"] != first_page["contacts"][0]["email"]

        searched = self.user_get(
            "/api/segments/%s/contacts?search=-1@example.com" % segment["id"]
        )
        assert searched["total"] == 1
        assert searched["contacts"][0]["email"] == "%s-1@example.com" % prefix

    def test_missing_segment_contacts_are_forbidden(self):
        result = self.simulate_get(
            "/api/segments/not-a-real-segment/contacts",
            headers={
                "X-Auth-UID": self.user_cookie["uid"],
                "X-Auth-Cookie": self.user_cookie["id"],
            },
        )
        assert result.status_code == 403
