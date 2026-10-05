import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch
import shortuuid
import test_base
from api.shared.send import check_send_limit
from api.shared.db import DB
from api import transactional
from api.shared.utils import redis_connect


class FixedTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 29, 12, 30, tzinfo=tz)


class TestTransactionalReserve(unittest.TestCase):
    def setUp(self):
        self.cid = shortuuid.uuid()
        self.company = {'id': self.cid, 'paid': False}
        self.env = patch.dict(os.environ, {'transactional_reserve_percent': '20'})
        self.env.start()
        self.clock = patch('api.shared.send.datetime', FixedTime)
        self.clock.start()
        self.rdb = redis_connect()

    def tearDown(self):
        self.clock.stop()
        self.env.stop()
        keys = list(self.rdb.scan_iter('*' + self.cid + '*'))
        if keys: self.rdb.delete(*keys)

    def send(self, count=1000, transactional=False, throttles=None, route='route', domain='example.invalid'):
        return check_send_limit(self.company, route, domain, throttles or [], count,
                                transactional=transactional)

    def test_each_account_limit_reserves_capacity(self):
        for field in ('minlimit', 'hourlimit', 'daylimit', 'monthlimit'):
            with self.subTest(field=field):
                self.company = {'id': self.cid, field: 100}
                self.assertEqual(self.send(), 80)
                self.assertEqual(self.send(), 0)
                self.assertEqual(self.send(transactional=True), 20)
                self.assertEqual(self.send(transactional=True), 0)
                self.rdb.delete(*list(self.rdb.scan_iter('*' + self.cid + '*')))

    def test_each_domain_limit_and_exact_override(self):
        for field in ('minlimit', 'hourlimit', 'daylimit'):
            with self.subTest(field=field):
                limits = [{'route': 'route', 'domainsparsed': ['*'], field: 10},
                          {'route': 'route', 'domainsparsed': ['example.invalid'], field: 100}]
                self.assertEqual(self.send(throttles=limits), 80)
                self.assertEqual(self.send(transactional=True, throttles=limits), 20)
                self.assertEqual(self.send(transactional=True, throttles=limits), 0)
                self.rdb.delete(*list(self.rdb.scan_iter('*' + self.cid + '*')))

    def test_disabled_unlimited_rounding_and_full_reserve(self):
        self.assertEqual(self.send(), 1000)  # no configured cap creates no artificial cap
        self.company['id'] = shortuuid.uuid()
        extra = self.company['id']
        try:
            self.company['minlimit'] = 3
            self.assertEqual(self.send(), 2)  # round headroom up
            self.assertEqual(self.send(transactional=True), 1)
        finally:
            self.rdb.delete(*list(self.rdb.scan_iter('*' + extra + '*')))
        self.company['id'] = self.cid
        self.company['minlimit'] = 2000
        with patch.dict(os.environ, {'transactional_reserve_percent': '0'}):
            self.assertEqual(self.send(), 1000)
        with patch.dict(os.environ, {'transactional_reserve_percent': '100'}):
            self.assertEqual(self.send(), 0)

    def test_transaction_first_does_not_reclaim_static_headroom(self):
        self.company['minlimit'] = 100
        self.assertEqual(self.send(20, transactional=True), 20)
        self.assertEqual(self.send(), 60)
        self.assertEqual(self.send(), 0)
        self.assertEqual(self.send(transactional=True), 20)

    def test_safety_limits_and_credits_are_not_bypassed(self):
        for restriction in ({'paused': True}, {'banned': True}, {'inreview': True},
                            {'minlimit': 0}, {'trialend': '2020-01-01T00:00:00Z'},
                            {'paid': True}):
            with self.subTest(restriction=restriction):
                self.company = dict(id=self.cid, **restriction)
                self.assertEqual(self.send(transactional=True), 0)
        self.company = {'id': self.cid, 'paid': True, 'minlimit': 100, 'persendlimit': 3}
        self.rdb.set('credits-' + self.cid, 5)
        self.assertEqual(self.send(transactional=True), 3)
        self.assertEqual(self.send(transactional=True), 2)
        self.assertEqual(self.send(transactional=True), 0)

    def test_concurrent_bulk_and_transactional_never_exceed_cap(self):
        self.company['minlimit'] = 100
        # Separate Redis connections per invocation, real WATCH/MULTI contention.
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: self.send(7), range(30)))
        self.assertEqual(sum(results), 80)
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda n: self.send(3, transactional=bool(n % 2)), range(30)))
        self.assertEqual(sum(results), 20)
        self.assertEqual(sum(results[::2]), 0)
        self.assertEqual(self.send(transactional=True), 0)

    def test_reserve_does_not_leak_between_accounts_or_domains(self):
        limits = [{'route': 'route', 'domainsparsed': ['*'], 'minlimit': 100}]
        self.assertEqual(self.send(throttles=limits), 80)
        self.assertEqual(self.send(throttles=limits, domain='other.invalid'), 80)
        self.assertEqual(self.send(transactional=True, throttles=limits), 20)
        self.assertEqual(self.send(throttles=limits, route='other'), 1000)

    def test_invalid_configuration_fails_closed(self):
        for value in ('-1', '101', 'garbage', '1.5'):
            with self.subTest(value=value), patch.dict(os.environ, {'transactional_reserve_percent': value}):
                with self.assertRaises(ValueError): self.send()

    def test_scheduler_admits_transaction_after_bulk_exhausts_its_share(self):
        db = DB()
        self.company.update(admin=False, minlimit=100)
        db.execute('insert into companies (id,data) values (%s,%s)', self.cid, self.company)
        try:
            self.assertEqual(self.send(), 80)
            # The same minute may have repeated bulk attempts: none can spend reserve.
            for _ in range(3): self.assertEqual(self.send(), 0)
            for n in range(3):
                db.execute('insert into txnqueue (cid,route,domain,data) values (%s,%s,%s,%s)',
                           self.cid, 'route', 'example.invalid', {'fixture': n})
            with patch.object(transactional, 'run_task') as dispatch:
                transactional.check_txns()
            calls = [call for call in dispatch.call_args_list if call.args[1]['id'] == self.cid]
            self.assertEqual(len(calls), 3)
            self.assertTrue(all(call.args[0] == transactional.send_txn for call in calls))
            self.assertEqual(db.single('select count(*) from txnqueue where cid=%s', self.cid), 0)
            self.assertEqual(self.send(transactional=True), 17)
        finally:
            db.execute('delete from txnqueue where cid=%s', self.cid)
            db.execute('delete from companies where id=%s', self.cid)
            db.conn.close()

    def test_minute_boundary_restores_headroom_without_bypassing_hour_cap(self):
        self.company.update(minlimit=10, hourlimit=15)
        self.assertEqual(self.send(), 8)
        self.assertEqual(self.send(transactional=True), 2)
        later = FixedTime(2026, 9, 29, 12, 31)
        with patch('api.shared.send.datetime') as clock:
            clock.now.return_value = later
            self.assertEqual(self.send(), 2)  # hour bulk ceiling is 12
            self.assertEqual(self.send(transactional=True), 3)
            self.assertEqual(self.send(transactional=True), 0)  # true hour cap is 15

    def test_account_counters_remain_isolated(self):
        self.company['minlimit'] = 100
        self.assertEqual(self.send(), 80)
        other = dict(self.company, id=shortuuid.uuid())
        try:
            self.assertEqual(check_send_limit(other, 'route', 'example.invalid', [], 1000), 80)
            self.assertEqual(self.send(transactional=True), 20)
            self.assertEqual(check_send_limit(other, 'route', 'example.invalid', [], 1000,
                                             transactional=True), 20)
        finally:
            keys = list(self.rdb.scan_iter('*' + other['id'] + '*'))
            if keys: self.rdb.delete(*keys)
