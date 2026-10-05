#!/usr/bin/env python3
"""Real Celery/default-queue baseline; only run via run_queue_baseline.sh.
Fake Velocity accepts/fetches recipients but cannot deliver mail. No production config.
"""
import collections
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen
from unittest.mock import patch

if os.environ.get('EDCOM_DISPOSABLE_VOLUME_CHECK') != '1' or Path('/config/edcom.json').exists():
    raise SystemExit('Disposable container required')
sys.path[:0] = ['/test', '/']
from test_base import TestBase
from api import campaigns, events, lists
from api.shared.tasks import tasks
from api.shared.utils import gather_init, gather_check, MPDictReader, redis_connect
from api.shared.s3 import s3_write, s3_delete_all

COUNT = int(os.environ.get('VOLUME_CONTACTS', '70000'))
DELAY = float(os.environ.get('BASELINE_DELAY', '2'))
assert 1 <= COUNT <= 100000 and 0 <= DELAY <= 10
os.environ.pop('SYNC_TASKS', None)
os.environ['development'] = ''
os.environ['webroot'] = 'http://127.0.0.1:8081'
SPLIT = os.environ.get('interactive_task_queue', '').lower() in ('true', '1')
QUEUE_KEYS = tuple(q + suffix for q in ('celery', 'interactive') for suffix in ('', ':3', ':6', ':9'))
report = {'split_queues': SPLIT, 'contacts': COUNT, 'worker_concurrency': 2, 'fake_http_delay_seconds': DELAY}
case = TestBase(); case.setUp()
db = case.db
cid = case.user_cookie['cid']
rdb = redis_connect()
received = collections.Counter()
requests_seen = []
submitted = {}
metrics = []
stop_metrics = threading.Event()
metric_errors = []
monitor_thread = None
fetch_errors = []
active = 0
lock = threading.Lock()

class Sink(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if not self.path.startswith('/transfer/') or '..' in self.path:
            self.send_error(404); return
        path = Path(os.environ['s3_transferbucket']) / self.path[len('/transfer/'):]
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404); return
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        global active
        obj = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/settings':
            self.send_response(200); self.end_headers(); return
        if self.path != '/send-lists':
            self.send_error(404); return
        with lock:
            active += 1
            requests_seen.append(obj['sendid'])
        # Hold the actual sending task, demonstrating non-preemptible occupied slots.
        time.sleep(DELAY)
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        def fetch():
            global active
            try:
                time.sleep(.1)  # deliberately fetch after HTTP acceptance, like Velocity
                for url in obj['listurls']:
                    assert url.startswith('http://127.0.0.1:8081/transfer/'), url
                    with urlopen(url, timeout=10) as response:
                        rows = list(MPDictReader(io.BytesIO(response.read())))
                    with lock:
                        for row in rows:
                            assert row['Email'].endswith('@example.invalid')
                            received[row['Email']] += 1
            except Exception as exc:
                fetch_errors.append(str(exc))
            finally:
                with lock: active -= 1
        threading.Thread(target=fetch, daemon=True).start()

server = ThreadingHTTPServer(('127.0.0.1', 8081), Sink)
threading.Thread(target=server.serve_forever, daemon=True).start()
worker = None
interactive_worker = None
log = open('/logs/queue-worker.log', 'w')

def start_worker(interactive=False):
    name = 'interactive' if interactive else 'bulk'
    queue = 'interactive' if interactive else 'celery'
    concurrency = 1 if SPLIT else 2
    return subprocess.Popen(['celery', '-A', 'api.app.tasks', 'worker', '--loglevel=WARNING',
        '--concurrency='+str(concurrency), '--queues='+queue, '--hostname='+name+'@%h',
        '--without-gossip', '--without-mingle'],
        cwd='/', stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy())

def wait_for(check, label, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result: return result
        if interactive_worker is not None and interactive_worker.poll() is not None:
            raise AssertionError('Interactive worker exited during ' + label)
        if worker is not None and worker.poll() is not None:
            raise AssertionError('Worker exited during ' + label)
        time.sleep(.1)
    raise AssertionError('Timeout: ' + label)

def monitor():
    from api.shared.db import DB
    connection = DB()
    try:
        while not stop_metrics.wait(1):
            queued = []
            for key in QUEUE_KEYS:
                queued.extend(json.loads(x)['headers']['id'] for x in rdb.lrange(key,0,-1))
            ages = [time.monotonic()-submitted[x] for x in queued if x in submitted]
            rss = 0
            for status in Path('/proc').glob('[0-9]*/status'):
                try:
                    for line in status.read_text().splitlines():
                        if line.startswith('VmRSS:'): rss += int(line.split()[1])*1024
                except (FileNotFoundError, ProcessLookupError): pass
            metrics.append({'queued':len(queued),'oldest_measured_send_seconds':round(max(ages,default=0),3),
                'container_process_rss_sum':rss,
                'db_waiters':connection.single("select count(*) from pg_stat_activity where wait_event_type='Lock'"),
                'transfer_files':sum(1 for p in Path(os.environ['s3_transferbucket']).rglob('*') if p.is_file())})
    except Exception as exc:
        metric_errors.append(str(exc))
    finally:
        connection.conn.close()

def query(legacy=False):
    gid = gather_init(db, 'baseline interactive query', 1)
    start = time.monotonic()
    lists.list_find_start.apply_async(args=(cid, segment, {'id':'Email'}, None, None, [lid], 1, [], gid),
        **({'queue':'celery'} if legacy else {}))
    result = wait_for(lambda: gather_check(db, gid), 'interactive results')
    assert len(result) == 1 and result[0].get('count') == COUNT, result
    assert len(result[0]['rows']) == min(COUNT, 50)
    return round(time.monotonic() - start, 3)

try:
    db.set_cid(cid)
    lid = db.lists.add({'name':'Disposable queue baseline'})
    campid = db.campaigns.add({'name':'Disposable fake delivery only','canceled':False})
    sinkid = db.sinks.add({'name':'Local fake Velocity','url':'http://127.0.0.1:8081',
        'accesskey':'disposable', 'ipdata':[]})
    db.execute(f'''insert into contacts."contacts_{cid}" (email,added,props)
        select 'queue-' || n || '@example.invalid',extract(epoch from now())::bigint,'{{}}'::jsonb
        from generate_series(1,%s) n''', COUNT)
    db.execute(f'''insert into contacts."contact_lists_{cid}" (contact_id,list_id)
        select contact_id,%s from contacts."contacts_{cid}" where email like 'queue-%%@example.invalid' ''', lid)
    segment = {'cid':cid,'parts':[],'operator':'and'}
    worker = start_worker()
    if SPLIT: interactive_worker = start_worker(True)
    wait_for(lambda: len(tasks.control.ping(timeout=1)) >= (2 if SPLIT else 1), 'worker readiness', 60)
    report['legacy_queue_query_seconds'] = query(legacy=True)
    report['idle_query_seconds'] = query()
    # Use the real audience builder. Keep the aggregate gather open so the campaign
    # HTML/finalisation chain is not invoked; dispatch preparation is explicit below.
    gid = gather_init(db, 'audience fixture', 2)
    main = gather_init(db, 'audience aggregate fixture', 2)
    started = time.monotonic()
    campaigns.write_campaign_lists.delay(segment,0,[lid],1,[],[],[],gid,[],0,100,
        [{'id':sinkid,'pct':100}],{'id':'baseline-policy'},campid,main)
    wait_for(lambda: db.single("select data->>'count' from taskgather where id=%s",gid) == '1', 'audience')
    files = list(Path(os.environ['s3_databucket']).glob('lists/*/*.blk'))
    assert len(files) == 1, files
    audience = list(MPDictReader(io.BytesIO(files[0].read_bytes())))
    assert len(audience) == COUNT
    report['audience_build_seconds'] = round(time.monotonic()-started,3)
    listkey = str(files[0].relative_to(os.environ['s3_databucket']))
    s3_write(os.environ['s3_databucket'], 'templates/baseline.html', b'<p>Local sink only</p>')
    data = {'policytype':'mta','sinkid':sinkid,'sendid':'baseline','from':'test@example.invalid',
        'fromdomain':'example.invalid','replyto':'test@example.invalid','subject':'No real delivery',
        'template':'templates/baseline.html','listkey':listkey,'settingsid':'baseline-policy'}
    monitor_thread = threading.Thread(target=monitor,daemon=True)
    monitor_thread.start()
    started = time.monotonic()
    for offset in range(0,COUNT,1000):
        result = campaigns.send_queued_camp.delay(cid,campid,'baseline',None,data,offset,min(1000,COUNT-offset))
        submitted[result.id] = time.monotonic()
    wait_for(lambda: active >= min(1 if SPLIT else 2,(COUNT+999)//1000), 'occupied send slots')
    report['busy_query_seconds'] = query()
    # Graceful shutdown while work remains; the same real worker then consumes backlog.
    worker.send_signal(signal.SIGTERM)
    worker.wait(timeout=60)
    report['graceful_worker_exit_code'] = worker.returncode
    worker = start_worker()
    wait_for(lambda: tasks.control.ping(timeout=1), 'restarted worker',60)
    samples = []
    # The supported 100k / 10-second profile needs over 16 minutes with
    # one bulk slot. Bound the run against its intentional service delay.
    budget = max(600, ((COUNT + 999) // 1000) * (DELAY + 5) * 2)
    report['drain_timeout_seconds'] = budget
    deadline = time.monotonic() + budget
    query_samples = []
    next_query = time.monotonic() + 30
    while sum(received.values()) < COUNT and time.monotonic()<deadline:
        depth = sum(rdb.llen(k) for k in QUEUE_KEYS)
        samples.append({'elapsed':round(time.monotonic()-started,2),'queued':depth,
                        'received':sum(received.values())})
        assert not fetch_errors, fetch_errors
        assert not db.campaigns.get(campid).get('error'), db.campaigns.get(campid).get('error')
        if SPLIT and time.monotonic() >= next_query:
            query_samples.append(query())
            next_query = time.monotonic() + 30
        time.sleep(.5)
    assert sum(received.values()) == COUNT and len(received) == COUNT
    assert max(received.values()) == 1 and not fetch_errors
    assert not db.campaigns.get(campid).get('error'), db.campaigns.get(campid)
    report['broadcast_seconds_including_restart'] = round(time.monotonic()-started,3)
    report['busy_query_samples_seconds'] = query_samples
    report['accepted_requests'] = len(requests_seen)
    report['unique_recipients'] = len(received)
    report['queue_samples'] = samples
    report['post_drain_query_seconds'] = query()
    report['transfer_files_after_drain'] = len(list(Path(os.environ['s3_transferbucket']).rglob('*.blk')))
    report['transfer_bytes_after_drain'] = sum(p.stat().st_size for p in Path(os.environ['s3_transferbucket']).rglob('*') if p.is_file())
    # Regression: failed processing retains the event for review without replay.
    rdb.lpush('webhooks-pending',json.dumps({'type':'mg','fixture':'no-contact-data'}))
    with patch.object(events,'process_mg_webhook',side_effect=RuntimeError('Injected handler failure')):
        events.process_webhooks(lambda:False)
    report['event_remaining_after_handler_failure'] = rdb.llen('webhooks-pending')
    assert report['event_remaining_after_handler_failure'] == 0
    report['event_held_after_handler_failure'] = rdb.llen('webhooks-held')
    assert report['event_held_after_handler_failure'] == 1
    # Targeted cleanup reproduction: real campaign holds this template reference.
    target = Path(os.environ['s3_databucket'])/'templates/baseline.html'
    db.execute('insert into campqueue (cid,campid,sendid,domain,count,remaining,data) values (%s,%s,%s,%s,1,1,%s)',
        cid,campid,'pending-cleanup-fixture','example.invalid',data)
    assert db.single("select data->>'template' from campqueue where sendid='pending-cleanup-fixture'") == 'templates/baseline.html'
    old = time.time()-91*86400
    os.utime(target,(old,old))
    s3_delete_all(os.environ['s3_databucket'],time.time()-90*86400)
    report['referenced_old_file_deleted'] = not target.exists()
    assert not report['referenced_old_file_deleted']
    report['database_bytes'] = db.single('select pg_database_size(current_database())')
    stop_metrics.set()
    monitor_thread.join(timeout=10)
    assert not monitor_thread.is_alive() and not metric_errors, metric_errors
    report['metrics'] = metrics
    report['final_queue_depth'] = sum(rdb.llen(k) for k in QUEUE_KEYS)
    assert report['final_queue_depth'] == 0
    report['passed'] = True
finally:
    stop_metrics.set()
    if worker is not None and worker.poll() is None:
        worker.send_signal(signal.SIGTERM)
        try: worker.wait(timeout=60)
        except subprocess.TimeoutExpired:
            worker.kill(); worker.wait()
    if interactive_worker is not None and interactive_worker.poll() is None:
        interactive_worker.send_signal(signal.SIGTERM)
        try: interactive_worker.wait(timeout=60)
        except subprocess.TimeoutExpired:
            interactive_worker.kill(); interactive_worker.wait()
    log.close()
    server.shutdown()
    if not report.get('passed'):
        print(Path('/logs/queue-worker.log').read_text()[-16000:])
print('BASELINE_RESULT='+json.dumps(report),flush=True)
