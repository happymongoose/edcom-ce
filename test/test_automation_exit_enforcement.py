"""Exit rules use disposable contacts and database actions only, never delivery."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import falcon
import shortuuid
import test_base
import test_automation_cross_enrolment as fixtures
from api import automations as a
from api import automation_exit_rules as x
from api.shared import contacts


class TestExitEnforcement(test_base.TestBase):
    create = fixtures.TestCrossAutomationEnrolment.create
    enrol = fixtures.TestCrossAutomationEnrolment.enrol
    end = fixtures.TestCrossAutomationEnrolment.end
    step = fixtures.TestCrossAutomationEnrolment.step
    state = fixtures.TestCrossAutomationEnrolment.state
    req = fixtures.TestCrossAutomationEnrolment.req
    new_db = fixtures.TestCrossAutomationEnrolment.new_db
    headers = fixtures.TestCrossAutomationEnrolment.headers

    def setUp(self):
        super().setUp()
        self.cid = self.user_cookie['cid']; self.db.set_cid(self.cid)
        self.ids, self.contacts, self.lists = [], [], []
        self.addCleanup(self.cleanup)
        self.delivery = patch.object(a, 'send_backend_mail', side_effect=AssertionError('Real delivery forbidden'))
        self.delivery.start(); self.addCleanup(self.delivery.stop)

    def cleanup(self):
        self.db.execute('delete from automation_trigger_events where cid=%s and contact_id=any(%s)', self.cid, self.contacts)
        self.db.execute(f'delete from contacts."contact_values_{self.cid}" where contact_id=any(%s)', self.contacts)
        self.db.execute(f'delete from contacts."contact_lists_{self.cid}" where contact_id=any(%s)', self.contacts)
        for lid in self.lists:
            self.db.execute('delete from list_domains where list_id=%s', lid)
            self.db.execute('delete from lists where id=%s and cid=%s', lid, self.cid)
        fixtures.TestCrossAutomationEnrolment.cleanup(self)

    def rules(self, kind='has_tag'):
        return [{'type': kind, 'tags': ['paid']}]

    def configure(self, doc, rules=None):
        # Isolate runtime tests from the separately covered publication contract.
        published = dict(doc['published'], exit_rules=rules if rules is not None else self.rules())
        self.db.automations.patch(doc['id'], {'published': published})
        return self.db.automations.get(doc['id'])

    def change(self, enrol, **values):
        self.db.execute('update automation_enrolments set data=data||%s where cid=%s and id=%s', values,self.cid,enrol['id'])

    def tag(self, enrol, present=True):
        if present:
            self.db.execute(f'''insert into contacts."contact_values_{self.cid}" (contact_id,type,value)
                values (%s,'tag','paid') on conflict do nothing''', enrol['contact_id'])
        else:
            self.db.execute(f'''delete from contacts."contact_values_{self.cid}" where contact_id=%s and type='tag' and value='paid' ''',enrol['contact_id'])

    def event(self, doc, enrol, **extra):
        return {'id': shortuuid.uuid(), 'contact_id': enrol['contact_id'], 'contact_email': enrol['contact_email'],
            'event_type': 'tag_added', 'tag': 'paid', 'depth': 100,
            'source': {'type':'automation','automation_id':doc['id']}, **extra}

    def test_admission_blocks_manual_and_shared_paths_then_restores_eligibility(self):
        doc=self.create(); e=self.enrol(doc); doc=self.configure(doc); self.tag(e)
        result=a._create_enrolment_for_contact(self.db,self.cid,doc['id'],doc,e['contact_id'],e['contact_email'],'manual')
        self.assertEqual(result['reason'],'exit_rule')
        x.process_event(self.db,self.cid,self.event(doc,e))
        self.assertEqual(self.state(e)['status'],'exited')
        self.tag(e,False)
        self.assertEqual(self.state(e)['status'],'exited')
        result=a._create_enrolment_for_contact(self.db,self.cid,doc['id'],doc,e['contact_id'],e['contact_email'],'manual')
        self.assertEqual(result['status'],'enrolled')

    def test_once_only_is_not_overridden_when_tag_removed(self):
        doc=self.create(reentry='once'); e=self.enrol(doc); doc=self.configure(doc); self.tag(e)
        x.process_event(self.db,self.cid,self.event(doc,e)); self.tag(e,False)
        result=a._create_enrolment_for_contact(self.db,self.cid,doc['id'],doc,e['contact_id'],e['contact_email'],'manual')
        self.assertEqual(result['reason'],'once')

    def test_all_unclaimed_states_exit_and_preserve_provenance_and_history(self):
        for status in a.AutomationEnrolmentCancel.CANCELLABLE_STATUSES:
            with self.subTest(status=status):
                doc=self.create(); e=self.enrol(doc); doc=self.configure(doc); self.tag(e)
                self.change(e,status=status,wait={'remaining_seconds':500},wake_at='2099-01-01',retry_count=3,
                    admin_note='keep',migration_events=[{'created':'old'}],trigger_depth=2)
                x.process_event(self.db,self.cid,self.event(doc,e))
                after=self.state(e)
                self.assertEqual(after['status'],'exited')
                self.assertEqual(after['current_node_id'],'end')
                self.assertEqual(after['admin_note'],'keep')
                self.assertEqual(after['migration_events'],[{'created':'old'}])
                self.assertEqual(after['trigger_depth'],2)
                for key in list(a._retry_clear_patch())+list(a._claim_clear_patch())+['wait','wake_at','paused_at']:
                    self.assertIsNone(after[key])
                self.assertEqual(after['exit_metadata']['previous_status'],status)
                self.assertEqual(self.db.single('select count(*) from automation_step_runs where enrolment_id=%s',e['id']),0)

    def test_paused_exit_and_resume_cannot_revive_it(self):
        doc=self.create(); e=self.enrol(doc); self.configure(doc); self.tag(e)
        self.user_post('/api/automations/'+doc['id']+'/pause')
        x.process_event(self.db,self.cid,self.event(doc,e))
        self.assertEqual(self.state(e)['status'],'exited')
        self.user_post('/api/automations/'+doc['id']+'/resume')
        self.assertEqual(self.state(e)['status'],'exited')

    def test_resume_catches_match_even_without_event(self):
        doc=self.create(); e=self.enrol(doc); self.configure(doc)
        self.user_post('/api/automations/'+doc['id']+'/pause'); self.tag(e)
        self.user_post('/api/automations/'+doc['id']+'/resume')
        self.assertEqual(self.state(e)['status'],'exited')

    def test_before_action_does_not_create_step_run_or_side_effect(self):
        doc=self.create([{'id':'tag','type':'add_tag','label':'Must not run','draft_tag':'forbidden'},self.end()])
        e=self.enrol(doc); self.configure(doc); self.tag(e)
        result=self.step(doc,e)
        self.assertEqual(result['enrolment']['status'],'exited'); self.assertIsNone(result['step_run'])
        self.assertFalse(a._contact_has_tag(self.db,self.cid,e['contact_id'],'forbidden'))

    def test_same_automation_depth_suppression_does_not_suppress_exit(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc);self.tag(e)
        a._process_automation_trigger_event(self.db,self.cid,self.event(doc,e))
        self.assertEqual(self.state(e)['status'],'exited')

    def test_event_is_queued_and_processed_even_when_entry_flags_disabled(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc);self.tag(e)
        with patch.dict('os.environ',{'automation_trigger_emission_enabled':'false','automation_triggers_enabled':'false'}):
            eid=contacts.maybe_insert_tag_added_trigger_event(self.db,self.cid,e['contact_email'],e['contact_id'],'paid')
        self.assertTrue(eid)
        result=x.process_pending(self.db,self.cid,1)
        self.assertEqual(result,{'processed':1,'failed':0})
        self.assertEqual(self.state(e)['status'],'exited')
        self.assertEqual(x.process_pending(self.db,self.cid,1)['processed'],0)

    def test_pending_exit_wins_success_failure_and_rule_removal(self):
        for failure in (False,True):
            doc=self.create();e=self.enrol(doc);self.configure(doc)
            self.change(e,status='running',running_status='ready',claim_token='token',claimed_at=a._utc_now())
            self.tag(e); x.process_event(self.db,self.cid,self.event(doc,e))
            self.assertEqual(self.state(e)['claim_token'],'token')
            self.assertEqual(self.state(e)['status'],'running')
            self.configure(doc,[]);self.tag(e,False)
            if failure:
                a._release_run_claim(self.db,self.cid,doc['id'],e['id'],'token','held',a._utc_now(),{'last_error':{'title':'error'}})
            else:
                a._advance_claimed_enrolment(self.db,self.cid,doc['id'],e['id'],'token',{'status':'ready','current_node_id':'wrong'})
            after=self.state(e)
            self.assertEqual(after['status'],'exited');self.assertEqual(after['current_node_id'],'end')
            self.assertIsNone(after['claim_token']);self.assertIsNone(after['last_error'])

    def test_stale_claim_pending_exit_is_not_executed_again(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc);self.tag(e)
        self.change(e,status='running',running_status='ready',claim_token='old',claimed_at='2000-01-01T00:00:00Z')
        x.process_event(self.db,self.cid,self.event(doc,e))
        result=self.step(doc,e)
        self.assertEqual(result['enrolment']['status'],'exited');self.assertIsNone(result['step_run'])

    def test_terminal_and_unrelated_contacts_unchanged_and_duplicate_event_idempotent(self):
        doc=self.create();e=self.enrol(doc);other=self.enrol(doc);self.configure(doc);self.tag(e)
        x.process_event(self.db,self.cid,self.event(doc,e)); first=self.state(e)
        x.process_event(self.db,self.cid,self.event(doc,e));self.assertEqual(first,self.state(e))
        self.assertEqual(self.state(other)['status'],'ready')
        for status in a.TERMINAL_ENROLMENT_STATUSES:
            self.change(e,status=status);before=self.state(e)
            x.process_event(self.db,self.cid,self.event(doc,e));self.assertEqual(before,self.state(e))

    def test_missing_tag_and_never_member_semantics(self):
        doc=self.create();e=self.enrol(doc);doc=self.configure(doc,self.rules('missing_tag'))
        self.assertIsNotNone(x.matching_rule(self.db,self.cid,e['contact_id'],doc['published']))
        self.tag(e);self.assertIsNone(x.matching_rule(self.db,self.cid,e['contact_id'],doc['published']))
        self.tag(e,False);x.process_event(self.db,self.cid,self.event(doc,e,event_type='tag_removed'))
        self.assertEqual(self.state(e)['status'],'exited')

    def test_list_any_none_exact_membership_and_list_events(self):
        doc=self.create();e=self.enrol(doc)
        lists=[self.user_post('/api/lists',json={'name':'Disposable exit rule '+shortuuid.uuid()}) for _ in range(2)]
        self.lists.extend(l['id'] for l in lists)
        rules=[{'type':'in_list','list_ids':self.lists}];doc=self.configure(doc,rules)
        self.assertIsNone(x.matching_rule(self.db,self.cid,e['contact_id'],doc['published']))
        self.db.execute(f'insert into contacts."contact_lists_{self.cid}" (contact_id,list_id) values (%s,%s)',e['contact_id'],self.lists[1])
        self.assertIsNotNone(x.matching_rule(self.db,self.cid,e['contact_id'],doc['published']))
        eid=contacts.maybe_insert_list_joined_trigger_event(self.db,self.cid,e['contact_email'],e['contact_id'],self.lists[1])
        self.assertTrue(eid);x.process_pending(self.db,self.cid,1)
        self.assertEqual(self.state(e)['status'],'exited')
        doc=self.configure(doc,[{'type':'not_in_list','list_ids':self.lists}])
        self.assertIsNone(x.matching_rule(self.db,self.cid,e['contact_id'],doc['published']))
        self.db.execute(f'delete from contacts."contact_lists_{self.cid}" where contact_id=%s',e['contact_id'])
        self.assertIsNotNone(x.matching_rule(self.db,self.cid,e['contact_id'],doc['published']))

    def test_failed_event_rolls_back_exits_and_remains_retryable(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc);self.tag(e)
        eid=contacts.maybe_insert_tag_added_trigger_event(self.db,self.cid,e['contact_email'],e['contact_id'],'paid')
        original=x.process_event
        def fail(*args):
            original(*args);raise RuntimeError('injected after exit')
        with patch.object(x,'process_event',side_effect=fail):
            self.assertEqual(x.process_pending(self.db,self.cid,1)['failed'],1)
        self.assertEqual(self.state(e)['status'],'ready')
        self.assertEqual(self.db.single("select data->>'exit_status' from automation_trigger_events where id=%s",eid),'pending')
        self.db.execute("update automation_trigger_events set data=data-'exit_retry_at' where id=%s",eid)
        self.assertEqual(x.process_pending(self.db,self.cid,1)['processed'],1)
        self.assertEqual(self.state(e)['status'],'exited')

    def test_independent_connection_exit_waits_for_claim_coordination(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc);self.tag(e)
        started=Event()
        def run():
            db=self.new_db()
            try:
                started.set();return x.process_event(db,self.cid,self.event(doc,e))
            finally: db.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with a._locked_automation(self.db,self.cid,doc['id']):
                future=pool.submit(run);self.assertTrue(started.wait(2))
                self.assertFalse(future.done())
                self.change(e,status='running',running_status='ready',claim_token='token',claimed_at=a._utc_now())
            self.assertEqual(future.result(timeout=5),1)
        self.assertEqual(self.state(e)['claim_token'],'token')
        a._advance_claimed_enrolment(self.db,self.cid,doc['id'],e['id'],'token',{'status':'ready'})
        self.assertEqual(self.state(e)['status'],'exited')

    def test_cross_automation_enrolment_exclusion_is_a_skip_and_source_continues(self):
        target=self.create();source=self.create([{'id':'enrol','type':'enrol_automation','label':'Elsewhere','automation_id':target['id']},self.end()])
        e=self.enrol(source);self.configure(target);self.tag(e)
        result=self.step(source,e)
        self.assertEqual(result['step_run']['reason'],'exit_rule')
        self.assertEqual(result['enrolment']['current_node_id'],'end')
        self.assertEqual(self.db.single('select count(*) from automation_enrolments where automation_id=%s',target['id']),0)

    def test_actual_inflight_action_finishes_but_cannot_advance_after_exit_event(self):
        doc=self.create([{'id':'tag','type':'add_tag','label':'In flight','draft_tag':'allowed'},self.end()])
        e=self.enrol(doc);self.configure(doc)
        started,release=Event(),Event();original=a._insert_step_run
        def slow(*args,**kwargs):
            result=original(*args,**kwargs)
            started.set()
            if not release.wait(5): raise RuntimeError('test barrier timeout')
            return result
        def run():
            db=self.new_db()
            try: return self.step(doc,e,db)
            finally: db.close()
        with patch.object(a,'_insert_step_run',side_effect=slow), ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(run)
            try:
                self.assertTrue(started.wait(3));self.tag(e)
                x.process_event(self.db,self.cid,self.event(doc,e))
                self.assertEqual(self.state(e)['status'],'running')
                self.assertTrue(self.state(e)['pending_rule_exit'])
            finally: release.set()
            result=future.result(timeout=5)
        self.assertEqual(result['enrolment']['status'],'exited')
        self.assertEqual(result['enrolment']['current_node_id'],'tag')
        self.assertEqual(result['step_run']['status'],'succeeded')
        with self.assertRaises(falcon.HTTPBadRequest): self.step(doc,e)

    def test_missing_rule_reference_during_finish_releases_claim_to_hold(self):
        doc=self.create();e=self.enrol(doc)
        self.configure(doc,[{'type':'in_list','list_ids':['missing']}])
        self.change(e,status='running',running_status='ready',claim_token='token')
        a._advance_claimed_enrolment(self.db,self.cid,doc['id'],e['id'],'token',{'status':'ready','current_node_id':'next'})
        after=self.state(e)
        self.assertEqual(after['status'],'held');self.assertIsNone(after['claim_token'])
        self.assertEqual(after['current_node_id'],'end');self.assertIn('missing contact list',after['last_error']['description'])

    def test_exit_worker_account_boundary_and_pending_event_retention(self):
        from datetime import datetime, timedelta
        doc=self.create();e=self.enrol(doc);self.configure(doc);self.tag(e)
        eid=contacts.maybe_insert_tag_added_trigger_event(self.db,self.cid,e['contact_email'],e['contact_id'],'paid')
        self.assertEqual(x.process_pending(self.db,'unrelated-account',1)['processed'],0)
        self.assertEqual(self.state(e)['status'],'ready')
        self.db.execute("update automation_trigger_events set ts=%s,data=data||%s where id=%s",datetime.utcnow()-timedelta(days=100),{'status':'processed'},eid)
        a._cleanup_automation_trigger_events_for_account(self.db,self.cid,datetime.utcnow()-timedelta(days=30),100)
        self.assertTrue(self.db.single('select id from automation_trigger_events where id=%s',eid))
        self.assertEqual(x.process_pending(self.db,self.cid,1)['processed'],1)

    def test_manual_endpoint_reports_exclusion_without_creating_enrolment(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc);self.tag(e)
        response=self.simulate_post('/api/automations/'+doc['id']+'/enrolments',json={'email':e['contact_email']},headers=self.headers())
        self.assertEqual(response.status_code,400,response.text)
        self.assertIn('excluded by exit rule',response.text)
        self.assertEqual(self.db.single('select count(*) from automation_enrolments where automation_id=%s',doc['id']),1)

    def test_stale_recovery_finalises_pending_exit_while_paused(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc);self.tag(e)
        self.user_post('/api/automations/'+doc['id']+'/pause')
        self.change(e,status='running',running_status='waiting',claim_token='old',claimed_at='2000-01-01T00:00:00Z',wait={'remaining_seconds':5},wake_at='2000-01-01')
        x.process_event(self.db,self.cid,self.event(doc,e))
        dry=a.recover_stale_automation_enrolment_claims(self.db,self.cid,dry_run=True,automation_id=doc['id'])
        self.assertEqual(dry['matched_count'],1);self.assertEqual(self.state(e)['status'],'running')
        result=a.recover_stale_automation_enrolment_claims(self.db,self.cid,dry_run=False,automation_id=doc['id'])
        self.assertEqual(result['changed_count'],1)
        after=self.state(e);self.assertEqual(after['status'],'exited');self.assertIsNone(after['claim_token'])
        self.assertIsNone(after['wait']);self.assertIsNone(after['pending_rule_exit'])
        self.assertTrue(after['exit_metadata']);self.assertEqual(self.db.automations.get(doc['id'])['status'],'paused')

    def test_membership_change_and_exit_queue_are_atomic_and_noop_safe(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc)
        sql=f'''insert into contacts."contact_values_{self.cid}" (contact_id,type,value)
            values (%s,'tag',%s) on conflict do nothing returning contact_id'''
        args=(self.db,self.cid,'tags','paid','tag_added',sql,e['contact_id'],'paid')
        with self.assertRaisesRegex(RuntimeError,'rollback'):
            with self.db.transaction():
                contacts.execute_exit_rule_change(*args)
                raise RuntimeError('rollback')
        self.assertFalse(a._contact_has_tag(self.db,self.cid,e['contact_id'],'paid'))
        self.assertEqual(self.db.single('select count(*) from automation_trigger_events where contact_id=%s',e['contact_id']),0)
        self.assertEqual(contacts.execute_exit_rule_change(*args),[(e['contact_id'],)])
        self.assertEqual(contacts.execute_exit_rule_change(*args),[])
        event=self.db.single('select data from automation_trigger_events where contact_id=%s',e['contact_id'])
        self.assertEqual(event['status'],'processed');self.assertEqual(event['exit_status'],'pending')
        x.process_pending(self.db,self.cid)
        self.assertEqual(self.state(e)['status'],'exited')

    def test_normal_list_addition_exits_paused_contact_without_entry_events(self):
        doc=self.create();e=self.enrol(doc)
        lid=self.user_post('/api/lists',json={'name':'Disposable exit addition'})['id'];self.lists.append(lid)
        self.configure(doc,[{'type':'in_list','list_ids':[lid]}])
        self.user_post('/api/automations/'+doc['id']+'/pause')
        with patch.object(contacts,'send_webhooks'):
            contacts.feed(self.db,lid,{'Email':e['contact_email']},[])
            contacts.feed(self.db,lid,{'Email':e['contact_email']},[])
        self.assertEqual(self.db.single('select count(*) from automation_trigger_events where contact_id=%s',e['contact_id']),1)
        self.assertEqual(self.state(e)['status'],'paused_ready')
        x.process_pending(self.db,self.cid)
        self.assertEqual(self.state(e)['status'],'exited')

    def test_normal_list_removal_exits_waiting_contact_and_preserves_other_membership(self):
        doc=self.create();e=self.enrol(doc)
        lids=[self.user_post('/api/lists',json={'name':'Disposable exit removal'})['id'] for _ in range(2)]
        self.lists.extend(lids)
        with patch.object(contacts,'send_webhooks'):
            for lid in lids: contacts.feed(self.db,lid,{'Email':e['contact_email']},[])
        self.configure(doc,[{'type':'not_in_list','list_ids':[lids[0]]}])
        self.change(e,status='waiting',wait={'type':'duration'},wake_at='2099-01-01')
        self.assertEqual(contacts.remove_list_contacts(self.db,self.cid,lids[0],[e['contact_email']]),1)
        self.assertEqual(contacts.remove_list_contacts(self.db,self.cid,lids[0],[e['contact_email']]),0)
        x.process_pending(self.db,self.cid)
        self.assertEqual(self.state(e)['status'],'exited')
        self.assertEqual(self.db.single(f'select list_id from contacts."contact_lists_{self.cid}" where contact_id=%s',e['contact_id']),lids[1])

    def test_import_batch_queues_only_new_memberships_without_webhooks(self):
        from io import BytesIO
        import msgpack
        doc=self.create();first=self.enrol(doc);second=self.enrol(doc)
        lid=self.user_post('/api/lists',json={'name':'Disposable exit import'})['id'];self.lists.append(lid)
        self.configure(doc,[{'type':'in_list','list_ids':[lid]}])
        payload=b''.join(msgpack.packb((e['contact_email'],{})) for e in (first,second))
        with patch.object(contacts,'s3_read_stream',side_effect=lambda *args:BytesIO(payload)), patch.object(contacts,'send_webhooks') as webhooks:
            count,domains,stats=contacts.write_rows(self.db,self.cid,lid,'unused','list',False,False)
            self.assertEqual(count,2);self.assertEqual(domains,{'example.invalid':2})
            self.assertEqual(contacts.write_rows(self.db,self.cid,lid,'unused','list',False,False)[0],0)
            webhooks.assert_not_called()
        self.assertEqual(self.db.single('select count(*) from automation_trigger_events where contact_id=any(%s)',[first['contact_id'],second['contact_id']]),2)
        x.process_pending(self.db,self.cid)
        self.assertEqual([self.state(e)['status'] for e in (first,second)],['exited','exited'])

    def test_global_tag_removal_queues_exit_without_entry_or_webhook(self):
        doc=self.create();e=self.enrol(doc);tag='disposable_exit_'+shortuuid.uuid().lower()
        self.db.execute(f'''insert into contacts."contact_values_{self.cid}" (contact_id,type,value)
            values (%s,'tag',%s)''',e['contact_id'],tag)
        configured=self.configure(doc,[{'type':'missing_tag','tags':[tag]}])
        self.assertIsNone(x.matching_rule(self.db,self.cid,e['contact_id'],configured['published']))
        with patch.object(contacts,'send_webhooks') as webhooks:
            contacts.remove_tag_all_bucket(self.cid,0,1,tag)
            webhooks.assert_not_called()
        x.process_pending(self.db,self.cid)
        self.assertEqual(self.state(e)['status'],'exited')

    def test_import_exit_queue_failure_rolls_back_membership_batch(self):
        from io import BytesIO
        import msgpack
        doc=self.create();e=self.enrol(doc)
        lid=self.user_post('/api/lists',json={'name':'Disposable rollback import'})['id'];self.lists.append(lid)
        self.configure(doc,[{'type':'in_list','list_ids':[lid]}])
        payload=msgpack.packb((e['contact_email'],{}))
        with patch.object(contacts,'s3_read_stream',side_effect=lambda *args:BytesIO(payload)), patch.object(contacts,'execute_exit_rule_change',side_effect=RuntimeError('queue failed')):
            with self.assertRaisesRegex(RuntimeError,'queue failed'):
                contacts.write_rows(self.db,self.cid,lid,'unused','list',False,False)
        self.assertEqual(self.db.single(f'select count(*) from contacts."contact_lists_{self.cid}" where list_id=%s',lid),0)
        self.assertEqual(self.state(e)['status'],'ready')

    def test_tag_changes_roll_back_when_required_exit_event_cannot_be_queued(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc)
        with patch.object(contacts,'maybe_insert_tag_added_trigger_event',side_effect=RuntimeError('queue failed')):
            with self.assertRaisesRegex(RuntimeError,'queue failed'):
                contacts.add_tag(self.db,self.cid,e['contact_email'],e['contact_id'],'paid',None,{},{},[])
        self.assertFalse(a._contact_has_tag(self.db,self.cid,e['contact_id'],'paid'))
        self.tag(e)
        with patch.object(contacts,'maybe_insert_tag_removed_trigger_event',side_effect=RuntimeError('queue failed')):
            with self.assertRaisesRegex(RuntimeError,'queue failed'):
                contacts.remove_tag(self.db,self.cid,e['contact_email'],e['contact_id'],'paid',{},[])
        self.assertTrue(a._contact_has_tag(self.db,self.cid,e['contact_id'],'paid'))

    def test_tag_change_does_not_commit_or_reset_its_callers_transaction(self):
        doc=self.create();e=self.enrol(doc);self.configure(doc)
        with self.assertRaisesRegex(RuntimeError,'outer rollback'):
            with self.db.transaction():
                self.change(e,admin_note='must roll back')
                contacts.add_tag(self.db,self.cid,e['contact_email'],e['contact_id'],'paid',None,{},{},[])
                raise RuntimeError('outer rollback')
        self.assertNotIn('admin_note',self.state(e))
        self.assertFalse(a._contact_has_tag(self.db,self.cid,e['contact_id'],'paid'))
        self.assertEqual(self.db.single('select count(*) from automation_trigger_events where contact_id=%s',e['contact_id']),0)

    def test_domain_removal_captures_exit_in_its_membership_statement(self):
        doc=self.create();e=self.enrol(doc)
        lids=[self.user_post('/api/lists',json={'name':'Disposable domain exit'})['id'] for _ in range(2)]
        self.lists.extend(lids)
        with patch.object(contacts,'send_webhooks'):
            for lid in lids: contacts.feed(self.db,lid,{'Email':e['contact_email']},[])
        self.configure(doc,[{'type':'not_in_list','list_ids':[lids[0]]}])
        original=contacts.execute_exit_rule_change
        # Stop after the relevant committed statement: the legacy task's later
        # account-wide orphan cleanup must not touch unrelated test-server data.
        class StopAfterMembership(Exception): pass
        def capture(*args):
            original(*args)
            raise StopAfterMembership()
        with patch.object(contacts,'execute_exit_rule_change',side_effect=capture) as changed, patch.object(contacts.log,'exception'):
            contacts.remove_list_domains_bucket(self.cid,0,1,lids[0],['example.invalid'],'unused')
            self.assertEqual(changed.call_count,1)
        self.assertEqual(self.db.single(f'select count(*) from contacts."contact_lists_{self.cid}" where contact_id=%s and list_id=%s',e['contact_id'],lids[0]),0)
        x.process_pending(self.db,self.cid)
        self.assertEqual(self.state(e)['status'],'exited')

    def test_import_webhook_and_no_rule_paths_preserve_existing_counts(self):
        from io import BytesIO
        import msgpack
        for has_rules in (False,True):
            doc=self.create();e=self.enrol(doc)
            lid=self.user_post('/api/lists',json={'name':'Disposable webhook import'})['id'];self.lists.append(lid)
            if has_rules: self.configure(doc,[{'type':'in_list','list_ids':[lid]}])
            original=self.db.single
            def single(sql,*args):
                return 1 if 'select count(id) from resthooks' in sql else original(sql,*args)
            payload=msgpack.packb((e['contact_email'],{}))
            with patch.object(self.db,'single',side_effect=single), patch.object(contacts,'s3_read_stream',side_effect=lambda *args:BytesIO(payload)), patch.object(contacts,'send_webhooks') as webhooks:
                count,domains,_=contacts.write_rows(self.db,self.cid,lid,'unused','list',False,False)
                self.assertEqual(count,1);self.assertEqual(domains,{'example.invalid':1})
                self.assertEqual(webhooks.call_args[0][2][0]['email'],e['contact_email'])
                self.assertEqual(webhooks.call_count,1)
            self.assertEqual(self.db.single('select count(*) from automation_trigger_events where contact_id=%s',e['contact_id']),int(has_rules))
