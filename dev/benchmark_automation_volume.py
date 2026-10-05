#!/usr/bin/env python3
"""Synthetic 70k cohort benchmark. Run only via run_volume_check.sh.
No SMTP/API delivery nodes. Bulk SQL fixture creation is not an import benchmark.
"""
import concurrent.futures
import json
import os
import sys
import time
from urllib.parse import urlencode
from unittest.mock import patch

if os.environ.get("EDCOM_DISPOSABLE_VOLUME_CHECK") != "1" or os.path.exists("/config/edcom.json"):
    raise SystemExit("Requires disposable benchmark container without application config")
sys.path[:0] = ["/test", "/"]
from test_automation_execution import TestAutomationExecution
from api import automations
from api.shared.db import DB

COUNT = int(os.environ.get("VOLUME_CONTACTS", "70000"))
WORKERS = int(os.environ.get("VOLUME_WORKERS", "4"))
assert 1 <= COUNT <= 100000 and 1 <= WORKERS <= 8
report = {"contacts": COUNT, "workers": WORKERS, "measurements": {}}

def measure(name, call):
    start = time.monotonic()
    result = call()
    elapsed = time.monotonic() - start
    report["measurements"][name] = round(elapsed, 3)
    print(json.dumps({"phase": name, "seconds": round(elapsed, 3)}), flush=True)
    return result

case = TestAutomationExecution()
case.setUp()
db = case.db
cid = case.user_cookie["cid"]
a = case.create_automation(nodes=[
    {"id": "wait_a", "type": "wait_duration", "label": "Wait A", "duration": {"days": 1, "hours": 0, "minutes": 0}},
    {"id": "wait_b", "type": "wait_duration", "label": "Wait B", "duration": {"days": 1, "hours": 0, "minutes": 0}},
    {"id": "end", "type": "exit", "label": "End"}])
path = "/api/automations/" + a["id"]
email, contact_id = case.create_contact(domain="example.invalid")
e = case.enrol(a["id"], email)
template = case.enrolment_data(e["id"])
db.execute("delete from automation_enrolments where id=%s", e["id"])
prefix = "volume-" + a["id"].lower() + "-"

def fixtures():
    db.execute(f"""insert into contacts."contacts_{cid}" (email, added, props)
        select %s || n || '@example.invalid', extract(epoch from now())::bigint,
        jsonb_build_object('First Name', 'Volume', 'Last Name', n::text)
        from generate_series(1,%s) n""", prefix, COUNT)
    db.execute(f"""insert into automation_enrolments (id,cid,automation_id,contact_id,contact_email,data)
        select %s || contact_id, %s, %s, contact_id, email, %s
        from contacts."contacts_{cid}" where email like %s""", prefix,cid,a["id"],template,prefix+'%')
    db.execute('analyze automation_enrolments')
    db.execute(f'analyze contacts."contacts_{cid}"')
measure("bulk_fixture_seed", fixtures)
for term in (prefix+'1@', 'Volume', 'absent-volume-name'):
    result = measure("contact_search_"+term, lambda: case.user_get('/api/contacts?' + urlencode({"search":term,"include_unlisted":"true"})))
    if term == 'Volume': assert result['total'] == COUNT
measure("eligible_100", lambda: automations._eligible_automation_enrolments(db,cid,100,a['id']))
measure("no_impact_preview", lambda: case.user_get(path+'/publish-impact'))
ids = [r[0] for r in db.execute('select id from automation_enrolments where automation_id=%s order by id', a['id'])]

def run_chunk(chunk):
    connection = DB()
    connection.set_cid(cid)
    try:
        for eid in chunk:
            outcome = automations._run_next_automation_enrolment(connection,cid,a['id'],eid,False)
            assert outcome['enrolment']['status'] == 'waiting', outcome
    finally:
        connection.conn.close()

def run_all():
    with patch.object(automations, 'send_backend_mail', side_effect=AssertionError('No delivery permitted')):
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(run_chunk,[ids[i::WORKERS] for i in range(WORKERS)]))
measure("enter_wait_all", run_all)
assert db.single("select count(*) from automation_enrolments where automation_id=%s and data->>'status'='waiting'",a['id']) == COUNT
measure("pause_all", lambda: case.user_post(path+'/pause'))
case.user_patch(path,json={"draft":{"nodes":a['published']['nodes'][1:]}})
impact = measure("occupied_deletion_preview",lambda:case.user_get(path+'/publish-impact'))
print(json.dumps({"impact":impact}),flush=True)
request = {"request_id":"volume-move", "review":impact['review'],"resolutions":{"wait_a":{"action":"move","destination_node_id":"wait_b"}}}
result = measure("migrate_all_paused",lambda:case.user_post(path+'/publish',json=request))
assert db.single("select count(*) from automation_enrolments where automation_id=%s and data->>'status'='paused_ready' and data->>'current_node_id'='wait_b' and (data->'wait' is null or data->'wait'='null'::jsonb)",a['id']) == COUNT
replay = measure("receipt_replay",lambda:case.user_post(path+'/publish',json=request))
assert replay['published_revision'] == result['published_revision']
measure("resume_all",lambda:case.user_post(path+'/resume'))
def drain_scheduler():
    processed = 0
    dispatches = 0
    with patch.dict(os.environ, {"automation_processing_budget_seconds": "10"}), \
            patch.object(automations, 'send_backend_mail', side_effect=AssertionError('No delivery permitted')):
        while processed < COUNT:
            batch = case.process_enrolments_task(a['id'], 100)
            assert batch['failed'] == 0 and batch['processed'] > 0, batch
            processed += batch['processed']
            dispatches += 1
            print(json.dumps({"scheduler_processed":processed,"dispatches":dispatches}),flush=True)
    assert processed == COUNT
    report['scheduler_dispatches'] = dispatches
measure("scheduler_enter_wait_all",drain_scheduler)
assert db.single("select count(*) from automation_enrolments where automation_id=%s and data->>'status'='waiting'",a['id']) == COUNT
# Immediate exit is a separate operation from normal destination execution.
case.user_patch(path,json={"draft":{"nodes":a['published']['nodes'][2:]}})
impact = measure("second_deletion_preview",lambda:case.user_get(path+'/publish-impact'))
result = measure("immediate_exit_all",lambda:case.user_post(path+'/publish',json={"request_id":"volume-exit","review":impact['review'],"resolutions":{"wait_b":{"action":"exit"}}}))
assert db.single("select count(*) from automation_enrolments where automation_id=%s and data->>'status'='exited'",a['id']) == COUNT
assert db.single("select count(*) from automation_step_runs where automation_id=%s",a['id']) == 2 * COUNT
report['database_bytes'] = db.single('select pg_database_size(current_database())')
report['passed'] = True
print(json.dumps(report,indent=2),flush=True)
