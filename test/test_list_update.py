import shortuuid

import test_base
from api.shared.contacts import update, add_send
from api.shared.utils import get_os, get_browser, get_device

class TestListUpdate(test_base.TestBase):

    def setUp(self):
        super(TestListUpdate, self).setUp()
        self.test_id = "test_update_%s" % shortuuid.uuid().lower()
        self.created_emails = []
        self.created_list_ids = []
        self.created_campaign_ids = []

    def tearDown(self):
        cid = self.user_cookie["cid"]
        if self.created_campaign_ids:
            self.db.execute(
                "delete from campaigns where id = any(%s) and cid = %s",
                self.created_campaign_ids,
                cid,
            )
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
                    f"""delete from contacts."contact_open_logs_{cid}" where contact_id = any(%s)""",
                    contact_ids,
                )
                self.db.execute(
                    f"""delete from contacts."contact_click_logs_{cid}" where contact_id = any(%s)""",
                    contact_ids,
                )
                self.db.execute(
                    f"""delete from contacts."contact_send_logs_{cid}" where contact_id = any(%s)""",
                    contact_ids,
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
        super(TestListUpdate, self).tearDown()

    def test_update(self):
        result = self.user_post('/api/lists', json={
            "name": self.test_id
        })

        lid = result['id']
        self.created_list_ids.append(lid)

        email = '%s@example.com' % self.test_id
        self.created_emails.append(email)

        self.user_post(f'/api/lists/{lid}/feed', json={
            'email': email,
            'tags': ['buyer', 'shopper'],
            'data': {
                'First Name': 'Ace',
                'Last Name': 'Test'
            }
        })

        camp = self.create_broadcast(lid, '%s 1' % self.test_id)
        camp2 = self.create_broadcast(lid, '%s 2' % self.test_id)
        camp3 = self.create_broadcast(lid, '%s 3' % self.test_id)
        self.created_campaign_ids.extend([camp['id'], camp2['id'], camp3['id']])

        add_send(self.db, camp['id'], [email])
        self.update(email, 'open', camp['id'], 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:101.0) Gecko/20100101 Firefox/101.0')
        self.update(email, 'click', camp['id'], 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:101.0) Gecko/20100101 Firefox/101.0', 2)

        add_send(self.db, camp2['id'], [email])
        self.update(email, 'open', camp2['id'], 'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36')

        self.update(email, 'bounce', camp3['id'])

        lst = self.db.lists.get(lid)

        assert lst['count'] == 1
        assert lst['active30'] == 1
        assert lst['active60'] == 1
        assert lst['active90'] == 1
        assert 'Opened' in lst['used_properties']
        assert 'Clicked' in lst['used_properties']
        assert 'Bounced' in lst['used_properties']
        assert lst['bounced'] == 1

        self.find(lid, {
            "type": "Responses",
            "action": "opened",
            "timetype": "anytime",
            "timenum": 1,
            "timestart": "",
            "timeend": ""
        }, 1)
        self.find(lid, {
            "type": "Responses",
            "action": "clicked",
            "timetype": "anytime",
            "timenum": 1,
            "timestart": "",
            "timeend": "",
            "broadcast": camp['id'],
            "linkindex": 2,
        }, 1)
        self.find(lid, {
            "type": "Responses",
            "action": "clicked",
            "timetype": "anytime",
            "timenum": 1,
            "timestart": "",
            "timeend": "",
            "broadcast": camp2['id'],
            "linkindex": 2,
        }, 0)
        self.find(lid, {
            "type": "Responses",
            "action": "sent",
            "broadcast": camp['id'],
        }, 1)
        self.find(lid, {
            "type": "Responses",
            "action": "sent",
            "broadcast": camp3['id'],
        }, 0)
        self.find(lid, {
            "type": "Responses",
            "action": "from",
            "fromtype": "browser",
            "frombrowser": "1"
        }, 1)
        self.find(lid, {
            "type": "Responses",
            "action": "from",
            "fromtype": "browser",
            "frombrowser": "5"
        }, 0)
        self.find(lid, {
            "type": "Responses",
            "action": "from",
            "fromtype": "os",
            "fromos": "1"
        }, 1)
        self.find(lid, {
            "type": "Responses",
            "action": "from",
            "fromtype": "device",
            "fromdevice": "3"
        }, 1)
        self.find(lid, {
            "type": "Responses",
            "action": "from",
            "fromtype": "region",
            "fromregion": "California"
        }, 1)
        self.find(lid, {
            "type": "Responses",
            "action": "from",
            "fromtype": "country",
            "fromcountry": "United States of America"
        }, 1)
        self.find(lid, {
            "type": "Responses",
            "action": "from",
            "fromtype": "zip",
            "fromzip": "99999"
        }, 1)
        row = self.find(lid, {
            "type": "Info",
            "test": "tag",
            "tag": "buyer"
        }, 1)

        assert row['Clicked'] == 'true'
        assert row['Opened'] == 'true'
        assert row['Bounced'] == 'true'

    def create_broadcast(self, lid, name):
        return self.user_post('/api/broadcasts', json={
            'name': name,
            'when': 'draft',
            'tags': [],
            'lists': [lid],
            'segments': [],
            'supplists': [],
            'suppsegs': [],
            'supptags': [],
            'subject': 'test',
            'fromname': 'test',
            'fromemail': '',
            'returnpath': 'test',
            'replyto': '',
            'rawText': '',
            'type': 'raw',
            'parts': [],
            'bodyStyle': {}
        })

    def find(self, lid, query, count):
        result = self.user_post(f'/api/lists/{lid}/find', json={
            'operator': 'and',
            'parts': [query],
            'sort': {
                'id': 'Email',
                'desc': False,
            }
        })
        assert len(result['result']['rows']) == count

        if len(result['result']['rows']):
            return result['result']['rows'][0]

    def update(self, email, ct, c, agent=None, linkindex=None):
        upd = {
            'email': email,
            'cmd': ct,
            'campid': c,
        }
        if ct == 'click' and linkindex >= 0:
            upd['updatedts'] = None
            upd['linkindex'] = linkindex

        if agent:
            agentl = agent.lower()
            upd['os'] = get_os(agentl)
            upd['browser'] = get_browser(agentl)
            upd['device'] = get_device(agentl)
            upd['country'] = 'United States of America'
            upd['region'] = 'California'
            upd['zip'] = '99999'

        update(self.db, self.user_cookie['cid'], upd)
