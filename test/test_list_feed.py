import test_base

class TestListFeed(test_base.TestBase):

    def test_feed(self):
        email = 'barbara@petpsychic.com'

        result = self.user_post('/api/lists', json={
            "name": "test_feed"
        })

        assert result['name'].startswith('test_feed')

        lid = result['id']
        cid = result['cid']

        self.user_post(f'/api/lists/{lid}/feed', json={
            'email': email,
            'tags': ['buyer', 'shopper'],
            'data': {
                'First Name': 'Barbara',
                'Last Name': 'Test'
            }
        })

        result = self.user_post(f'/api/lists/{lid}/find', json={
            'operator': 'and',
            'parts': [{
                "type": "Info",
                "prop": "",
                "operator": "contains",
                "value": "",
            }],
            'sort': {
                'id': 'Email',
                'desc': False,
            }
        })

        assert result.get('complete')
        assert {
            k: result['result']['rows'][0][k]
            for k in ('Email', '!!tags', 'First Name', 'Last Name')
        } == {
            'Email': email,
            '!!tags': 'buyer,shopper',
            'First Name': 'Barbara',
            'Last Name': 'Test'
        }

        lst = self.db.lists.get(lid)

        assert lst['count'] == 1
        assert lst['used_properties'] == ['Email', 'First Name', 'Last Name']

        self.user_post(f'/api/lists/{lid}/feed', json={
            'email': email,
            'removetags': ['buyer'],
        })

        result = self.user_post(f'/api/lists/{lid}/find', json={
            'operator': 'and',
            'parts': [{
                "type": "Info",
                "prop": "",
                "operator": "contains",
                "value": "",
            }],
            'sort': {
                'id': 'Email',
                'desc': False,
            }
        })
        assert {
            k: result['result']['rows'][0][k]
            for k in ('Email', '!!tags', 'First Name', 'Last Name')
        } == {
            'Email': email,
            '!!tags': 'shopper',
            'First Name': 'Barbara',
            'Last Name': 'Test'
        }

        self.user_post(f'/api/lists/{lid}/feed', json={
            'email': email,
            'unsubscribe': True
        })

        assert self.db.single("select unsubscribed from unsublogs where cid = %s and email = %s", cid, email) == True
        result = self.user_post(f'/api/lists/{lid}/find', json={
            'operator': 'and',
            'parts': [{
                "type": "Info",
                "prop": "",
                "operator": "contains",
                "value": "",
            }],
            'sort': {
                'id': 'Email',
                'desc': False,
            }
        })
        assert result['result']['rows'][0]['Unsubscribed'] == 'true'

        lst = self.db.lists.get(lid)
        assert lst['unsubscribed'] == 1

        self.user_post(f'/api/lists/{lid}/feed', json={
            'email': email,
            'resubscribe': True
        })

        assert self.db.single("select unsubscribed from unsublogs where cid = %s and email = %s", cid, email) is None
        result = self.user_post(f'/api/lists/{lid}/find', json={
            'operator': 'and',
            'parts': [{
                "type": "Info",
                "prop": "",
                "operator": "contains",
                "value": "",
            }],
            'sort': {
                'id': 'Email',
                'desc': False,
            }
        })
        assert result['result']['rows'][0]['Unsubscribed'] == ''

        lst = self.db.lists.get(lid)
        assert lst['unsubscribed'] == 0

        self.db.execute(
            "insert into unsublogs (cid, email, rawhash, unsubscribed, complained, bounced) values (%s, %s, %s, false, false, true)",
            cid,
            email,
            999999999,
        )
        other_cid = "othercustomer"
        self.db.execute(
            "insert into unsublogs (cid, email, rawhash, unsubscribed, complained, bounced) values (%s, %s, %s, true, false, false)",
            other_cid,
            email,
            999999999,
        )

        self.user_post(f'/api/lists/{lid}/feed', json={
            'email': email,
            'resubscribe': True
        })

        assert self.db.single("select bounced from unsublogs where cid = %s and email = %s", cid, email) is None
        assert self.db.single("select unsubscribed from unsublogs where cid = %s and email = %s", other_cid, email) == True
