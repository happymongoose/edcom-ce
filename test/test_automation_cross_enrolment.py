"""Backend-only cross-automation actions. Fixtures never send email."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import falcon
import shortuuid
import test_base
from api import automations as a
from api.shared.db import DB


class TestCrossAutomationEnrolment(test_base.TestBase):
    def setUp(self):
        super().setUp()
        self.cid = self.user_cookie['cid']
        self.db.set_cid(self.cid)
        self.ids = []
        self.contacts = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for table in ('automation_step_runs', 'automation_enrolments', 'automations'):
            key = 'id' if table == 'automations' else 'automation_id'
            self.db.execute('delete from %s where cid=%%s and %s=any(%%s)' % (table, key), self.cid, self.ids)
        self.db.execute("delete from userlogs where cid=%s and data->>'link_id'=any(%s)", self.cid, self.ids)
        self.db.execute('delete from contacts."contacts_%s" where contact_id=any(%%s)' % self.cid, self.contacts)

    def node(self, target, nid='handoff'):
        return {'id': nid, 'type': 'enrol_automation', 'label': 'Enrol elsewhere', 'automation_id': target}

    def end(self, nid='end'):
        return {'id': nid, 'type': 'exit', 'label': 'Exit'}

    def create(self, nodes=None, reentry='multiple', publish=True):
        doc = self.user_post('/api/automations', json={'name': 'Disposable cross enrolment '+shortuuid.uuid()})
        self.ids.append(doc['id'])
        self.user_patch('/api/automations/'+doc['id'], json={'entry': {'type': 'manual'}, 'reentry': reentry,
            'draft': {'nodes': nodes if nodes is not None else [self.end()]}})
        return self.user_post('/api/automations/'+doc['id']+'/publish') if publish else self.db.automations.get(doc['id'])

    def enrol(self, doc, email=None):
        if email is None:
            email = 'cross-'+shortuuid.uuid().lower()+'@example.invalid'
            self.contacts.append(self.db.single('insert into contacts."contacts_%s" (email,added,props) values (%%s,0,%%s) returning contact_id' % self.cid, email, {}))
        return self.user_post('/api/automations/'+doc['id']+'/enrolments', json={'email': email})

    def step(self, doc, enrol, db=None):
        return a._run_next_automation_enrolment(db or self.db, self.cid, doc['id'], enrol['id'])

    def state(self, enrol):
        return self.db.single('select data from automation_enrolments where cid=%s and id=%s', self.cid, enrol['id'])

    def target_rows(self, target):
        return [a._enrolment_obj(row) for row in self.db.execute('select id,cid,automation_id,contact_id,contact_email,data from automation_enrolments where cid=%s and automation_id=%s', self.cid, target['id']).fetchall()]

    def req(self, db, doc=None):
        return SimpleNamespace(context={'db': db, 'uid': self.user_cookie['uid'], 'admin': False, 'api': False, 'doc': doc})

    def headers(self):
        return {'X-Auth-UID': self.user_cookie['uid'], 'X-Auth-Cookie': self.user_cookie['id']}

    def test_draft_and_publish_contract(self):
        target = self.create()
        source = self.create([self.node(target['id']), self.end()])
        self.assertEqual(source['published']['nodes'][0]['automation_id'], target['id'])
        for invalid in ('', source['id'], 'missing'):
            self.user_patch('/api/automations/'+source['id'], json={'draft': {'nodes': [self.node(invalid)]}})
            result = self.simulate_post('/api/automations/'+source['id']+'/publish', headers=self.headers())
            self.assertEqual(result.status_code, 400)
        unpublished = self.create(publish=False)
        self.user_patch('/api/automations/'+source['id'], json={'draft': {'nodes': [self.node(unpublished['id'])]}})
        self.assertEqual(self.simulate_post('/api/automations/'+source['id']+'/publish', headers=self.headers()).status_code, 400)
        for malformed in (12, None, ['id']):
            result = self.simulate_patch('/api/automations/'+source['id'], json={'draft': {'nodes': [self.node(malformed)]}}, headers=self.headers())
            self.assertEqual(result.status_code, 400)
        extra = self.node(target['id']); extra['unknown'] = True
        self.assertEqual(self.simulate_patch('/api/automations/'+source['id'], json={'draft': {'nodes': [extra]}}, headers=self.headers()).status_code, 400)

    def test_success_provenance_history_and_no_destination_execution(self):
        target = self.create()
        source = self.create([self.node(target['id']), self.end()])
        enrol = self.enrol(source)
        result = self.step(source, enrol)
        child = self.target_rows(target)[0]
        self.assertEqual((child['status'], child['current_node_id']), ('ready', 'end'))
        self.assertEqual(child['source_node_id'], 'handoff')
        self.assertEqual(child['source_enrolment_id'], enrol['id'])
        self.assertEqual(child['trigger_depth'], 1)
        self.assertEqual(child['trigger_correlation_id'], 'automation:'+enrol['id'])
        self.assertEqual(child['cross_automation_visits'], [[source['id'], 'handoff']])
        self.assertEqual(result['step_run']['outcome'], 'enrolled')
        self.assertEqual(result['step_run']['target_enrolment_id'], child['id'])
        self.assertEqual(result['enrolment']['current_node_id'], 'end')
        self.assertIsNone(result['enrolment']['claim_token'])
        self.assertEqual(self.db.single('select count(*) from automation_step_runs where automation_id=%s', target['id']), 0)
        # Retrying after success executes the next source step, not the handoff.
        self.step(source, enrol)
        self.assertEqual(len(self.target_rows(target)), 1)

    def test_last_node_completes_source(self):
        target = self.create(); source = self.create([self.node(target['id'])])
        self.assertEqual(self.step(source, self.enrol(source))['enrolment']['status'], 'completed')

    def test_reentry_skip_preserves_target_state(self):
        for rule, status, reason in [('once', 'completed', 'once'), ('multiple', 'waiting', 'active_pass'),
                                     ('multiple', 'held', 'active_pass'), ('multiple', 'running', 'active_pass')]:
            with self.subTest(rule=rule, status=status):
                target = self.create(reentry=rule); source = self.create([self.node(target['id'])])
                enrol = self.enrol(source); existing = self.enrol(target, enrol['contact_email'])
                self.db.execute('update automation_enrolments set data=data||%s where id=%s', {'status': status, 'wake_at': '2030-01-01T00:00:00Z'}, existing['id'])
                before = self.state(existing)
                result = self.step(source, enrol)
                self.assertEqual(result['step_run']['outcome'], 'skipped')
                self.assertEqual(result['step_run']['reason'], reason)
                self.assertEqual(self.state(existing), before)
                self.assertEqual(result['enrolment']['status'], 'completed')

    def test_multiple_allows_fresh_pass_after_terminal(self):
        target = self.create(); source = self.create([self.node(target['id'])])
        enrol = self.enrol(source); prior = self.enrol(target, enrol['contact_email'])
        self.step(target, prior)
        self.step(source, enrol)
        self.assertEqual(len(self.target_rows(target)), 2)

    def test_paused_target_is_held_until_resume(self):
        target = self.create(); self.user_post('/api/automations/'+target['id']+'/pause')
        source = self.create([self.node(target['id'])]); self.step(source, self.enrol(source))
        child = self.target_rows(target)[0]
        self.assertEqual(child['status'], 'held')
        self.user_post('/api/automations/'+target['id']+'/resume')
        self.assertEqual(self.state(child)['status'], 'ready')

    def test_runtime_target_failures_hold_and_clear_claim(self):
        for mode in ('missing', 'foreign', 'unpublished', 'duplicate'):
            with self.subTest(mode=mode):
                target = self.create(); source = self.create([self.node(target['id'])]); enrol = self.enrol(source)
                if mode == 'foreign':
                    self.db.execute('update automations set cid=%s where id=%s', 'foreign-test', target['id'])
                elif mode == 'missing':
                    self.db.execute('delete from automations where id=%s', target['id'])
                elif mode == 'unpublished': self.db.automations.patch(target['id'], {'published': None})
                else: self.db.automations.patch(target['id'], {'published': {'nodes': [self.end(), self.end()], 'reentry': 'multiple'}})
                try:
                    with self.assertRaises(falcon.HTTPError): self.step(source, enrol)
                    self.assertEqual(self.state(enrol)['status'], 'held')
                    self.assertIsNone(self.state(enrol)['claim_token'])
                    self.assertEqual(self.target_rows(target), [])
                finally:
                    if mode == 'foreign': self.db.execute('update automations set cid=%s where id=%s', self.cid, target['id'])
                if mode == 'foreign':
                    # Publish validation is also account-scoped.
                    self.db.execute('update automations set cid=%s where id=%s', 'foreign-test', target['id'])
                    try:
                        with self.assertRaises(falcon.HTTPError): a._published_snapshot(self.db, source)
                    finally: self.db.execute('update automations set cid=%s where id=%s', self.cid, target['id'])

    def test_depth_and_cross_node_loop_guards(self):
        target = self.create(); source = self.create([self.node(target['id'])])
        enrol = self.enrol(source)
        with patch.dict(os.environ, {'automation_trigger_max_depth': '1'}):
            with self.assertRaises(falcon.HTTPError): self.step(source, enrol)
        self.assertEqual(self.target_rows(target), [])
        self.assertEqual(self.state(enrol)['status'], 'held')
        # A -> B -> A: first source pass is terminal before B returns to it.
        self.user_patch('/api/automations/'+target['id'], json={'draft': {'nodes': [self.node(source['id'])]}})
        self.user_post('/api/automations/'+target['id']+'/publish')
        self.db.execute('update automation_enrolments set data=data||%s where id=%s', {'status': 'ready'}, enrol['id'])
        with patch.dict(os.environ, {'automation_trigger_max_depth': '10'}):
            self.step(source, enrol)
            child = self.target_rows(target)[0]
            self.step(target, child)
            returned = [row for row in self.target_rows(source) if row['id'] != enrol['id']][0]
            with self.assertRaises(falcon.HTTPError) as caught:
                self.step(source, returned)
            self.assertEqual(caught.exception.title, 'Automation loop detected')
            self.assertEqual(self.state(returned)['status'], 'held')
            self.assertEqual(len(self.target_rows(target)), 1)

    def test_equal_node_ids_in_different_automations_are_not_loops(self):
        target = self.create([self.end('handoff')]); source = self.create([self.node(target['id'])])
        self.step(source, self.enrol(source)); child = self.target_rows(target)[0]
        self.assertEqual(self.step(target, child)['enrolment']['status'], 'exited')

    def test_wait_destination_is_not_started_by_handoff(self):
        wait = {'id': 'wait', 'type': 'wait_duration', 'label': 'Wait', 'duration': {'days': 0, 'hours': 0, 'minutes': 5}}
        target = self.create([wait, self.end()]); source = self.create([self.node(target['id'])])
        self.step(source, self.enrol(source)); child = self.target_rows(target)[0]
        self.assertEqual((child['status'], child['current_node_id']), ('ready', 'wait'))
        self.assertNotIn('wake_at', child)
        self.assertNotIn('wait', child)
        self.assertEqual(self.step(target, child)['enrolment']['status'], 'waiting')

    def test_only_elapsed_wait_resets_inherited_visits_not_depth(self):
        for elapsed in (True, False):
            with self.subTest(elapsed=elapsed):
                wait = {'id': 'wait', 'type': 'wait_duration', 'label': 'Wait', 'wait_until': '2020-01-01T00:00:00Z'}
                target = self.create([wait, self.end()]); child = self.enrol(target)
                metadata = {'cross_automation_visits': [[target['id'], 'end']], 'trigger_depth': 2}
                if elapsed:
                    metadata.update(status='waiting', wake_at='2020-01-01T00:00:00Z',
                        wait={'started_at': '2019-12-31T23:55:00Z', 'wait_until': '2020-01-01T00:00:00Z'})
                self.db.execute('update automation_enrolments set data=data||%s where id=%s', metadata, child['id'])
                self.step(target, child)
                self.assertEqual(self.state(child)['trigger_depth'], 2)
                if elapsed:
                    self.assertEqual(self.state(child)['cross_automation_visits'], [])
                    self.assertEqual(self.step(target, child)['enrolment']['status'], 'exited')
                else:
                    # An already-past deadline provides no elapsed delay.
                    with self.assertRaises(falcon.HTTPError) as caught: self.step(target, child)
                    self.assertEqual(caught.exception.title, 'Automation loop detected')

    def test_inherited_repeat_stops_before_tag_side_effect(self):
        target = self.create([{'id': 'tag', 'type': 'add_tag', 'label': 'Tag', 'draft_tag': 'test'}, self.end()])
        child = self.enrol(target)
        self.db.execute('update automation_enrolments set data=data||%s where id=%s',
            {'cross_automation_visits': [[target['id'], 'tag']]}, child['id'])
        with patch.object(a.contacts, 'add_tag', side_effect=AssertionError('must not run')) as action:
            with self.assertRaises(falcon.HTTPError) as caught: self.step(target, child)
        self.assertEqual(caught.exception.title, 'Automation loop detected')
        action.assert_not_called()
        self.assertIsNone(self.state(child)['claim_token'])

    def test_malformed_inherited_visits_fail_closed(self):
        target = self.create(); child = self.enrol(target)
        self.db.execute('update automation_enrolments set data=data||%s where id=%s',
            {'cross_automation_visits': [['bad']]}, child['id'])
        with self.assertRaises(falcon.HTTPError): self.step(target, child)
        self.assertEqual(self.state(child)['status'], 'held')
        self.assertIsNone(self.state(child)['claim_token'])

    def test_explicit_publish_migration_starts_fresh_but_preserves_depth(self):
        wait = {'id': 'wait', 'type': 'wait_duration', 'label': 'Wait', 'duration': {'days': 0, 'hours': 0, 'minutes': 5}}
        target = self.create([wait, self.end()]); child = self.enrol(target)
        self.db.execute('update automation_enrolments set data=data||%s where id=%s',
            {'cross_automation_visits': [[target['id'], 'end']], 'trigger_depth': 2}, child['id'])
        path = '/api/automations/'+target['id']
        self.user_patch(path, json={'draft': {'nodes': [self.end()]}})
        review = self.user_get(path+'/publish-impact')['review']
        self.user_post(path+'/publish', json={'request_id': shortuuid.uuid(), 'review': review,
            'resolutions': {'wait': {'action': 'move', 'destination_node_id': 'end'}}})
        self.assertEqual(self.state(child)['cross_automation_visits'], [])
        self.assertEqual(self.state(child)['trigger_depth'], 2)
        self.assertEqual(self.step(target, child)['enrolment']['status'], 'exited')

    def test_lost_claim_cannot_create_target(self):
        target = self.create(); source = self.create([self.node(target['id'])]); enrol = self.enrol(source)
        commit = a._commit_automation_enrolment_action
        def stolen(*args, **kwargs):
            self.db.execute('update automation_enrolments set data=data||%s where id=%s',
                {'claim_token': 'replacement-owner'}, enrol['id'])
            return commit(*args, **kwargs)
        with patch.object(a, '_commit_automation_enrolment_action', side_effect=stolen):
            with self.assertRaises(falcon.HTTPConflict): self.step(source, enrol)
        self.assertEqual(self.target_rows(target), [])
        self.assertEqual(self.state(enrol)['claim_token'], 'replacement-owner')

    def test_pause_source_after_claim_preserves_paused_continuation(self):
        target = self.create(); source = self.create([self.node(target['id']), self.end()]); enrol = self.enrol(source)
        commit = a._commit_automation_enrolment_action
        def pause(*args, **kwargs):
            a.AutomationPause().on_post(self.req(self.db), SimpleNamespace(), source['id'])
            return commit(*args, **kwargs)
        with patch.object(a, '_commit_automation_enrolment_action', side_effect=pause): self.step(source, enrol)
        self.assertEqual(self.state(enrol)['status'], 'paused_ready')
        self.assertEqual(len(self.target_rows(target)), 1)
        self.user_post('/api/automations/'+source['id']+'/resume')
        self.assertEqual(self.state(enrol)['status'], 'ready')

    def test_source_publish_refuses_active_handoff_claim(self):
        target = self.create(); source = self.create([self.node(target['id'])]); enrol = self.enrol(source)
        observer = self.new_db(); commit = a._commit_automation_enrolment_action
        def publish_during_claim(*args, **kwargs):
            with self.assertRaises(falcon.HTTPConflict):
                a.AutomationPublish().on_post(self.req(observer), SimpleNamespace(), source['id'])
            return commit(*args, **kwargs)
        with patch.object(a, '_commit_automation_enrolment_action', side_effect=publish_during_claim): self.step(source, enrol)
        self.assertEqual(len(self.target_rows(target)), 1)

    def test_transaction_rolls_back_target_history_and_source_advance(self):
        for hook in ('_create_enrolment_for_contact_locked', '_patch_step_run', '_advance_claimed_enrolment'):
            target = self.create(); source = self.create([self.node(target['id']), self.end()]); enrol = self.enrol(source)
            original = getattr(a, hook)
            fired = []
            def fail_after(*args, **kwargs):
                result = original(*args, **kwargs)
                if not fired:
                    fired.append(True)
                    raise RuntimeError('injected transaction failure')
                return result
            with patch.object(a, hook, side_effect=fail_after):
                with self.assertRaises(falcon.HTTPError): self.step(source, enrol)
            self.assertEqual(self.target_rows(target), [])
            state = self.state(enrol)
            self.assertEqual((state['status'], state['current_node_id']), ('held', 'handoff'))
            self.assertIsNone(state['claim_token'])
            runs = self.db.execute('select data from automation_step_runs where enrolment_id=%s', enrol['id']).fetchall()
            self.assertEqual([row[0]['status'] for row in runs], ['failed'])
            self.db.execute('update automation_enrolments set data=data||%s where id=%s', {'status': 'ready'}, enrol['id'])
            self.step(source, enrol)
            self.assertEqual(len(self.target_rows(target)), 1)

    def new_db(self):
        db = DB(); db.set_cid(self.cid)
        original = db.single
        def observed(query, *args, **kwargs):
            if query.startswith('select id from automations') and 'for update' in query:
                # Capture the backend inside the transaction (pooler-safe).
                db.pid = original('select pg_backend_pid()')
                db.execute("set local statement_timeout = '8s'")
            return original(query, *args, **kwargs)
        db.single = observed
        self.addCleanup(db.close)
        return db

    def blocked(self, db):
        until = time.monotonic()+4
        while time.monotonic() < until:
            pid = db.__dict__.get('pid')
            if pid and self.db.single('select pg_backend_pid()=any(pg_blocking_pids(%s))', pid): return
            time.sleep(.01)
        self.fail('Worker did not wait on the held automation lock')

    def test_concurrent_target_publication_uses_new_snapshot(self):
        target = self.create(); source = self.create([self.node(target['id'])]); enrol = self.enrol(source)
        worker = self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with a._locked_automation(self.db, self.cid, target['id']):
                future = pool.submit(self.step, source, enrol, worker)
                self.blocked(worker)
                self.db.automations.patch(target['id'], {'draft': {'nodes': [self.end('new')]}})
                a.AutomationPublish().on_post(self.req(self.db), SimpleNamespace(), target['id'])
            future.result(timeout=10)
        child = self.target_rows(target)[0]
        self.assertEqual((child['current_node_id'], child['published_revision']), ('new', 2))

    def test_concurrent_manual_enrolment_prevents_duplicate(self):
        target = self.create(); source = self.create([self.node(target['id'])]); enrol = self.enrol(source)
        worker = self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with a._locked_automation(self.db, self.cid, target['id']):
                future = pool.submit(self.step, source, enrol, worker); self.blocked(worker)
                a._create_enrolment_for_contact_locked(self.db, self.cid, target['id'], target,
                    enrol['contact_id'], enrol['contact_email'], 'manual')
            result = future.result(timeout=10)
        self.assertEqual(result['step_run']['reason'], 'active_pass')
        self.assertEqual(len(self.target_rows(target)), 1)

    def test_opposite_direction_actions_do_not_deadlock(self):
        left = self.create(); right = self.create([self.node(left['id'])])
        self.user_patch('/api/automations/'+left['id'], json={'draft': {'nodes': [self.node(right['id'])]}})
        left = self.user_post('/api/automations/'+left['id']+'/publish')
        first = self.enrol(left); second = self.enrol(right)
        db1, db2 = self.new_db(), self.new_db()
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.step, left, first, db1), pool.submit(self.step, right, second, db2)]
            for future in futures: self.assertEqual(future.result(timeout=10)['enrolment']['status'], 'completed')
