#!/usr/bin/env python3
"""Real bulk + transactional tasks, isolated broker/DB and slow fake delivery only.
Run through run_transactional_queue_check.sh; never loads production config.
The fake FIFO downstream deliberately has NO priority: this tests the boundary too.
"""
import base64
import io
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

if os.environ.get('EDCOM_DISPOSABLE_VOLUME_CHECK') != '1' or Path('/config/edcom.json').exists():
    raise SystemExit('Disposable container required')
sys.path[:0] = ['/test', '/']
from test_base import TestBase
from api import campaigns, transactional
from api.shared.tasks import tasks
from api.shared.utils import MPDictReader, MPDictWriter, create_txnid, redis_connect
from api.shared.s3 import s3_write
import shortuuid

os.environ.pop('SYNC_TASKS', None)
os.environ['development'] = ''
os.environ['webroot'] = 'http://127.0.0.1:8081'
SPLIT = os.environ.get('transactional_task_queue', '').lower() in ('true', '1')
BATCHES, PER_BATCH = 8, 100
HTTP_DELAY, DELIVERY_DELAY = 2, .04
report = {'reserved_transactional_worker': SPLIT, 'bulk_recipients': BATCHES * PER_BATCH,
          'bulk_workers': 1, 'transactional_workers': int(SPLIT),
          'bulk_http_delay_seconds': HTTP_DELAY, 'fake_recipient_delay_seconds': DELIVERY_DELAY}
case = TestBase(); case.setUp()
db, cid = case.db, case.user_cookie['cid']
workers = []
errors = []
accepted = {}
delivered = {}
spool = queue.Queue()
lock = threading.Lock()
active_bulk = threading.Event()
log = open('/logs/transactional-worker.log', 'w')


def deliver():
    while True:
        email = spool.get()
        if email is None:
            spool.task_done(); return
        time.sleep(DELIVERY_DELAY)
        with lock:
            if email in delivered: errors.append('Duplicate delivery')
            delivered[email] = time.monotonic()
        spool.task_done()


class Sink(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        if not self.path.startswith('/transfer/') or '..' in self.path:
            self.send_error(404); return
        path = Path(os.environ['s3_transferbucket']) / self.path[len('/transfer/'):]
        self.send_response(200); self.end_headers(); self.wfile.write(path.read_bytes())

    def do_POST(self):
        try:
            obj = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path == '/settings':
                self.send_response(200); self.end_headers(); return
            assert self.path == '/send-lists', self.path
            if 'listdata' in obj:
                rows = list(MPDictReader(io.BytesIO(base64.b64decode(obj['listdata']))))
            else:
                active_bulk.set()
                rows = []
                for url in obj['listurls']:
                    assert url.startswith('http://127.0.0.1:8081/transfer/')
                    with urlopen(url, timeout=10) as response:
                        rows.extend(MPDictReader(io.BytesIO(response.read())))
            for row in rows:
                email = row['Email']
                assert email.endswith('@example.invalid')
                with lock:
                    assert email not in accepted
                    accepted[email] = time.monotonic()
                spool.put(email)
            time.sleep(.1 if 'listdata' in obj else HTTP_DELAY)
            self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        except Exception as exc:
            errors.append(str(exc)); self.send_error(500)


server = ThreadingHTTPServer(('127.0.0.1', 8081), Sink)
threading.Thread(target=server.serve_forever, daemon=True).start()
delivery_thread = threading.Thread(target=deliver, daemon=True)
delivery_thread.start()


def wait_for(check, label, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        assert not errors, errors
        assert all(w.poll() is None for w in workers), 'Worker exited'
        if check(): return
        time.sleep(.05)
    raise AssertionError('Timeout: ' + label)


try:
    db.set_cid(None)
    company = db.companies.get(cid)
    db.set_cid(company['cid'])
    sinkid = db.sinks.add({'name': 'Disposable fake sink', 'url': 'http://127.0.0.1:8081',
                          'accesskey': 'disposable', 'ipdata': []})
    policy = {'name': 'Disposable policy', 'domains': '*', 'sinks': [{'sink': sinkid, 'pct': 100, 'allips': True, 'iplist': {}}]}
    policyid = db.policies.add(dict(policy, published=policy, dirty=False))
    rules = [{'splits': [{'pct': 100, 'policy': policyid}], 'default': True, 'domaingroup': ''}]
    routeid = db.routes.add({'name': 'Disposable route', 'rules': rules, 'usedefault': False,
                            'published': {'rules': rules, 'usedefault': False}})
    db.set_cid(cid)
    db.clientdkim.add({'name': 'example.invalid', 'verified': True})
    campid = db.campaigns.add({'name': 'Disposable slow bulk', 'canceled': False})
    tagid = shortuuid.uuid()
    db.execute('insert into txntags (id,cid,tag) values (%s,%s,%s)', tagid, cid, 'disposable-login')
    txnid = create_txnid(tagid)
    bodykey = 'templates/disposable-login.html'
    s3_write(os.environ['s3_databucket'], bodykey, b'<p>Disposable login placeholder; no credentials.</p>')
    s3_write(os.environ['s3_databucket'], 'templates/slow-bulk.html', b'<p>Fake bulk only</p>')
    contents = io.BytesIO()
    writer = MPDictWriter(contents, ['Email']); writer.writeheader()
    for n in range(BATCHES * PER_BATCH): writer.writerow({'Email': 'bulk-%d@example.invalid' % n})
    listkey = 'lists/slow-bulk.blk'
    s3_write(os.environ['s3_databucket'], listkey, contents.getvalue())
    for lane in (['celery', 'transactional'] if SPLIT else ['celery']):
        workers.append(subprocess.Popen(['celery', '-A', 'api.app.tasks', 'worker', '--loglevel=WARNING',
            '--concurrency=1', '--queues='+lane, '--hostname='+lane+'@%h', '--without-gossip', '--without-mingle'],
            cwd='/', stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy()))
    wait_for(lambda: len(tasks.control.ping(timeout=1)) == len(workers), 'readiness', 60)
    data = {'policytype': 'mta', 'sinkid': sinkid, 'sendid': 'slow-bulk', 'from': 'sender@example.invalid',
            'fromdomain': 'example.invalid', 'replyto': 'sender@example.invalid', 'subject': 'Fake bulk',
            'template': 'templates/slow-bulk.html', 'listkey': listkey, 'settingsid': policyid}
    for n in range(BATCHES):
        campaigns.send_queued_camp.delay(cid, campid, 'slow-bulk', None, data, n * PER_BATCH, PER_BATCH)
    wait_for(active_bulk.is_set, 'bulk active')
    started = time.monotonic()
    transactional.send_txn.delay(company, {'campid': txnid, 'tag': 'disposable-login', 'template': '',
        'body': bodykey, 'variables': None, 'route': routeid, 'to': 'login@example.invalid',
        'fromname': '', 'fromemail': 'sender@example.invalid', 'returnpath': 'sender@example.invalid',
        'replyto': '', 'subject': 'Disposable login', 'toname': None, 'disableopens': True})
    wait_for(lambda: 'login@example.invalid' in accepted, 'transaction handoff')
    report['transaction_handoff_seconds'] = round(accepted['login@example.invalid'] - started, 3)
    report['bulk_recipients_handed_off_before_transaction'] = len(accepted) - 1
    if SPLIT:
        assert report['bulk_recipients_handed_off_before_transaction'] < BATCHES * PER_BATCH
    wait_for(lambda: len(delivered) == BATCHES * PER_BATCH + 1, 'fake delivery')
    report['transaction_fake_delivery_seconds'] = round(delivered['login@example.invalid'] - started, 3)
    report['downstream_wait_seconds'] = round(delivered['login@example.invalid'] - accepted['login@example.invalid'], 3)
    assert report['downstream_wait_seconds'] > 1, 'Slow downstream was not exercised'
    assert len(accepted) == BATCHES * PER_BATCH + 1
    assert not db.campaigns.get(campid).get('error')
    assert not db.single("select count(*) from txnsends where cid=%s and data->>'event'='Error'", cid)
    rdb = redis_connect()
    wait_for(lambda: not any(rdb.llen(q+s) for q in ('celery','transactional') for s in ('',':3',':6',':9')), 'queue drain')
    report['unique_fake_deliveries'] = len(delivered)
    report['passed'] = True
finally:
    for worker in workers:
        if worker.poll() is None:
            worker.send_signal(signal.SIGTERM)
            try: worker.wait(timeout=30)
            except subprocess.TimeoutExpired: worker.kill(); worker.wait()
    server.shutdown()
    spool.put(None)
    delivery_thread.join(timeout=5)
    log.close()
    if not report.get('passed'): print(Path('/logs/transactional-worker.log').read_text()[-12000:])
print('TRANSACTIONAL_RESULT='+json.dumps(report), flush=True)
