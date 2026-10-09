"""Real local Step 5 import + paired Docker job, using an isolated test schema.

Owner decisions are simulated for this automated fixture. No real desktop is
controlled, no existing worker identity is used, and no public schema is reset.
"""
import argparse
from datetime import datetime, timezone
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
from urllib.parse import quote

import docker
from dotenv import dotenv_values
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
sys.path.insert(0, str(ROOT / 'workloads/test-data'))
from runtime_release import OfflineRelease, DEFAULT_MANIFEST
from desktop_runtime import DesktopRuntime
from hardware import get_hardware_specs
from pairing_client import PairingClient
from verify_job_results import verify_job

SERVER = r"""
const { PrismaClient } = require('./node_modules/@prisma/client');
const { spawnSync } = require('node:child_process');
const schema = process.env.EWASTE_TEST_SCHEMA;
if (!/^ewaste_test_step5_[a-f0-9]{32}$/.test(schema)) throw new Error('Invalid isolated test schema');
const root = new PrismaClient({ datasources: { db: { url: process.env.TEST_DATABASE_URL } } });
let state, server, stopping = false;
async function stop() {
  if (stopping) return; stopping = true;
  try {
    if (state) {
      const evidence = {nodes: await state.prisma.node.count(), pairings: await state.prisma.pairingSession.count(),
        tasks: await state.prisma.task.count(), metrics: await state.prisma.metric.count()};
      console.log('EVIDENCE ' + JSON.stringify(evidence));
    }
    if (server) await new Promise(resolve => server.close(resolve));
    if (state) await state.prisma.$disconnect();
    await root.$executeRawUnsafe(`DROP SCHEMA IF EXISTS "${schema}" CASCADE`);
    await root.$disconnect();
    process.exit(0);
  } catch (_) { process.exit(1); }
}
(async () => {
  await root.$executeRawUnsafe(`CREATE SCHEMA "${schema}"`);
  const url = new URL(process.env.TEST_DATABASE_URL); url.searchParams.set('schema', schema);
  process.env.DATABASE_URL = url.toString();
  const push = spawnSync(process.execPath, [require.resolve('prisma/build/index.js'), 'db', 'push', '--skip-generate'],
      {env: process.env, encoding: 'utf8', timeout: 60000});
  if (push.status !== 0) throw new Error('Isolated test schema setup failed');
  state = require('./dist/app');
  server = state.app.listen(0, '127.0.0.1', () => console.log('READY http://127.0.0.1:' + server.address().port + '/api'));
  process.stdin.once('data', stop); process.stdin.once('end', stop);
})().catch(async () => { console.log('FIXTURE FAILED'); await stop(); });
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development-env-file', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--report', type=Path, default=ROOT / 'output/onboarding/step5-docker-verification.json')
    args = parser.parse_args()
    values = dotenv_values(args.development_env_file)
    password = values.get('POSTGRES_PASSWORD')
    if not password: raise ValueError('A private local development DB configuration is required')
    port = int(values.get('DB_PORT', '55432'))
    schema = 'ewaste_test_step5_' + uuid.uuid4().hex
    directory = ROOT / '.test-data' / schema
    directory.mkdir(parents=True)
    admin_token = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update(TEST_DATABASE_URL=f'postgresql://ewaste:{quote(password, safe="")}@127.0.0.1:{port}/ewaste',
        EWASTE_TEST_SCHEMA=schema, STORAGE_DRIVER='local', STORAGE_DIR=str(directory / 'storage'),
        PUBLIC_API_URL='/api', ADMIN_TOKEN=admin_token, STORAGE_SECRET=secrets.token_urlsafe(32),
        ENROLLMENT_TOKEN=secrets.token_urlsafe(32), ALLOW_LEGACY_ENROLLMENT='false', NODE_ENV='test')
    server = subprocess.Popen(['node', '-e', SERVER], cwd=ROOT / 'control-plane', env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    lines = queue.Queue()
    def read_lines():
        for line in server.stdout: lines.put(line.strip())
    threading.Thread(target=read_lines, daemon=True).start()
    runtime = None
    report = {'date': datetime.now(timezone.utc).isoformat(), 'status': 'RUNNING',
        'scope': 'Automated isolated local HTTP/PostgreSQL + Docker; owner approval simulated; no physical laptop or native UI claim',
        'checks': {}, 'release': OfflineRelease().manifest}
    api_url = None
    engine = docker.from_env(timeout=15)
    try:
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            try: line = lines.get(timeout=1)
            except queue.Empty: continue
            if line.startswith('READY '): api_url = line[6:]; break
            if line == 'FIXTURE FAILED': raise RuntimeError('Test API fixture failed')
        if not api_url: raise TimeoutError('Local test API did not start')
        release = OfflineRelease()
        progress = []
        release.prepare(directory / 'worker', args.archive, threading.Event(), progress.append, force_import=True)
        report['checks']['actual_verified_archive_import'] = True
        release.prepare(directory / 'worker', None, threading.Event(), progress.append)
        report['checks']['cache_hit_without_archive'] = True
        runtime = DesktopRuntime(api_url, directory / 'worker', 'Step 5 test laptop', {'cpu': 1, 'memory_gb': 2})
        capabilities = runtime.preflight(threading.Event())
        report['checks']['pinned_docker_preflight'] = capabilities
        client = PairingClient(api_url, runtime.directory, allow_http=True)
        hardware = get_hardware_specs(capabilities); hardware['name'] = 'Step 5 test laptop'
        session = client.begin(hardware, runtime.limits)
        def admin(method, path, body=None, data=None, extra=None):
            response = requests.request(method, api_url + path, json=body, data=data,
                headers={'Authorization': 'Bearer ' + admin_token, 'Idempotency-Key': str(uuid.uuid4()), **(extra or {})},
                timeout=(5, 15), allow_redirects=False)
            response.raise_for_status(); return response.json()
        assert not runtime.running() and not client.credentials_file.exists()
        admin('POST', '/pairing/invite', {'pairing_code': session['pairing_code']})
        assert not client.credentials_file.exists()
        identity = client.decide(True)
        report['checks']['test_pairing_before_agent_launch'] = True
        photos = sorted((ROOT / 'workloads/test-data/demo').glob('*'))
        photos = [photo for photo in photos if photo.suffix.lower() in ('.jpg', '.png')]
        assert len(photos) == 10
        items = [admin('POST', '/inputs?name=' + photo.name, data=photo.read_bytes(),
            extra={'Content-Type': 'application/octet-stream'}) for photo in photos]
        job = admin('POST', '/jobs', {'name': 'Step 5 immutable offline image job', 'workload_type': 'image_inference',
            'items': items, 'chunk_size': 5, 'min_ram_gb': 2})
        runtime.start()
        observed = {}
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            result = admin('GET', f'/jobs/{job["id"]}/results')
            for container in engine.containers.list(filters={'label': 'ewaste.worker=' + str(runtime.directory)}):
                container.reload()
                options = container.attrs['HostConfig']
                assert options['NanoCpus'] == 1000000000 and options['Memory'] == 2147483648
                assert options['MemorySwap'] == options['Memory']
                assert options['ReadonlyRootfs'] and container.attrs['Config']['NetworkDisabled']
                assert container.attrs['Image'] in release.images.values()
                observed[container.id] = {'image_id': container.attrs['Image'], 'cpu': 1, 'memory_bytes': options['Memory'],
                    'attempt': container.labels['ewaste.attempt'],
                    'preflight': container.labels['ewaste.attempt'].startswith('preflight-')}
            if result['status'] == 'COMPLETED': break
            if runtime.process.poll() is not None: raise RuntimeError('Approved agent exited before job completion')
            time.sleep(0.2)
        coverage = verify_job(result, [photo.name for photo in photos])
        report['checks']['ten_photos_two_accepted_tasks'] = coverage
        report['checks']['actual_owned_container_limits'] = list(observed.values())
        assert any(not snapshot['preflight'] for snapshot in observed.values())
        report['node_id'] = identity['node_id']; report['checks']['no_global_enrollment_needed'] = True
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.with_name('step5-job-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        report['progress_stages'] = list(dict.fromkeys(progress))
        report['status'] = 'PASSED'
    except Exception:
        report['status'] = 'FAILED'
        raise
    finally:
        if runtime and runtime.running():
            runtime.request_stop(); runtime.process.wait(timeout=50)
        if runtime:
            report['owned_containers_after_stop'] = len(engine.containers.list(all=True,
                filters={'label': 'ewaste.worker=' + str(runtime.directory)}))
        engine.close()
        if server.poll() is None:
            server.stdin.write('stop\n'); server.stdin.flush()
            server.wait(timeout=20)
        while not lines.empty():
            line = lines.get_nowait()
            if line.startswith('EVIDENCE '): report['accepted_counts'] = json.loads(line[9:])
        report['fixture_exit_code'] = server.returncode
        if report['status'] == 'PASSED':
            assert report.get('accepted_counts') == {'nodes': 1, 'pairings': 1, 'tasks': 2, 'metrics': 2}
            assert server.returncode == 0
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'report': str(args.report), 'accepted_counts': report['accepted_counts']}))


if __name__ == '__main__': main()
