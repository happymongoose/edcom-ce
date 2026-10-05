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
        assert first_page["contacts"][0]["added"].endswith("Z")
        assert "1970" not in first_page["contacts"][0]["added"]
        assert self.db.segments.get(segment["id"])["count"] == 2

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

    def test_all_contacts_are_paginated_searchable_and_distinct(self):
        suffix = shortuuid.uuid().lower()
        first_list = self.create_contact_list()
        second_list = self.create_contact_list()
        first_email = "all-contacts-%s-0@example.com" % suffix
        second_email = "all-contacts-%s-1@example.com" % suffix
        orphan_email = "all-contacts-%s-orphan@example.com" % suffix
        self.add_contact(first_list["id"], first_email)
        self.add_contact(first_list["id"], second_email)
        self.add_contact(second_list["id"], first_email)
        self.db.execute(
            f"""insert into contacts."contacts_{self.user_cookie['cid']}" (email, added, props)
                values (%s, 1700000000, %s)
                on conflict (email) do nothing""",
            orphan_email,
            {},
        )
        self.created_emails.append(orphan_email)
        orphan_contact_id = self.db.single(
            f"""select contact_id from contacts."contacts_{self.user_cookie['cid']}" where email = %s""",
            orphan_email,
        )
        self.db.execute(
            f"""insert into contacts."contact_lists_{self.user_cookie['cid']}" (contact_id, list_id)
                values (%s, %s)""",
            orphan_contact_id,
            "deleted-list-%s" % suffix,
        )

        first_page = self.user_get(
            "/api/contacts?page=1&page_size=1&search=all-contacts-%s" % suffix
        )
        assert first_page["total"] == 2
        assert first_page["total_pages"] == 2
        assert len(first_page["contacts"]) == 1
        assert set(first_page["contacts"][0].keys()) == {"contact_id", "email", "name", "added"}
        assert first_page["contacts"][0]["added"].endswith("Z")

        searched = self.user_get(
            "/api/contacts?search=%s" % second_email
        )
        assert searched["total"] == 1
        assert searched["contacts"][0]["email"] == second_email

        # The overview search can also find contacts with no surviving list.
        global_search = self.user_get("/api/contacts?include_unlisted=true&search=" + orphan_email)
        assert global_search["total"] == 1
        assert global_search["contacts"][0]["email"] == orphan_email

    def test_all_contacts_searches_names_across_lists_with_literal_input(self):
        from urllib.parse import quote
        suffix = shortuuid.uuid().lower()
        first, second = self.create_contact_list(), self.create_contact_list()
        for index, contact_list in enumerate((first, second)):
            email = "name-search-%s-%s@example.com" % (suffix, index)
            self.add_contact(contact_list["id"], email)
            self.db.execute(f'''update contacts."contacts_{self.user_cookie['cid']}" set props = %s where email = %s''',
                            {"First Name": "Alice", "Last Name": "O'Neil_" + suffix}, email)
        search = quote(" ALICE O'NEIL_" + suffix.upper() + " ")
        result = self.user_get("/api/contacts?include_unlisted=true&search=" + search)
        assert result["total"] == 2
        assert all(row["name"] == "Alice O'Neil_" + suffix for row in result["contacts"])
        partial = self.user_get("/api/contacts?include_unlisted=true&search=" + quote("o'neil_" + suffix))
        assert partial["total"] == 2
        # SQL wildcard characters are literal input, not a request for everyone.
        assert self.user_get("/api/contacts?search=" + quote("%" + suffix))["total"] == 0

    def test_contact_memberships_include_lists_and_matching_segments(self):
        suffix = shortuuid.uuid().lower()
        prefix = "segment-memberships-%s" % suffix
        contact_list = self.create_contact_list()
        email = "%s@example.com" % prefix
        self.add_contact(contact_list["id"], email)
        matching_segment = self.create_segment(prefix)
        non_matching_segment = self.create_segment("segment-memberships-no-match-%s" % suffix)

        result = self.user_get("/api/contactdata/%s/memberships" % email)

        assert result["email"] == email
        assert [
            item["id"] for item in result["lists"]
        ] == [contact_list["id"]]
        segment_ids = [item["id"] for item in result["segments"]]
        assert matching_segment["id"] in segment_ids
        assert non_matching_segment["id"] not in segment_ids
