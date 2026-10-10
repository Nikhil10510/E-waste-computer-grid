"""Real frozen-helper/Docker lease recovery with a blocked loopback API proxy.

Two processes on ONE PC, never physical-LAN or throughput evidence. Only this
fixture's first container is paused to keep execution active across lease loss.
"""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit
import docker
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
from desktop_runtime import DesktopRuntime
import desktop_runtime
from hardware import get_hardware_specs
from pairing_client import PairingClient
from log_safety import safe_text
from verify_packaged_workers import FLEET_SERVER

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    database = os.environ.get('TEST_DATABASE_URL', '')
    if urlsplit(database).hostname not in ('127.0.0.1', 'localhost', '::1'): raise ValueError('Use a local test database')
    engine = docker.from_env(timeout=15)
    engine.ping()  # Fail before starting a fixture if the local engine is stopped.
    schema = 'ewaste_test_package_' + uuid.uuid4().hex
    directory = ROOT / '.test-data' / schema; directory.mkdir(parents=True)
    token = secrets.token_urlsafe(32)
    os.environ.update(HEARTBEAT_INTERVAL='1', MIN_POLL_INTERVAL='0.2')
    env = os.environ.copy(); env.update(TEST_DATABASE_URL=database, EWASTE_TEST_SCHEMA=schema, NODE_ENV='test',
        ADMIN_TOKEN=token, ENROLLMENT_TOKEN=secrets.token_urlsafe(32), STORAGE_SECRET=secrets.token_urlsafe(32),
        ALLOW_LEGACY_ENROLLMENT='false', STORAGE_DRIVER='local', STORAGE_DIR=str(directory/'storage'), PUBLIC_API_URL='/api', TASK_LEASE_MS='5000')
    server = subprocess.Popen(['node', '-e', FLEET_SERVER], cwd=ROOT/'control-plane', env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    lines = queue.Queue()
    def read():
        for line in server.stdout: lines.put(line.strip())
    threading.Thread(target=read, daemon=True).start()
    runtimes, clients = [], []
    blocked, release = threading.Event(), threading.Event()
    proxy = None
    original = desktop_runtime.agent_command
    desktop_runtime.agent_command = lambda *parts: [str(args.helper.resolve()), *parts]
    report = {'status':'RUNNING', 'date':datetime.now(timezone.utc).isoformat(),
        'scope':'Two real frozen helpers on ONE PC; blocked loopback proxy and paused owned container; not physical LAN', 'checks':{}}
    try:
        deadline = time.monotonic()+75; base = None
        while time.monotonic() < deadline:
            try: line = lines.get(timeout=5)
            except queue.Empty: continue
            if line.startswith('READY '): base = line[6:]; break
            if line == 'FIXTURE FAILED': raise RuntimeError('Fixture setup failed')
        if not base: raise TimeoutError('API startup failed')
        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def forward(self):
                if blocked.is_set():
                    release.wait(30)  # Longer than heartbeat HTTP read timeout.
                    if not release.is_set(): self.send_error(503); return
                data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                headers = {key:value for key,value in self.headers.items() if key.lower() not in ('host', 'content-length', 'connection')}
                try:
                    response = requests.request(self.command, base[:-4]+self.path, data=data or None, headers=headers, timeout=(5,20), allow_redirects=False)
                    self.send_response(response.status_code)
                    self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                    self.send_header('Content-Length', str(len(response.content))); self.end_headers(); self.wfile.write(response.content)
                except (OSError, requests.RequestException): pass  # Client may cancel a blocked socket.
            do_GET = forward
            do_POST = forward
            do_PUT = forward
        proxy = ThreadingHTTPServer(('127.0.0.1',0), Proxy); proxy.daemon_threads = True
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        def admin(method, endpoint, body=None):
            response = requests.request(method, base+endpoint, json=body,
                headers={'Authorization':'Bearer '+token, 'Idempotency-Key':str(uuid.uuid4())}, timeout=(5,20))
            response.raise_for_status(); return response.json()
        for i, url in enumerate([f'http://127.0.0.1:{proxy.server_port}/api', base]):
            runtime = DesktopRuntime(url, directory/f'worker {i}', f'Network fixture {i}', {'cpu':.5,'memory_gb':1}); runtimes.append(runtime)
            capabilities = runtime.preflight(threading.Event())
            client = PairingClient(url, runtime.directory, allow_http=True); clients.append(client)
            session = client.begin(get_hardware_specs(capabilities), runtime.limits)
            admin('POST','/pairing/invite', {'pairing_code':session['pairing_code']}); client.decide(True)
            client.set_paused(True); runtime.start()
        job = admin('POST','/jobs', {'name':'Network lease watchdog fixture', 'workload_type':'dummy',
            'items':[f'item {i}' for i in range(100)], 'chunk_size':100, 'min_ram_gb':.25})
        clients[0].set_paused(False)
        active = None; deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            for container in engine.containers.list(filters={'label':'ewaste.worker='+str(runtimes[0].directory)}):
                if not container.labels['ewaste.attempt'].startswith('preflight-'): active = container; break
            if active: break
            time.sleep(.05)
        if not active: raise AssertionError('No active owned Docker task observed')
        active.pause(); blocked.set(); loss = time.monotonic()
        clients[1].set_paused(False)
        deadline = loss+7
        while time.monotonic() < deadline:
            if not engine.containers.list(all=True, filters={'label':'ewaste.worker='+str(runtimes[0].directory)}): break
            time.sleep(.1)
        assert not engine.containers.list(all=True, filters={'label':'ewaste.worker='+str(runtimes[0].directory)}), 'Watchdog did not remove expired owned task'
        report['cancellation_seconds_after_network_loss'] = round(time.monotonic()-loss,3)
        report['checks']['expired_compute_stops_while_heartbeat_socket_is_blocked'] = True
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            result = admin('GET',f'/jobs/{job["id"]}/results')
            if result['status'] == 'COMPLETED': break
            time.sleep(.2)
        assert result['status']=='COMPLETED' and result['items_processed']==100 and len(result['predictions'])==100
        batches = admin('GET',f'/jobs/{job["id"]}/tasks')
        attempts = batches['tasks'][0]['attempts']
        assert [(a['number'],a['status']) for a in attempts] == [(1,'COMPLETED'),(0,'REQUEUED')]
        assert attempts[0]['worker_id'] != attempts[1]['worker_id']
        report['checks']['same_batch_reassigned_to_other_worker_exactly_once'] = True
        report['attempt_history'] = attempts
        report['status']='PASSED'
    except Exception as error:
        report['status']='FAILED'; report['error']=safe_text(error)
        raise
    finally:
        blocked.clear(); release.set()
        for runtime in runtimes:
            if runtime.running(): runtime.request_stop(); runtime.process.wait(timeout=55)
        desktop_runtime.agent_command = original
        leftovers = sum(len(engine.containers.list(all=True, filters={'label':'ewaste.worker='+str(r.directory)})) for r in runtimes)
        report['owned_containers_after_stop'] = leftovers; engine.close()
        if proxy: proxy.shutdown(); proxy.server_close()
        if server.poll() is None: server.stdin.write('stop\n'); server.stdin.flush(); server.wait(timeout=25)
        while not lines.empty():
            line=lines.get_nowait()
            if line.startswith('EVIDENCE '): report['accepted_counts']=json.loads(line[9:])
        if report['status']=='PASSED' and (leftovers or report['accepted_counts']['metrics']!=1): report['status']='FAILED'
        args.report.parent.mkdir(parents=True,exist_ok=True); args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'], 'report':str(args.report)}))
    return 0 if report['status']=='PASSED' else 1

if __name__=='__main__': sys.exit(main())
