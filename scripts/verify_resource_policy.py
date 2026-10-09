"""Live Step 3 acceptance against a dedicated local test grid, after owner approval.

Creates test jobs and briefly starts an approved Docker agent. Close its desktop
first. Never point this at a shared grid: existing jobs/other workers are rejected.
The private config JSON contains api_url, schema and admin_token; it is not output.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import uuid

import docker
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
from desktop_runtime import DesktopRuntime
from pairing_client import PairingClient
from resource_limits import memory_bytes
from state_store import load_state


def wait_for(check, label, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value: return value
        time.sleep(0.15)
    raise AssertionError('Timed out: ' + label)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-config', type=Path, required=True)
    parser.add_argument('--state-directory', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.private_config.read_text(encoding='utf-8-sig'))
    api_url = config['api_url'].rstrip('/')
    if urlsplit(api_url).hostname not in ('127.0.0.1', 'localhost') or not config['schema'].startswith('ewaste_acceptance_step3_'):
        raise ValueError('Use a dedicated local Step 3 acceptance grid')
    directory = args.state_directory.resolve()
    client = PairingClient(api_url, directory, allow_http=True)
    identity = client.saved_identity()
    if not identity: raise ValueError('Owner must approve this state directory in the desktop first')
    limits, node_id = identity['resource_limits'], identity['node_id']
    if limits['memory_gb'] >= 2 or limits['cpu'] > 1:
        raise ValueError('Choose a fractional CPU limit and RAM below 2 GiB for this acceptance matrix')
    engine = docker.from_env(timeout=15)
    report = {'date': datetime.now(timezone.utc).isoformat(), 'status': 'RUNNING',
              'scope': 'Local Docker and HTTP acceptance; not a physical second-device test',
              'node_id': node_id, 'resource_limits': limits, 'checks': {}, 'jobs': {}}
    runtime = None
    sentinel = None

    def admin(method, path, body=None):
        response = requests.request(method, api_url + path, json=body,
            headers={'Authorization': 'Bearer ' + config['admin_token'],
                     'Idempotency-Key': str(uuid.uuid4())}, timeout=(5, 15), allow_redirects=False)
        response.raise_for_status()
        return response.json()

    def dashboard(): return admin('GET', '/dashboard/sync')

    def node():
        return next(n for n in dashboard()['nodes'] if n['id'] == node_id)

    def result(job_id): return admin('GET', f'/jobs/{job_id}/results')

    def job(label, count, minimum=0.25):
        created = admin('POST', '/jobs', {'name': 'Step 3 ' + label, 'workload_type': 'dummy',
            'items': [str(i) for i in range(count)], 'chunk_size': 100, 'min_ram_gb': minimum})
        report['jobs'][label] = created['id']
        return created['id']

    def containers():
        return engine.containers.list(filters={'label': 'ewaste.worker=' + str(directory)})

    def workload():
        return next((c for c in containers() if not c.labels['ewaste.attempt'].startswith('preflight-')), None)

    def note(key, value=True):
        report['checks'][key] = value
        print('Passed: ' + key, flush=True)

    def snapshot(container):
        container.reload()
        host = container.attrs['HostConfig']
        expected = memory_bytes(limits)
        assert host['NanoCpus'] == int(limits['cpu'] * 1e9)
        assert host['Memory'] == expected and host['MemorySwap'] == expected
        assert container.attrs['Config']['NetworkDisabled'] and host['ReadonlyRootfs']
        values = {}
        for name in ('cpu.max', 'memory.max', 'memory.swap.max'):
            exit_code, output = container.exec_run(['cat', '/sys/fs/cgroup/' + name])
            assert exit_code == 0, 'Cannot read workload cgroup ' + name
            values[name] = output.decode().strip()
        quota, period = map(int, values['cpu.max'].split())
        assert quota / period == limits['cpu']
        assert int(values['memory.max']) == expected and values['memory.swap.max'] == '0'
        return {'nano_cpus': host['NanoCpus'], 'memory_bytes': expected,
                'memory_swap_bytes': host['MemorySwap'], 'network_disabled': True,
                'read_only_root': True, 'cgroup': values}

    def start():
        nonlocal runtime
        latest = datetime.now(timezone.utc)
        runtime = DesktopRuntime(api_url, directory, 'Step 3 test worker', limits)
        runtime.start()
        wait_for(lambda: datetime.fromisoformat(node()['lastHeartbeat'].replace('Z', '+00:00')) > latest,
                 'new process heartbeat')
        assert runtime.running(), 'Worker exited during startup; inspect its private log'

    def stop():
        runtime.request_stop()
        wait_for(lambda: not runtime.running(), 'worker stop', 30)
        assert not containers(), 'Owned container remained after stop'
        sentinel.reload()
        assert sentinel.status == 'running', 'Worker removed another owner\'s container'

    # Test requests/task returns HTTP 204, unlike pairing JSON-only endpoints.
    def no_assignment():
        response = requests.get(api_url + '/tasks/request', headers={
            'Authorization': 'Bearer ' + saved['node_secret'], 'x-node-id': node_id}, timeout=(5, 15), allow_redirects=False)
        assert response.status_code == 204

    def verify_complete(job_id, count, suffix):
        finished = wait_for(lambda: (r if (r := result(job_id))['status'] == 'COMPLETED' else None), 'job ' + suffix, 40)
        assert finished['items_processed'] == count and finished['items_failed'] == 0
        assert finished['errors'] == [] and finished['failed_tasks'] == 0
        names = [p['image'] for p in finished['predictions']]
        assert sorted(names) == [f'{i:05d}.txt' for i in range(count)]
        assert len(set(names)) == count
        args.report.parent.mkdir(parents=True, exist_ok=True)
        output = args.report.with_name(args.report.stem + '-' + suffix + '-results.json')
        output.write_text(json.dumps(finished, indent=2) + '\n', encoding='utf-8')
        return {'job_id': job_id, 'items': count, 'tasks': finished['completed_tasks'], 'result_file': output.name}

    try:
        initial = dashboard()
        assert len(initial['nodes']) == 1 and initial['nodes'][0]['id'] == node_id
        assert not initial['workloads']['recent_jobs'], 'Use a fresh acceptance schema'
        assert not containers(), 'Close the desktop/worker before running acceptance'
        saved = load_state(client.credentials_file)
        sentinel = engine.containers.run('ewaste/dummy-workload:v1',
            ['python', '-c', 'import time; time.sleep(180)'], detach=True,
            name='ewaste-step3-sentinel-' + uuid.uuid4().hex[:12],
            network_disabled=True, read_only=True, cap_drop=['ALL'], pids_limit=16,
            mem_limit='64m', memswap_limit='64m', nano_cpus=250000000)
        os.environ['HEARTBEAT_INTERVAL'] = '1'
        os.environ['MIN_POLL_INTERVAL'] = '0.2'
        client.set_paused(True)
        incompatible = job('RAM incompatible', 1, limits['memory_gb'] + 0.25)
        drain = job('pause drain', 200)
        start()
        wait_for(lambda: node()['status'] == 'PAUSED', 'paused start')
        no_assignment()
        assert result(drain)['completed_tasks'] == 0 and workload() is None
        assert dashboard()['hardware']['available_cores'] == 0
        note('paused_start_admits_no_task')
        client.set_paused(False)
        container = wait_for(workload, 'running workload')
        note('docker_and_kernel_resource_ceilings', snapshot(container))
        reply = client.set_paused(True)
        assert reply['status'] == 'DRAINING'
        active = client.request('GET', '/tasks/request', secret=saved['node_secret'], node_id=node_id)
        assert active['job_id'] == drain and active['lease_token'] == container.labels['ewaste.attempt']
        wait_for(lambda: result(drain)['completed_tasks'] == 1 and node()['status'] == 'PAUSED', 'draining completes one task', 30)
        no_assignment()
        time.sleep(2)
        assert result(drain)['completed_tasks'] == 1 and workload() is None
        note('pause_drains_current_task_and_blocks_next')
        stop()
        start()
        wait_for(lambda: node()['status'] == 'PAUSED', 'paused restart')
        no_assignment()
        time.sleep(2)
        assert result(drain)['completed_tasks'] == 1 and workload() is None
        persisted = load_state(client.credentials_file)
        assert persisted['paused'] is True and persisted['resource_limits'] == limits
        note('pause_and_limits_survive_process_restart')
        client.set_paused(False)
        note('resume_finishes_remaining_task', verify_complete(drain, 200, 'drain'))
        cancelled = job('active stop retry', 100)
        wait_for(workload, 'task to stop')
        stopped_at = time.monotonic()
        stop()
        elapsed = time.monotonic() - stopped_at
        assert elapsed < 7, 'Expected explicit release before the ten-second test lease expires'
        assert result(cancelled)['completed_tasks'] == 0 and result(cancelled)['items_processed'] == 0
        client.set_paused(True)
        no_assignment()
        start()
        wait_for(lambda: node()['status'] == 'PAUSED', 'paused restart after active stop')
        no_assignment()
        time.sleep(2)
        assert result(cancelled)['completed_tasks'] == 0 and workload() is None
        note('active_stop_cancels_only_owned_work', {'stop_seconds': round(elapsed, 3)})
        client.set_paused(False)
        retry = wait_for(workload, 'requeued stopped task')
        active = client.request('GET', '/tasks/request', secret=saved['node_secret'], node_id=node_id)
        assert active['job_id'] == cancelled and active['retry_count'] == 1
        assert active['lease_token'] == retry.labels['ewaste.attempt']
        note('stopped_attempt_requeues_with_new_lease', {'retry_count': active['retry_count']})
        note('retry_has_exactly_one_accepted_result', verify_complete(cancelled, 100, 'retry'))
        assert result(incompatible)['status'] == 'QUEUED' and result(incompatible)['completed_tasks'] == 0
        note('RAM_incompatible_job_stays_queued')
        assert len(dashboard()['nodes']) == 1
        note('same_approved_identity_reused')
        stop()
        note('unrelated_container_retained_through_stop_and_restart')
        report['status'] = 'PASSED'
    except Exception as error:
        report['status'] = 'FAILED'
        report['error'] = str(error)
        raise
    finally:
        cleanup_errors = []
        try:
            if runtime and runtime.running():
                runtime.request_stop()
                wait_for(lambda: not runtime.running(), 'cleanup worker', 30)
        except Exception as error:
            cleanup_errors.append('Worker cleanup: ' + str(error))
        try:
            if sentinel: sentinel.remove(force=True)
        except Exception as error:
            cleanup_errors.append('Test sentinel cleanup: ' + str(error))
        finally:
            engine.close()
        if cleanup_errors:
            report.update(status='FAILED', cleanup_errors=cleanup_errors)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if cleanup_errors: raise RuntimeError('Acceptance cleanup failed; inspect the report')
    print('Step 3 Docker acceptance passed; report: ' + str(args.report), flush=True)


if __name__ == '__main__': main()
