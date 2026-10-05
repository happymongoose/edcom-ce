import base64
import json
import logging
import subprocess
import sys
import uuid
import unittest
from unittest.mock import Mock, patch

import test_base  # Establish the repository test import path.
from api.shared import webhook_inbox as inbox
from api.shared.utils import redis_connect
from api.shared.db import DB
from api import events


class TestWebhookInbox(unittest.TestCase):
    def setUp(self):
        self.redis = redis_connect()
        self.prefix = 'test-inbox-' + uuid.uuid4().hex + ':'
        self.constants = patch.multiple(inbox, PENDING=self.prefix+'pending',
            PROCESSING=self.prefix+'processing', HELD=self.prefix+'held',
            STATE_PREFIX=self.prefix+'state:')
        self.constants.start()
        self.raw = b'{"type":"ses","fixture":1}'
        self.log = logging.getLogger('inbox-test')

    def tearDown(self):
        keys = list(self.redis.scan_iter(self.prefix+'*'))
        if keys:
            self.redis.delete(*keys)
        self.constants.stop()

    def run_queue(self, handler, cancel=lambda:False):
        inbox.consume(self.redis,handler,cancel,self.log)

    def held(self):
        return [json.loads(x) for x in self.redis.lrange(inbox.HELD,0,-1)]

    def test_success_receipt_and_exact_duplicate(self):
        self.redis.lpush(inbox.PENDING,self.raw,b'{"fixture": 1, "type": "ses"}')
        handler = Mock()
        self.run_queue(handler)
        self.assertEqual(handler.call_count,1)
        self.assertEqual(self.redis.llen(inbox.PROCESSING),0)
        self.assertEqual(self.redis.get(inbox.state_key(self.raw)),b'done')
        self.assertGreater(self.redis.ttl(inbox.state_key(self.raw)),0)

    def test_failure_retained_no_repeated_effects(self):
        self.redis.lpush(inbox.PENDING,self.raw,self.raw)
        effects=[]
        def partial(obj):
            effects.append(obj)
            raise RuntimeError('partial side effect')
        self.run_queue(partial)
        self.assertEqual(len(effects),1)
        self.assertEqual(len(self.held()),1)
        self.assertEqual(base64.b64decode(self.held()[0]['payload_base64']),self.raw)
        self.assertEqual(self.redis.ttl(inbox.state_key(self.raw)),-1)

    def test_interruption_retains_claim_and_restart_holds(self):
        self.redis.lpush(inbox.PENDING,self.raw)
        with self.assertRaises(KeyboardInterrupt):
            self.run_queue(Mock(side_effect=KeyboardInterrupt))
        self.assertEqual(self.redis.llen(inbox.PROCESSING),1)
        handler=Mock()
        self.run_queue(handler)
        handler.assert_not_called()
        self.assertEqual(self.held()[0]['reason'],'interrupted_outcome_unknown')

    def test_after_effect_before_ack_is_not_replayed(self):
        self.redis.lpush(inbox.PENDING,self.raw)
        handler=Mock()
        with patch.object(inbox,'acknowledge',side_effect=ConnectionError):
            with self.assertRaises(ConnectionError): self.run_queue(handler)
        self.run_queue(handler)
        self.assertEqual(handler.call_count,1)
        self.assertEqual(len(self.held()),1)

    def test_cancel_before_claim(self):
        self.redis.lpush(inbox.PENDING,self.raw)
        self.run_queue(Mock(),lambda:True)
        self.assertEqual(self.redis.llen(inbox.PENDING),1)

    def test_bad_envelopes_do_not_block_good_event(self):
        self.redis.lpush(inbox.PENDING,b'not json',b'[]',b'{"type":"unknown"}',self.raw)
        handler=Mock(); self.run_queue(handler)
        self.assertEqual(handler.call_count,1)
        self.assertEqual(len(self.held()),3)

    def test_distinct_account_envelopes_not_deduplicated(self):
        handler=Mock()
        for account in ('a','b'):
            self.redis.lpush(inbox.PENDING,json.dumps({'type':'mg','usercid':account}))
        self.run_queue(handler)
        self.assertEqual(handler.call_count,2)

    def test_done_processing_copy_is_acknowledged_on_restart(self):
        self.redis.lpush(inbox.PROCESSING,self.raw)
        self.redis.set(inbox.state_key(self.raw),'done')
        handler=Mock(); self.run_queue(handler)
        handler.assert_not_called()
        self.assertEqual(self.held(),[])
        self.assertEqual(self.redis.llen(inbox.PROCESSING),0)

    def test_independent_connection_excludes_second_consumer(self):
        connection=DB()
        try:
            self.assertTrue(connection.single('select pg_try_advisory_lock(%s,%s)',*inbox.LOCK))
            self.redis.lpush(inbox.PENDING,self.raw)
            with patch.object(events,'process_ses_webhook') as handler:
                events.process_webhooks(lambda:False)
                handler.assert_not_called()
            self.assertEqual(self.redis.llen(inbox.PENDING),1)
        finally:
            connection.single('select pg_advisory_unlock(%s,%s)',*inbox.LOCK)
            connection.close()
        with patch.object(events,'process_ses_webhook') as handler:
            events.process_webhooks(lambda:False)
            handler.assert_called_once()

    def test_real_handler_partial_db_effect_is_not_replayed(self):
        # An autocommitted effect survives the exception: transport must hold it.
        connection=DB()
        key=uuid.uuid4().hex
        connection.execute('create table if not exists test_inbox_effects (id text primary key, n int)')
        connection.execute('insert into test_inbox_effects values (%s,0)',key)
        def handler(db,obj):
            db.execute('update test_inbox_effects set n=n+1 where id=%s',key)
            raise RuntimeError('after commit')
        try:
            self.redis.lpush(inbox.PENDING,self.raw)
            with patch.object(events,'process_ses_webhook',side_effect=handler):
                events.process_webhooks(lambda:False)
                self.redis.lpush(inbox.PENDING,self.raw)
                events.process_webhooks(lambda:False)
            self.assertEqual(connection.single('select n from test_inbox_effects where id=%s',key),1)
        finally:
            connection.execute('delete from test_inbox_effects where id=%s',key)
            connection.close()

    def test_process_death_releases_lock_and_retains_event(self):
        self.redis.lpush(inbox.PENDING,self.raw)
        code = """
import os, sys
from api.shared.db import DB
from api.shared.utils import redis_connect
from api.shared.webhook_inbox import LOCK
connection = DB()
assert connection.single('select pg_try_advisory_lock(%s,%s)', *LOCK)
assert redis_connect().rpoplpush(sys.argv[1], sys.argv[2]) is not None
os._exit(23)
"""
        result = subprocess.run([sys.executable,'-c',code,inbox.PENDING,inbox.PROCESSING],cwd='/',timeout=20)
        self.assertEqual(result.returncode,23)
        with patch.object(events,'process_ses_webhook') as handler:
            events.process_webhooks(lambda:False)
            handler.assert_not_called()
        self.assertEqual(len(self.held()),1)

    def test_graceful_cancel_finishes_claim_before_stopping(self):
        self.redis.lpush(inbox.PENDING,self.raw,b'{"type":"ses","fixture":2}')
        called=[]
        self.run_queue(lambda obj:called.append(obj),lambda:bool(called))
        self.assertEqual(len(called),1)
        self.assertEqual(self.redis.llen(inbox.PENDING),1)
        self.assertEqual(self.redis.llen(inbox.PROCESSING),0)

    def test_late_completion_cannot_release_a_recovery_hold(self):
        self.redis.lpush(inbox.PROCESSING,self.raw)
        inbox.recover(self.redis)
        inbox.acknowledge(self.redis,self.raw)
        self.assertEqual(self.redis.get(inbox.state_key(self.raw)),b'held')
        self.assertEqual(self.redis.ttl(inbox.state_key(self.raw)),-1)
        self.assertEqual(len(self.held()),1)
