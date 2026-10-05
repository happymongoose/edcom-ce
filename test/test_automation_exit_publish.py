"""Publication changes, exits, history and receipts are one transaction."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
import copy
import shortuuid
import test_base
import test_automation_exit_enforcement as fixtures
from api import automations as a
from api import automation_exit_rules as x


class TestExitPublish(test_base.TestBase):
    def setUp(self):
        super().setUp()
        self.cid = self.user_cookie['cid']; self.db.set_cid(self.cid)
        self.ids, self.contacts, self.lists = [], [], []
        self.addCleanup(self.cleanup)
        delivery = patch.object(a, 'send_backend_mail', side_effect=AssertionError('Real delivery forbidden'))
        delivery.start(); self.addCleanup(delivery.stop)

    cleanup = fixtures.TestExitEnforcement.cleanup
    create = fixtures.TestExitEnforcement.create
    enrol = fixtures.TestExitEnforcement.enrol
    end = fixtures.TestExitEnforcement.end
    state = fixtures.TestExitEnforcement.state
    step = fixtures.TestExitEnforcement.step
    tag = fixtures.TestExitEnforcement.tag
    rules = fixtures.TestExitEnforcement.rules
    change = fixtures.TestExitEnforcement.change
    headers = fixtures.TestExitEnforcement.headers
    req = fixtures.TestExitEnforcement.req
    new_db = fixtures.TestExitEnforcement.new_db

    def setup_cohort(self):
        doc=self.create([{'id':'wait','type':'wait_duration','label':'Wait','duration':{'days':1,'hours':0,'minutes':0}},self.end()])
        e=self.enrol(doc);self.tag(e)
        self.user_patch('/api/automations/'+doc['id'],json={'exit_rules':self.rules()})
        return doc,e

    def impact(self,doc):
        return self.user_get('/api/automations/'+doc['id']+'/publish-impact')

    def payload(self,doc):
        return {'request_id':shortuuid.uuid(),'review':self.impact(doc)['review'],'resolutions':{},'accept_exit_rules':True}

    def publish(self,doc,payload):
        return self.user_post('/api/automations/'+doc['id']+'/publish',json=payload)

    def test_all_states_exit_at_publication_with_compact_history_and_pause_preserved(self):
        for status in a.AutomationEnrolmentCancel.CANCELLABLE_STATUSES:
            with self.subTest(status=status):
                doc,e=self.setup_cohort()
                if status.startswith('paused'):
                    self.user_post('/api/automations/'+doc['id']+'/pause')
                self.change(e,status=status,wait={'remaining_seconds':100},wake_at='2099-01-01',retry_count=2,admin_note='keep')
                impact=self.impact(doc)
                self.assertEqual(impact['rule_exits'],{'enrolment_count':1,'states':{status:1}})
                result=self.publish(doc,self.payload(doc));after=self.state(e)
                self.assertEqual(after['status'],'exited');self.assertEqual(after['admin_note'],'keep')
                self.assertIsNone(after['wait']);self.assertIsNone(after['retry_count'])
                self.assertEqual(after['exit_metadata']['source'],'publication')
                self.assertEqual(after['exit_metadata']['published_revision'],2)
                self.assertEqual(after['exit_metadata']['user_id'],self.user_cookie['uid'])
                self.assertEqual(result['publication_receipt']['rule_exit_count'],1)
                self.assertEqual(result['published']['exit_rules'],self.rules())
                self.assertEqual(self.db.single('select count(*) from automation_step_runs where enrolment_id=%s',e['id']),0)
                if status.startswith('paused'):
                    self.assertEqual(result['status'],'paused')
                    self.user_post('/api/automations/'+doc['id']+'/resume')
                    self.assertEqual(self.state(e)['status'],'exited')

    def test_deletion_only_requires_destinations_for_contacts_not_exiting(self):
        doc,e=self.setup_cohort();other=self.enrol(doc)
        self.user_patch('/api/automations/'+doc['id'],json={'draft':{'nodes':[self.end()]}})
        impact=self.impact(doc)
        self.assertEqual(impact['sources'][0]['enrolment_count'],1)
        self.assertEqual(impact['rule_exits']['enrolment_count'],1)
        body=self.payload(doc);body['resolutions']={'wait':{'action':'move','destination_node_id':'end'}}
        result=self.publish(doc,body)
        self.assertEqual(self.state(e)['status'],'exited');self.assertEqual(self.state(e)['current_node_id'],'wait')
        self.assertEqual(self.state(other)['current_node_id'],'end')
        self.assertEqual(result['publication_receipt']['outcomes'][0]['enrolment_count'],1)

    def test_all_deleted_occupants_matching_rules_need_no_migration_choice(self):
        doc,e=self.setup_cohort()
        self.user_patch('/api/automations/'+doc['id'],json={'draft':{'nodes':[self.end()]}})
        self.assertEqual(self.impact(doc)['sources'],[])
        self.publish(doc,self.payload(doc));self.assertEqual(self.state(e)['status'],'exited')

    def test_terminal_history_unchanged_and_counts_are_enrolments(self):
        doc,e=self.setup_cohort()
        terminal=self.enrol(doc);self.tag(terminal);self.change(terminal,status='completed')
        before=self.state(terminal)
        self.publish(doc,self.payload(doc))
        self.assertEqual(self.state(terminal),before)
        self.assertEqual(self.state(e)['status'],'exited')

    def test_requires_acknowledgement_and_review_then_identical_retry_is_idempotent(self):
        doc,e=self.setup_cohort();body=self.payload(doc);before=self.state(e)
        invalid=copy.deepcopy(body);invalid.pop('accept_exit_rules')
        result=self.simulate_post('/api/automations/'+doc['id']+'/publish',json=invalid,headers=self.headers())
        self.assertEqual(result.status_code,409);self.assertEqual(self.state(e),before)
        first=self.publish(doc,body);second=self.publish(doc,body)
        self.assertEqual(first['publication_receipt'],second['publication_receipt'])
        self.assertEqual(second['published_revision'],2)
        invalid=copy.deepcopy(body);invalid['resolutions']={'wait':{'action':'exit'}}
        self.assertEqual(self.simulate_post('/api/automations/'+doc['id']+'/publish',json=invalid,headers=self.headers()).status_code,409)

    def test_changed_counts_apply_current_cohort_and_stale_rules_are_rejected(self):
        doc,e=self.setup_cohort();body=self.payload(doc)
        other=self.enrol(doc);self.tag(other)
        result=self.publish(doc,body);self.assertEqual(result['publication_receipt']['rule_exit_count'],2)
        doc,e=self.setup_cohort();body=self.payload(doc)
        self.user_patch('/api/automations/'+doc['id'],json={'exit_rules':[{'type':'has_tag','tags':['other']}]})
        result=self.simulate_post('/api/automations/'+doc['id']+'/publish',json=body,headers=self.headers())
        self.assertEqual(result.status_code,409);self.assertEqual(self.state(e)['status'],'ready')

    def test_active_and_stale_claims_block_before_any_exit(self):
        for claimed_at in (a._utc_now(),'2000-01-01T00:00:00Z'):
            doc,e=self.setup_cohort();self.change(e,status='running',running_status='ready',claim_token='claim',claimed_at=claimed_at)
            body=self.payload(doc);before=self.state(e)
            self.assertIn('execution_claims',[b['code'] for b in self.impact(doc)['blockers']])
            result=self.simulate_post('/api/automations/'+doc['id']+'/publish',json=body,headers=self.headers())
            self.assertEqual(result.status_code,409);self.assertEqual(self.state(e),before)
            self.assertEqual(self.db.automations.get(doc['id'])['published_revision'],1)

    def test_audit_failure_rolls_back_exits_snapshot_receipt_and_history(self):
        doc,e=self.setup_cohort();body=self.payload(doc);before=self.state(e);automation=self.db.automations.get(doc['id'])
        with patch.object(a,'user_log',side_effect=RuntimeError('injected audit failure')):
            with self.assertRaises(RuntimeError):
                a.AutomationPublish().on_post(self.req(self.db,body),object(),doc['id'])
        self.assertEqual(self.state(e),before);self.assertEqual(self.db.automations.get(doc['id']),automation)

    def test_second_exit_failure_rolls_back_first(self):
        doc,e=self.setup_cohort();other=self.enrol(doc);self.tag(other);body=self.payload(doc)
        original=x.exit_patch;count=[]
        def fail(*args):
            count.append(1)
            if len(count)==2: raise RuntimeError('injected second exit')
            return original(*args)
        with patch.object(x,'exit_patch',side_effect=fail):
            with self.assertRaises(RuntimeError):
                a.AutomationPublish().on_post(self.req(self.db,body),object(),doc['id'])
        self.assertEqual(self.state(e)['status'],'ready');self.assertEqual(self.state(other)['status'],'ready')
        self.assertEqual(self.db.automations.get(doc['id'])['published_revision'],1)

    def test_concurrent_enrolment_uses_new_published_exclusion_after_commit(self):
        doc,e=self.setup_cohort();body=self.payload(doc);started=Event()
        def enrol():
            db=self.new_db()
            try:
                started.set()
                return a._create_enrolment_for_contact(db,self.cid,doc['id'],doc,e['contact_id'],e['contact_email'],'manual')
            finally: db.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with a._locked_automation(self.db,self.cid,doc['id']):
                future=pool.submit(enrol);self.assertTrue(started.wait(2));self.assertFalse(future.done())
                a.AutomationPublish().on_post(self.req(self.db,body),object(),doc['id'])
            self.assertEqual(future.result(timeout=5)['reason'],'exit_rule')
        self.assertEqual(self.state(e)['status'],'exited')

    def assert_coordination_wait(self, pid):
        import time
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if self.db.single("select exists(select 1 from pg_locks where pid=%s and locktype='advisory' and not granted)",pid):
                return
            time.sleep(0.01)
        self.fail('Independent connection did not wait for the exit-publication advisory lock')

    def test_first_rule_publication_waits_for_contact_change_then_reconciles_it(self):
        from api.shared import contacts
        doc=self.create();e=self.enrol(doc)
        self.user_patch('/api/automations/'+doc['id'],json={'exit_rules':self.rules()})
        payload=self.payload(doc);started=Event();worker_pid=[]
        def publish():
            db=self.new_db()
            try:
                with db.transaction():
                    # The connection proxy's protocol PID is not PostgreSQL's PID.
                    worker_pid.append(db.single('select pg_backend_pid()'))
                    started.set();req=self.req(db,payload)
                    a.AutomationPublish().on_post(req,None,doc['id'])
                    return req.context['result']
            finally:db.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.db.transaction():
                contacts.add_tag(self.db,self.cid,e['contact_email'],e['contact_id'],'paid',None,{},{},[])
                future=pool.submit(publish);self.assertTrue(started.wait(2))
                self.assert_coordination_wait(worker_pid[0])
                self.assertFalse(future.done())
                self.assertEqual(self.state(e)['status'],'ready')
            result=future.result(timeout=5)
        self.assertEqual(result['publication_receipt']['rule_exit_count'],1)
        self.assertEqual(self.state(e)['status'],'exited')

    def test_contact_change_waiting_on_publication_emits_against_new_rules(self):
        from api.shared import contacts
        doc=self.create();e=self.enrol(doc)
        self.user_post('/api/automations/'+doc['id']+'/pause')
        self.user_patch('/api/automations/'+doc['id'],json={'exit_rules':self.rules()})
        payload=self.payload(doc);assessed=Event();release=Event();changing=Event();worker_pid=[]
        original=x.cohort
        def cohort(*args):
            result=original(*args);assessed.set()
            if not release.wait(5):raise RuntimeError('test release timeout')
            return result
        def publish():
            db=self.new_db()
            try:
                req=self.req(db,payload);a.AutomationPublish().on_post(req,None,doc['id'])
                return req.context['result']
            finally:db.close()
        def change():
            db=self.new_db()
            try:
                with db.transaction():
                    worker_pid.append(db.single('select pg_backend_pid()'));changing.set()
                    contacts.add_tag(db,self.cid,e['contact_email'],e['contact_id'],'paid',None,{},{},[])
            finally:db.close()
        with ThreadPoolExecutor(max_workers=2) as pool,patch.object(x,'cohort',side_effect=cohort):
            publication=pool.submit(publish)
            try:
                self.assertTrue(assessed.wait(2));mutation=pool.submit(change)
                self.assertTrue(changing.wait(2));self.assert_coordination_wait(worker_pid[0])
                self.assertFalse(mutation.done())
            finally:release.set()
            self.assertEqual(publication.result(timeout=5)['publication_receipt']['rule_exit_count'],0)
            mutation.result(timeout=5)
        self.assertEqual(self.state(e)['status'],'paused_ready')
        x.process_pending(self.db,self.cid)
        self.assertEqual(self.state(e)['status'],'exited')
