"""Cross-automation removal: database-only fixtures, never real delivery."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import falcon
import shortuuid
import test_base
import test_automation_cross_enrolment as fixtures
from api import automations as a


class TestCrossAutomationRemoval(test_base.TestBase):
    # Reuse fixture operations, not the enrolment action's test cases.
    cleanup = fixtures.TestCrossAutomationEnrolment.cleanup
    end = fixtures.TestCrossAutomationEnrolment.end
    create = fixtures.TestCrossAutomationEnrolment.create
    enrol = fixtures.TestCrossAutomationEnrolment.enrol
    step = fixtures.TestCrossAutomationEnrolment.step
    state = fixtures.TestCrossAutomationEnrolment.state
    target_rows = fixtures.TestCrossAutomationEnrolment.target_rows
    req = fixtures.TestCrossAutomationEnrolment.req
    headers = fixtures.TestCrossAutomationEnrolment.headers
    new_db = fixtures.TestCrossAutomationEnrolment.new_db
    blocked = fixtures.TestCrossAutomationEnrolment.blocked

    def setUp(self):
        super().setUp()
        self.cid = self.user_cookie['cid']
        self.db.set_cid(self.cid)
        self.ids, self.contacts = [], []
        self.addCleanup(self.cleanup)

    def node(self, target, nid='remove'):
        return {'id': nid, 'type': 'remove_automation', 'label': 'Remove elsewhere', 'automation_id': target}

    def cohort(self, status='ready', following=True):
        target = self.create()
        source = self.create([self.node(target['id'])] + ([self.end()] if following else []))
        source_enrol = self.enrol(source)
        target_enrol = self.enrol(target, source_enrol['contact_email'])
        self.change(target_enrol, {'status': status})
        return source, source_enrol, target, target_enrol

    def change(self, enrolment, data):
        self.db.execute('update automation_enrolments set data=data||%s where cid=%s and id=%s',
                        data, self.cid, enrolment['id'])

    def test_draft_publish_and_exact_target_contract(self):
        target = self.create()
        source = self.create([self.node(target['id'])])
        self.assertEqual(source['published']['nodes'][0]['type'], 'remove_automation')
        for value in ('', source['id'], 'missing', target['id'].swapcase()):
            self.user_patch('/api/automations/'+source['id'], json={'draft': {'nodes': [self.node(value)]}})
            response = self.simulate_post('/api/automations/'+source['id']+'/publish', headers=self.headers())
            self.assertEqual(response.status_code, 400)
        draft = self.create(publish=False)
        self.user_patch('/api/automations/'+source['id'], json={'draft': {'nodes': [self.node(draft['id'])]}})
        self.assertEqual(self.simulate_post('/api/automations/'+source['id']+'/publish', headers=self.headers()).status_code, 400)
        for value in (1, None, [], {}):
            response = self.simulate_patch('/api/automations/'+source['id'],
                json={'draft': {'nodes': [self.node(value)]}}, headers=self.headers())
            self.assertEqual(response.status_code, 400)
        invalid = self.node(target['id']); invalid['mode'] = 'all'
        self.assertEqual(self.simulate_patch('/api/automations/'+source['id'],
            json={'draft': {'nodes': [invalid]}}, headers=self.headers()).status_code, 400)

    def test_all_supported_states_cancel_with_fresh_operational_state_and_provenance(self):
        for status in sorted(a.AutomationEnrolmentCancel.CANCELLABLE_STATUSES):
            with self.subTest(status=status):
                source, source_enrol, target, target_enrol = self.cohort(status)
                operational = {key: 'old' for key in a._retry_clear_patch()}
                operational.update(wait={'remaining_seconds': 600}, wake_at='2099-01-01T00:00:00Z',
                    paused_at='old', resumed_at='old', visited_node_ids=['end'], trigger_depth=2,
                    trigger_correlation_id='correlation', admin_note='keep', migration_events=[{'created': 'old'}])
                self.change(target_enrol, operational)
                before = self.state(target_enrol)
                result = self.step(source, source_enrol)
                after = self.state(target_enrol)
                self.assertEqual(after['status'], 'cancelled')
                self.assertEqual(result['enrolment']['current_node_id'], 'end')
                self.assertEqual(result['enrolment']['status'], 'ready')
                self.assertIsNone(result['enrolment']['claim_token'])
                for key in list(a._claim_clear_patch()) + list(a._retry_clear_patch()) + ['wait', 'wake_at', 'paused_at', 'resumed_at']:
                    self.assertIsNone(after[key], key)
                for key in ('current_node_id', 'created', 'source', 'trigger_depth', 'trigger_correlation_id',
                            'admin_note', 'migration_events', 'visited_node_ids', 'published_revision'):
                    self.assertEqual(after.get(key), before.get(key), key)
                self.assertEqual(after['cancelled_metadata'], {
                    'source': 'automation_action', 'previous_status': status, 'source_automation_id': source['id'],
                    'source_enrolment_id': source_enrol['id'], 'source_node_id': 'remove',
                    'source_step_run_id': result['step_run']['id']})
                self.assertIsNone(after['cancelled_by_uid'])
                self.assertTrue(after['cancelled_at'])
                self.assertEqual(result['step_run']['removed_count'], 1)
                self.assertEqual(result['step_run']['target_enrolment_ids'], [target_enrol['id']])
                self.assertEqual(self.db.single('select count(*) from automation_step_runs where automation_id=%s', target['id']), 0)

    def test_no_target_enrolment_is_successful_noop_and_last_source_step_completes(self):
        target = self.create(); source = self.create([self.node(target['id'])])
        result = self.step(source, self.enrol(source))
        self.assertEqual(result['enrolment']['status'], 'completed')
        self.assertEqual(result['step_run']['reason'], 'no_active_enrolment')
        self.assertEqual(result['step_run']['removed_count'], 0)
        self.assertEqual(self.target_rows(target), [])

    def test_terminal_history_and_other_contacts_and_automations_are_untouched(self):
        source, source_enrol, target, target_enrol = self.cohort()
        history = []
        for status in a.TERMINAL_ENROLMENT_STATUSES:
            data = {'status': status, 'current_node_id': 'historic', 'source': 'manual', 'sent_emails': ['keep']}
            eid = shortuuid.uuid()
            self.db.execute('insert into automation_enrolments (id,cid,automation_id,contact_id,contact_email,data) values (%s,%s,%s,%s,%s,%s)',
                eid, self.cid, target['id'], source_enrol['contact_id'], source_enrol['contact_email'], data)
            history.append((eid, data))
        other_contact = self.enrol(target)
        other_automation = self.create(); other_pass = self.enrol(other_automation, source_enrol['contact_email'])
        other_states = [self.state(other_contact), self.state(other_pass)]
        self.step(source, source_enrol)
        self.assertEqual(self.state(target_enrol)['status'], 'cancelled')
        for eid, data in history: self.assertEqual(self.state({'id': eid}), data)
        self.assertEqual([self.state(other_contact), self.state(other_pass)], other_states)

    def test_multiple_nonterminal_passes_are_cancelled_together_without_email_address_matching(self):
        source, source_enrol, target, target_enrol = self.cohort()
        second = shortuuid.uuid()
        self.db.execute('insert into automation_enrolments (id,cid,automation_id,contact_id,contact_email,data) values (%s,%s,%s,%s,%s,%s)',
            second, self.cid, target['id'], source_enrol['contact_id'], 'old-address@example.invalid',
            {'status': 'held', 'current_node_id': 'end', 'source': 'manual'})
        result = self.step(source, source_enrol)
        self.assertEqual(result['step_run']['removed_count'], 2)
        self.assertEqual({self.state(row)['status'] for row in [target_enrol, {'id': second}]}, {'cancelled'})

    def test_paused_target_cancellation_survives_resume_and_preserves_automation_pause(self):
        source, source_enrol, target, target_enrol = self.cohort()
        self.user_post('/api/automations/'+target['id']+'/pause')
        self.step(source, source_enrol)
        self.assertEqual(self.db.automations.get(target['id'])['status'], 'paused')
        before = self.state(target_enrol)
        self.user_post('/api/automations/'+target['id']+'/resume')
        self.assertEqual(self.state(target_enrol), before)

    def test_source_pause_during_action_preserves_paused_continuation(self):
        source, source_enrol, target, target_enrol = self.cohort()
        commit = a._commit_automation_removal_action
        def pause(*args, **kwargs):
            a.AutomationPause().on_post(self.req(self.db), SimpleNamespace(), source['id'])
            return commit(*args, **kwargs)
        with patch.object(a, '_commit_automation_removal_action', side_effect=pause):
            self.step(source, source_enrol)
        self.assertEqual(self.state(source_enrol)['status'], 'paused_ready')
        self.assertEqual(self.state(target_enrol)['status'], 'cancelled')
        self.user_post('/api/automations/'+source['id']+'/resume')
        self.assertEqual(self.state(source_enrol)['status'], 'ready')

    def test_missing_self_unpublished_and_foreign_targets_fail_closed_at_runtime(self):
        for kind in ('missing', 'self', 'unpublished', 'foreign'):
            with self.subTest(kind=kind):
                source, source_enrol, target, target_enrol = self.cohort()
                before = self.state(target_enrol)
                if kind == 'unpublished': self.db.automations.patch(target['id'], {'status': 'draft'})
                if kind == 'foreign':
                    self.db.execute('update automations set cid=%s where id=%s', 'foreign-removal-test', target['id'])
                try:
                    changed = dict(source['published'])
                    changed['nodes'] = [self.node('missing' if kind == 'missing' else source['id'] if kind == 'self' else target['id'])]
                    self.db.automations.patch(source['id'], {'published': changed})
                    if kind == 'foreign':
                        self.user_patch('/api/automations/'+source['id'], json={'draft': {'nodes': [self.node(target['id'])]}})
                        self.assertEqual(self.simulate_post('/api/automations/'+source['id']+'/publish', headers=self.headers()).status_code, 400)
                    with self.assertRaises(falcon.HTTPError): self.step(source, source_enrol)
                    self.assertEqual(self.state(source_enrol)['status'], 'held')
                    self.assertIsNone(self.state(source_enrol)['claim_token'])
                    self.assertEqual(self.state(target_enrol), before)
                finally:
                    if kind == 'foreign': self.db.execute('update automations set cid=%s where id=%s', self.cid, target['id'])

    def test_active_stale_and_malformed_claims_refuse_without_partial_cancellation(self):
        cases = [
            {'status': 'running', 'claim_token': 'live', 'claimed_at': a._utc_now()},
            {'status': 'running', 'claim_token': 'stale', 'claimed_at': '2000-01-01T00:00:00Z'},
            {'status': 'ready', 'claim_token': 'unexpected'},
            {'status': 'running'}, {'status': 'unknown'}, {'status': None},
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                source, source_enrol, target, target_enrol = self.cohort()
                self.change(target_enrol, metadata); before = self.state(target_enrol)
                with self.assertRaises(falcon.HTTPConflict): self.step(source, source_enrol)
                self.assertEqual(self.state(target_enrol), before)
                self.assertEqual(self.state(source_enrol)['status'], 'held')
                self.assertIsNone(self.state(source_enrol)['claim_token'])

    def test_lost_source_claim_does_not_cancel_target_or_clear_replacement_claim(self):
        source, source_enrol, target, target_enrol = self.cohort()
        before = self.state(target_enrol); commit = a._commit_automation_removal_action
        def steal(*args, **kwargs):
            self.change(source_enrol, {'claim_token': 'new-owner'})
            return commit(*args, **kwargs)
        with patch.object(a, '_commit_automation_removal_action', side_effect=steal):
            with self.assertRaises(falcon.HTTPConflict): self.step(source, source_enrol)
        self.assertEqual(self.state(target_enrol), before)
        self.assertEqual(self.state(source_enrol)['claim_token'], 'new-owner')

    def test_rollback_after_history_or_source_advancement_and_safe_explicit_retry(self):
        for hook in ('_patch_step_run', '_advance_claimed_enrolment'):
            source, source_enrol, target, target_enrol = self.cohort()
            before = self.state(target_enrol); original = getattr(a, hook); fired = []
            def fail(*args, **kwargs):
                result = original(*args, **kwargs)
                if not fired:
                    fired.append(True)
                    raise RuntimeError('injected failure')
                return result
            with patch.object(a, hook, side_effect=fail):
                with self.assertRaises(falcon.HTTPError): self.step(source, source_enrol)
            self.assertEqual(self.state(target_enrol), before)
            self.assertEqual(self.state(source_enrol)['status'], 'held')
            self.assertIsNone(self.state(source_enrol)['claim_token'])
            runs = self.db.execute('select data from automation_step_runs where enrolment_id=%s', source_enrol['id']).fetchall()
            self.assertTrue(all(row[0]['status'] == 'failed' for row in runs))
            self.user_post('/api/automations/'+source['id']+'/pause')
            self.user_post('/api/automations/'+source['id']+'/resume')
            self.step(source, source_enrol)
            self.assertEqual(self.state(target_enrol)['status'], 'cancelled')
            cancelled = self.state(target_enrol)
            self.step(source, source_enrol)
            self.assertEqual(self.state(target_enrol), cancelled)

    def test_real_inflight_target_is_not_interrupted_and_retry_after_finish_succeeds(self):
        wait = {'id': 'wait', 'label': 'Wait', 'type': 'wait_duration', 'duration': {'days': 1, 'hours': 0, 'minutes': 0}}
        target = self.create([wait, self.end()])
        source = self.create([self.node(target['id']), self.end()])
        source_enrol = self.enrol(source); target_enrol = self.enrol(target, source_enrol['contact_email'])
        entered, release = Event(), Event(); original = a._advance_claimed_enrolment
        target_db = self.new_db()
        def block(*args, **kwargs):
            if args[2] == target['id']:
                entered.set()
                if not release.wait(6): raise AssertionError('target not released')
            return original(*args, **kwargs)
        with patch.object(a, '_advance_claimed_enrolment', side_effect=block), ThreadPoolExecutor(1) as pool:
            future = pool.submit(self.step, target, target_enrol, target_db)
            try:
                self.assertTrue(entered.wait(4))
                before = self.state(target_enrol)
                with self.assertRaises(falcon.HTTPConflict): self.step(source, source_enrol)
                self.assertEqual(self.state(target_enrol), before)
            finally: release.set()
            self.assertEqual(future.result(timeout=8)['enrolment']['status'], 'waiting')
        self.user_post('/api/automations/'+source['id']+'/pause')
        self.user_post('/api/automations/'+source['id']+'/resume')
        self.step(source, source_enrol)
        self.assertEqual(self.state(target_enrol)['status'], 'cancelled')
        self.assertIsNone(self.state(target_enrol)['wait'])

    def test_concurrent_enrolment_is_included_when_committed_before_removal_lock(self):
        target = self.create(); source = self.create([self.node(target['id'])]); source_enrol = self.enrol(source)
        worker = self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with self.db.transaction():
                self.db.single('select id from automations where cid=%s and id=%s for update', self.cid, target['id'])
                future = pool.submit(self.step, source, source_enrol, worker)
                self.blocked(worker)
                outcome = a._create_enrolment_for_contact_locked(self.db, self.cid, target['id'], target,
                    source_enrol['contact_id'], source_enrol['contact_email'], 'manual')
            result = future.result(timeout=10)
        self.assertEqual(result['step_run']['removed_count'], 1)
        self.assertEqual(self.state({'id': outcome['enrolment_id']})['status'], 'cancelled')

    def test_concurrent_target_pause_is_rechecked_under_coordination(self):
        source, source_enrol, target, target_enrol = self.cohort()
        worker = self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with self.db.transaction():
                self.db.single('select id from automations where cid=%s and id=%s for update', self.cid, target['id'])
                future = pool.submit(self.step, source, source_enrol, worker); self.blocked(worker)
                a.AutomationPause().on_post(self.req(self.db), SimpleNamespace(), target['id'])
            future.result(timeout=10)
        self.assertEqual(self.db.automations.get(target['id'])['status'], 'paused')
        self.assertEqual(self.state(target_enrol)['status'], 'cancelled')

    def test_repeated_step_guard_prevents_removal_side_effect(self):
        source, source_enrol, target, target_enrol = self.cohort()
        self.change(source_enrol, {'visited_node_ids': ['remove']})
        before = self.state(target_enrol)
        with self.assertRaises(falcon.HTTPError) as caught: self.step(source, source_enrol)
        self.assertEqual(caught.exception.title, 'Automation loop detected')
        self.assertEqual(self.state(target_enrol), before)

    def test_cancellation_rolls_back_if_second_pass_update_fails(self):
        source, source_enrol, target, first = self.cohort()
        second = {'id': shortuuid.uuid()}
        self.db.execute('insert into automation_enrolments (id,cid,automation_id,contact_id,contact_email,data) values (%s,%s,%s,%s,%s,%s)',
            second['id'], self.cid, target['id'], source_enrol['contact_id'], source_enrol['contact_email'],
            {'status': 'held', 'current_node_id': 'end'})
        before = [self.state(first), self.state(second)]
        original = self.db.execute
        changed = []
        def fail(query, *args, **kwargs):
            result = original(query, *args, **kwargs)
            if len(args) == 4 and isinstance(args[0], dict) and args[0].get('status') == 'cancelled':
                changed.append(args[-1])
                if len(changed) == 2: raise RuntimeError('second cancellation failed')
            return result
        with patch.object(self.db, 'execute', side_effect=fail):
            with self.assertRaises(falcon.HTTPError): self.step(source, source_enrol)
        self.assertEqual(len(changed), 2)
        self.assertEqual([self.state(first), self.state(second)], before)
        self.assertEqual(self.state(source_enrol)['status'], 'held')

    def test_new_enrolment_after_removal_follows_existing_reentry_rules(self):
        for reentry in ('once', 'multiple'):
            target = self.create(reentry=reentry)
            source = self.create([self.node(target['id'])])
            source_enrol = self.enrol(source); prior = self.enrol(target, source_enrol['contact_email'])
            self.step(source, source_enrol)
            # Use the existing authoritative helper to distinguish normal skip/new pass.
            outcome = a._create_enrolment_for_contact(self.db, self.cid, target['id'], target,
                source_enrol['contact_id'], source_enrol['contact_email'], 'manual')
            self.assertEqual(outcome['status'], 'skipped' if reentry == 'once' else 'enrolled')
            self.assertEqual(self.state(prior)['status'], 'cancelled')

    def test_concurrent_publish_commits_before_removal_without_using_an_old_target_graph(self):
        source, source_enrol, target, target_enrol = self.cohort()
        worker = self.new_db()
        with ThreadPoolExecutor(1) as pool:
            with self.db.transaction():
                self.db.single('select id from automations where cid=%s and id=%s for update', self.cid, target['id'])
                future = pool.submit(self.step, source, source_enrol, worker); self.blocked(worker)
                # Retain occupied stable ID; this is a normal safe publication.
                self.db.automations.patch(target['id'], {'draft': {'nodes': [dict(self.end(), label='Renamed')]}})
                a.AutomationPublish().on_post(self.req(self.db), SimpleNamespace(), target['id'])
            future.result(timeout=10)
        self.assertEqual(self.db.automations.get(target['id'])['published_revision'], target['published_revision'] + 1)
        self.assertEqual(self.state(target_enrol)['status'], 'cancelled')

    def test_two_opposite_removals_do_not_deadlock_or_steal_each_others_claims(self):
        left = self.create(); right = self.create([self.node(left['id'])])
        self.user_patch('/api/automations/'+left['id'], json={'draft': {'nodes': [self.node(right['id'])]}})
        left = self.user_post('/api/automations/'+left['id']+'/publish')
        first = self.enrol(left); second = self.enrol(right, first['contact_email'])
        # Both actions have reached the commit stage, so each has a real claim.
        from threading import Barrier
        barrier = Barrier(2); original = a._commit_automation_removal_action
        def simultaneous(*args, **kwargs):
            barrier.wait(timeout=6)
            return original(*args, **kwargs)
        with patch.object(a, '_commit_automation_removal_action', side_effect=simultaneous), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.step, left, first, self.new_db()),
                       pool.submit(self.step, right, second, self.new_db())]
            # Depending on which failed claim is released first, both may hold,
            # or the second can safely cancel the now-held first pass.
            for future in futures:
                try: future.result(timeout=10)
                except falcon.HTTPConflict: pass
        for enrolment in (first, second):
            self.assertIn(self.state(enrolment)['status'], ('held', 'cancelled', 'completed'))
            self.assertIsNone(self.state(enrolment)['claim_token'])
