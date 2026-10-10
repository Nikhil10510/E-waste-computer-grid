"""Isolated real packaged-helper acceptance; multiple workers are on ONE PC.

Requires the local test DB, Docker Linux engine and reviewed runtime images.
Approvals are simulated only for this generated fixture; no existing identity
or public database schema is modified. Reports contain no private credentials.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
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
sys.path.insert(0, str(ROOT / 'workloads/test-data'))
import desktop_runtime
from desktop_runtime import DesktopRuntime, worker_environment
from hardware import get_hardware_specs
from pairing_client import PairingClient
from state_store import load_state
from runtime_release import OfflineRelease
from verify_job_results import verify_job
from verify_offline_runtime import SERVER

# Independent generated schema and an actual sweeper for crash recovery.
FLEET_SERVER = SERVER.replace('ewaste_test_step5_', 'ewaste_test_package_').replace(
    "state = require('./dist/app');",
    "state = require('./dist/app'); setInterval(() => state.sweep().catch(() => {}), 500).unref();")
FLEET_SERVER = FLEET_SERVER.replace('metrics: await state.prisma.metric.count()',
    "metrics: await state.prisma.metric.count(), ownership: await state.prisma.task.findMany({select:{id:true,jobId:true,nodeId:true,status:true,retryCount:true}})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=(1, 4, 5), default=1)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    helper = args.helper.resolve()
    if not helper.is_file(): raise ValueError('Build the packaged helper first')
    database = os.environ.get('TEST_DATABASE_URL', '')
    if urlsplit(database).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Set TEST_DATABASE_URL to a dedicated LOCAL test database')
    schema = 'ewaste_test_package_' + uuid.uuid4().hex
    directory = ROOT / '.test-data' / schema
    directory.mkdir(parents=True)
    # Accelerated fixture timings; production defaults remain untouched.
    os.environ.update(HEARTBEAT_INTERVAL='1', MIN_POLL_INTERVAL='0.2')
    admin_token = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update(TEST_DATABASE_URL=database, EWASTE_TEST_SCHEMA=schema,
        STORAGE_DRIVER='local', STORAGE_DIR=str(directory / 'storage'), PUBLIC_API_URL='/api',
        ADMIN_TOKEN=admin_token, STORAGE_SECRET=secrets.token_urlsafe(32),
        ENROLLMENT_TOKEN=secrets.token_urlsafe(32), ALLOW_LEGACY_ENROLLMENT='false', NODE_ENV='test',
        TASK_LEASE_MS='15000', NODE_OFFLINE_MS='10000')
    server = subprocess.Popen(['node', '-e', FLEET_SERVER], cwd=ROOT / 'control-plane', env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    lines = queue.Queue()
    def read_lines():
        for line in server.stdout: lines.put(line.strip())
    threading.Thread(target=read_lines, daemon=True).start()
    runtimes, clients, node_ids = [], [], []
    engine = docker.from_env(timeout=15)
    sentinel = engine.containers.run(OfflineRelease().images['dummy'],
        ['-c', 'import time; time.sleep(300)'], entrypoint='python', detach=True,
        network_disabled=True, read_only=True, nano_cpus=100000000, mem_limit=32*1024*1024,
        memswap_limit=32*1024*1024, cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
        labels={'ewaste.acceptance-sentinel': schema})
    original_command = desktop_runtime.agent_command
    desktop_runtime.agent_command = lambda *parts: [str(helper), *parts]
    report = {'date': datetime.now(timezone.utc).isoformat(), 'status': 'RUNNING',
        'scope': f'{args.workers} REAL frozen helpers on ONE Windows PC; isolated DB/API/Docker; approvals simulated; no physical laptop or speedup claim',
        'helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(), 'checks': {}, 'jobs': []}
    report['fixture_timings'] = {'lease_ms': 15000, 'offline_ms': 10000, 'heartbeat_seconds': 1}
    baseline = {c.id for c in engine.containers.list()}
    try:
        deadline = time.monotonic() + 75
        api_url = None
        while time.monotonic() < deadline:
            try: line = lines.get(timeout=1)
            except queue.Empty: continue
            if line.startswith('READY '): api_url = line[6:]; break
            if line == 'FIXTURE FAILED': raise RuntimeError('Isolated test API setup failed')
        if not api_url: raise TimeoutError('Test API did not start')
        def admin(method, path, body=None, data=None, extra=None):
            r = requests.request(method, api_url + path, json=body, data=data,
                headers={'Authorization': 'Bearer ' + admin_token, 'Idempotency-Key': str(uuid.uuid4()), **(extra or {})},
                timeout=(5, 15), allow_redirects=False)
            r.raise_for_status(); return r.json()
        for index in range(args.workers):
            runtime = DesktopRuntime(api_url, directory / f'worker {index+1}', f'Packaged test {index+1}', {'cpu': 0.5, 'memory_gb': 1})
            runtimes.append(runtime)
            capabilities = runtime.preflight(threading.Event())
            client = PairingClient(api_url, runtime.directory, allow_http=True); clients.append(client)
            hardware = get_hardware_specs(capabilities); hardware['name'] = runtime.name
            session = client.begin(hardware, runtime.limits)
            assert not runtime.running() and not client.credentials_file.exists()
            admin('POST', '/pairing/invite', {'pairing_code': session['pairing_code']})
            assert not client.credentials_file.exists()
            identity = client.decide(True); node_ids.append(identity['node_id'])
            assert load_state(client.credentials_file)['resource_limits'] == runtime.limits
            client.set_paused(True)
            runtime.start()
        report['checks']['no_agent_or_identity_before_fixture_approval'] = True
        report['checks']['real_frozen_preflight_and_saved_limits'] = True
        photos = sorted(p for p in (ROOT / 'workloads/test-data/demo').iterdir() if p.suffix.lower() in ('.jpg', '.png'))
        assert len(photos) == 10
        repeats = 1 if args.workers == 1 else 6
        names, items = [], []
        for repeat in range(repeats):
            for photo in photos:
                name = photo.name if repeats == 1 else f'{repeat}_{photo.name}'
                names.append(name)
                items.append(admin('POST', '/inputs?name=' + name, data=photo.read_bytes(), extra={'Content-Type': 'application/octet-stream'}))
        chunk = 5 if args.workers == 1 else 2
        job = admin('POST', '/jobs', {'name': 'Packaged worker acceptance', 'workload_type': 'image_inference',
            'items': items, 'chunk_size': chunk, 'min_ram_gb': 1})
        time.sleep(3)
        paused = admin('GET', f'/jobs/{job["id"]}/results')
        assert paused['completed_tasks'] == 0
        report['checks']['paused_helpers_accept_no_work'] = True
        for client in clients: client.set_paused(False)
        observed, concurrent, crashed = {}, set(), False
        deadline = time.monotonic() + 210
        while time.monotonic() < deadline:
            result = admin('GET', f'/jobs/{job["id"]}/results')
            active_workers = set()
            for index, runtime in enumerate(runtimes):
                for container in engine.containers.list(filters={'label': 'ewaste.worker=' + str(runtime.directory)}):
                    container.reload(); options = container.attrs['HostConfig']
                    assert options['NanoCpus'] == 500000000 and options['Memory'] == 1073741824
                    assert options['MemorySwap'] == options['Memory']
                    assert options['ReadonlyRootfs'] and container.attrs['Config']['NetworkDisabled']
                    assert container.attrs['Image'] in runtime.release.images.values()
                    if not container.labels['ewaste.attempt'].startswith('preflight-'):
                        active_workers.add(index)
                        observed[container.id] = {'worker': index+1, 'image': container.attrs['Image'],
                            'cpu': 0.5, 'memory_bytes': options['Memory'], 'attempt': container.labels['ewaste.attempt']}
            if len(active_workers) >= 2: concurrent.update(active_workers)
            if args.workers > 1 and not crashed and 0 in active_workers and len(active_workers) >= 2:
                # Kill only this Popen-owned disposable helper, never by process name.
                runtimes[0].process.kill(); runtimes[0].process.wait(timeout=10); crashed = True
            if result['status'] == 'COMPLETED': break
            if any(not r.running() for r in runtimes[1:] if args.workers > 1):
                raise RuntimeError('A surviving packaged helper exited')
            time.sleep(0.15)
        report['jobs'].append(verify_job(result, names, chunk))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.with_name(args.report.stem + '-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        assert observed, 'No actual inference container was observed'
        summary = admin('GET', f'/jobs/{job["id"]}')
        assert summary['items'] == {'total': len(items), 'processed': len(items), 'failed': 0, 'cancelled': 0, 'pending': 0}
        report['job_summary'] = summary
        batches = admin('GET', f'/jobs/{job["id"]}/tasks?limit=100')
        assert len(batches['tasks']) == len(items) // chunk
        assert all(t['attempts'] and t['attempts'][0]['status'] == 'COMPLETED' for t in batches['tasks'])
        if args.workers > 1:
            assert any(any(a['status'] == 'REQUEUED' for a in t['attempts']) for t in batches['tasks'])
        report['checks']['dashboard_history_explains_accepted_work_and_recovery'] = True
        report['checks']['immutable_images_and_real_container_quotas'] = True
        report['observed_containers'] = list(observed.values())
        if args.workers > 1:
            assert len(concurrent) >= 2 and crashed
            report['checks']['concurrent_execution_and_owned_helper_crash'] = True
            # Reconnect same protected identity; no re-enrollment or clearing state.
            old_id = load_state(clients[0].credentials_file)['node_id']
            runtimes[0].start()
            time.sleep(3)
            assert clients[0].saved_identity()['node_id'] == old_id
            report['checks']['same_identity_reconnect_after_crash'] = True
        # Explicit pause remains in server truth and protected local state.
        clients[-1].set_paused(True)
        runtimes[-1].request_stop(); runtimes[-1].process.wait(timeout=50)
        runtimes[-1].start(); time.sleep(3)
        assert clients[-1].saved_identity()['paused'] and load_state(clients[-1].credentials_file)['paused']
        report['checks']['pause_survives_packaged_helper_restart'] = True
        broken = worker_environment(api_url, directory / 'missing-docker', 'Missing Docker test', release=runtimes[0].release)
        broken['DOCKER_HOST'] = 'npipe:////./pipe/ewaste-missing-engine-' + uuid.uuid4().hex
        failure = subprocess.run([str(helper), '--preflight'], env=broken, capture_output=True, text=True, timeout=30)
        assert failure.returncode != 0
        report['checks']['unavailable_docker_fails_preflight'] = True
        unapproved = worker_environment(api_url, directory / 'no-owner-approval', 'Unapproved test', release=runtimes[0].release)
        unapproved['REQUIRE_PAIRED_IDENTITY'] = 'false'
        failure = subprocess.run([str(helper)], env=unapproved, capture_output=True, text=True, timeout=20)
        rejected = load_state(directory / 'no-owner-approval/credentials.json')
        # The legacy client may persist an empty registration placeholder;
        # neither an actual node identity nor approval can be manufactured.
        assert failure.returncode != 0 and not rejected.get('node_id') and not rejected.get('node_secret')
        report['checks']['frozen_helper_requires_approval_despite_environment_override'] = True
        unapproved['EXECUTION_MODE'] = 'native'
        failure = subprocess.run([str(helper), '--preflight'], env=unapproved, capture_output=True, text=True, timeout=20)
        assert failure.returncode != 0
        report['checks']['packaged_native_execution_refused'] = True
        report['status'] = 'PASSED'
    finally:
        desktop_runtime.agent_command = original_command
        for runtime in runtimes:
            if runtime.running(): runtime.request_stop(); runtime.process.wait(timeout=50)
        report['owned_containers_after_stop'] = sum(len(engine.containers.list(all=True,
            filters={'label': 'ewaste.worker=' + str(r.directory)})) for r in runtimes)
        report['unrelated_containers_preserved'] = baseline.issubset({c.id for c in engine.containers.list()})
        sentinel.reload()
        report['checks']['unrelated_running_container_survives_worker_cleanup'] = sentinel.status == 'running'
        sentinel.remove(force=True)  # Only this disposable harness-owned sentinel.
        engine.close()
        if server.poll() is None:
            server.stdin.write('stop\n'); server.stdin.flush(); server.wait(timeout=25)
        while not lines.empty():
            line = lines.get_nowait()
            if line.startswith('EVIDENCE '): report['accepted_counts'] = json.loads(line[9:])
        report['fixture_exit_code'] = server.returncode
        if report['status'] == 'PASSED':
            evidence = report['accepted_counts']; expected = len(items) // chunk
            owners = Counter(row['nodeId'] for row in evidence['ownership'])
            report['accepted_tasks_per_worker'] = {str(i+1): owners[node] for i, node in enumerate(node_ids)}
            valid = (evidence['nodes'] == args.workers and evidence['pairings'] == args.workers and
                evidence['tasks'] == evidence['metrics'] == expected and report['owned_containers_after_stop'] == 0 and
                report['unrelated_containers_preserved'] and report['checks']['unrelated_running_container_survives_worker_cleanup'] and server.returncode == 0)
            if args.workers > 1:
                valid = valid and len([n for n in owners.values() if n]) >= args.workers-1 and any(row['retryCount'] > 0 for row in evidence['ownership'])
                report['checks']['expired_attempt_retried_one_metric_per_task'] = valid
            if not valid: report['status'] = 'FAILED'
        else: report['status'] = 'FAILED'
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'report': str(args.report), 'tasks_per_worker': report.get('accepted_tasks_per_worker')}))
    return 0 if report['status'] == 'PASSED' else 1


if __name__ == '__main__': sys.exit(main())
