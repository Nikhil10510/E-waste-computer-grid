const { describe, test, before, after, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const path = require('node:path');
const fs = require('node:fs');
const { spawn, spawnSync } = require('node:child_process');

describe('real PostgreSQL and HTTP integration', { skip: !process.env.TEST_DATABASE_URL }, () => {
  let app, prisma, sweep, server, base, rootDb;
  const schema = `ewaste_test_${randomUUID().replaceAll('-', '')}`;
  const temp = path.resolve(__dirname, '../../.test-data', schema);
  before(async () => {
    const url = new URL(process.env.TEST_DATABASE_URL);
    url.searchParams.set('schema', schema);
    Object.assign(process.env, {
      DATABASE_URL: url.toString(), STORAGE_DRIVER: 'local', STORAGE_DIR: path.join(temp, 'storage'),
      PUBLIC_API_URL: '/api', ENROLLMENT_TOKEN: 'integration-enrollment', ADMIN_TOKEN: 'integration-admin',
      STORAGE_SECRET: 'integration-storage-secret', NODE_ENV: 'test', ALLOW_LEGACY_ENROLLMENT: 'true',
    });
    const { PrismaClient } = require('@prisma/client');
    rootDb = new PrismaClient();
    await rootDb.$executeRawUnsafe(`CREATE SCHEMA "${schema}"`);
    const pushed = spawnSync(process.execPath, [require.resolve('prisma/build/index.js'), 'db', 'push', '--skip-generate'], { cwd: path.resolve(__dirname, '..'), env: process.env, encoding: 'utf8' });
    assert.equal(pushed.status, 0, pushed.stdout + pushed.stderr);
    ({ app, prisma, sweep } = require('../dist/app'));
    server = await new Promise(resolve => { const s = app.listen(0, '127.0.0.1', () => resolve(s)); });
    base = `http://127.0.0.1:${server.address().port}`;
  });
  after(async () => {
    if (server) await new Promise(resolve => server.close(resolve));
    if (prisma) await prisma.$disconnect();
    if (rootDb) {
      // Only this test's generated schema is ever dropped.
      assert.match(schema, /^ewaste_test_[a-f0-9]{32}$/);
      await rootDb.$executeRawUnsafe(`DROP SCHEMA IF EXISTS "${schema}" CASCADE`);
      await rootDb.$disconnect();
    }
    if (temp.startsWith(path.resolve(__dirname, '../../.test-data') + path.sep)) fs.rmSync(temp, { recursive: true, force: true });
  });
  beforeEach(async () => {
    await prisma.pairingSession.deleteMany();
    await prisma.metric.deleteMany(); await prisma.task.deleteMany(); await prisma.job.deleteMany(); await prisma.node.deleteMany();
  });
  async function api(method, endpoint, body, node, headers = {}) {
    const r = await fetch(base + endpoint, {
      method, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${node ? node.node_secret : 'integration-admin'}`, ...(node ? { 'x-node-id': node.node_id } : {}), ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }
  async function register(overrides = {}) {
    const r = await api('POST', '/api/nodes/register', { name: 'Test worker', registration_key: randomUUID(), cpu_cores: 4, ram_gb: 8.5, os: 'test', capabilities: ['dummy', 'image_inference'], baseline_power_w: 45, ...overrides }, null, { Authorization: 'Bearer integration-enrollment' });
    assert.equal(r.status, 200, JSON.stringify(r.body)); return r.body;
  }
  const hardware = { name: 'Owner laptop', cpu_cores: 4, ram_gb: 8, os: 'windows', capabilities: ['dummy'], baseline_power_w: 45 };
  async function pairing() {
    const r = await api('POST', '/api/pairing', hardware, null, { Authorization: '' });
    assert.equal(r.status, 201, JSON.stringify(r.body)); return r.body;
  }
  function decide(session, decision = 'approve', secret = session.pairing_secret) {
    return api('POST', `/api/pairing/${session.pairing_id}/decision`, { decision }, null, { Authorization: `Bearer ${secret}` });
  }
  async function invite(session) {
    const r = await api('POST', '/api/pairing/invite', { pairing_code: session.pairing_code });
    assert.equal(r.status, 200, JSON.stringify(r.body)); return r.body;
  }
  async function job(items = ['a'], overrides = {}, key = randomUUID()) {
    const r = await api('POST', '/api/jobs', { name: 'Test job', workload_type: 'dummy', items, chunk_size: 1, ...overrides }, null, { 'Idempotency-Key': key });
    assert.ok([200, 201].includes(r.status), JSON.stringify(r.body)); return r.body;
  }
  async function take(node) {
    const r = await api('GET', '/api/tasks/request', undefined, node);
    assert.equal(r.status, 200, JSON.stringify(r.body)); return r.body;
  }
  async function upload(node, task, result) {
    const r = await api('GET', `/api/tasks/${task.task_id}/upload-url`, undefined, node, { 'x-lease-token': task.lease_token });
    assert.equal(r.status, 200, JSON.stringify(r.body));
    const uploaded = await fetch(new URL(r.body.upload_url, base), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result || {
      status: 'SUCCESS', itemsProcessed: task.payload.items.length, itemsFailed: 0,
      predictions: task.payload.items.map(item => ({ image: item.name, classId: 1, className: 'dummy_class_1', confidence: 0.9 })), errors: [],
    }) });
    assert.equal(uploaded.status, 204, await uploaded.text());
    return r.body;
  }
  function complete(node, task, result_key) {
    return api('POST', `/api/tasks/${task.task_id}/complete`, { lease_token: task.lease_token, execution_time_ms: 1000, result_key }, node);
  }
  async function input(name, data) {
    const r = await fetch(base + '/api/inputs?name=' + name, { method: 'POST', headers: { Authorization: 'Bearer integration-admin', 'Content-Type': 'application/octet-stream' }, body: data });
    assert.equal(r.status, 201); return r.json();
  }
  function runWorker(suffix, approvedOnly = false) {
    const python = process.env.TEST_PYTHON || path.resolve(__dirname, process.platform === 'win32' ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python');
    return new Promise((resolve, reject) => {
      const child = spawn(python, [path.resolve(__dirname, '../../worker/agent.py'), '--once'], {
        cwd: path.resolve(__dirname, '../..'), env: { ...process.env, CONTROL_PLANE_URL: base + '/api', ENROLLMENT_TOKEN: 'integration-enrollment',
          EXECUTION_MODE: 'native', DATA_DIR: path.join(temp, suffix), TEMP_EXEC_DIR: path.join(temp, suffix + '-tasks'), PYTHONUTF8: '1',
          REQUIRE_PAIRED_IDENTITY: approvedOnly ? 'true' : 'false',
          ...(approvedOnly ? { ENROLLMENT_TOKEN: 'invalid-and-not-needed' } : {}) },
      });
      let output = '';
      child.stdout.on('data', chunk => output += chunk); child.stderr.on('data', chunk => output += chunk);
      const timer = setTimeout(() => { child.kill(); reject(new Error('Worker timeout\n' + output)); }, 45000);
      child.on('error', error => { clearTimeout(timer); reject(error); });
      child.on('close', code => { clearTimeout(timer); code === 0 ? resolve(output) : reject(new Error(output)); });
    });
  }
  function runPairingClient(suffix, operation) {
    const python = process.env.TEST_PYTHON;
    assert.ok(python, 'TEST_PYTHON must point to the current fresh Python runtime');
    const code = `import json, os, sys\nfrom pathlib import Path\nsys.path.insert(0, ${JSON.stringify(path.resolve(__dirname, '../../worker'))})\nfrom pairing_client import PairingClient\nfrom hardware import get_hardware_specs\nclient = PairingClient(os.environ['CONTROL_PLANE_URL'], os.environ['DATA_DIR'], allow_http=True)\ndata = client.begin(get_hardware_specs(['dummy'])) if ${operation === 'begin' ? 'True' : 'False'} else client.decide(${operation === 'approve' ? 'True' : 'False'})\nprint(json.dumps({k: data[k] for k in ('pairing_id', 'pairing_code', 'state', 'node_id') if k in data}))`;
    // This server runs in the same Node event loop: a synchronous child would
    // block the API that the Python client is waiting for.
    return new Promise((resolve, reject) => {
      const child = spawn(python, ['-c', code], {
        env: { ...process.env, CONTROL_PLANE_URL: base + '/api', DATA_DIR: path.join(temp, suffix), PYTHONUTF8: '1' } });
      let stdout = '', stderr = '';
      child.stdout.on('data', chunk => stdout += chunk); child.stderr.on('data', chunk => stderr += chunk);
      const timer = setTimeout(() => { child.kill(); reject(new Error('Pairing client timeout')); }, 30000);
      child.on('error', error => { clearTimeout(timer); reject(error); });
      child.on('close', status => {
        clearTimeout(timer);
        if (status !== 0) { reject(new Error(stderr)); return; }
        try { resolve(JSON.parse(stdout)); } catch (error) { reject(error); }
      });
    });
  }

  test('authentication, idempotent enrollment, fractional RAM, and secret-safe dashboard', async () => {
    assert.equal((await api('GET', '/api/dashboard/sync', undefined, null, { Authorization: 'Bearer wrong' })).status, 401);
    const key = randomUUID(); const a = await register({ registration_key: key }); const b = await register({ registration_key: key });
    assert.equal(a.node_id, b.node_id);
    const data = (await api('GET', '/api/dashboard/sync')).body;
    assert.equal(data.nodes.length, 1); assert.equal(data.nodes[0].ramGb, 8.5);
    assert.ok(!JSON.stringify(data).includes(a.node_secret));
    assert.equal((await api('GET', '/api/tasks/request', undefined, { ...a, node_secret: 'wrong' })).status, 401);
  });
  test('pairing requires authenticated invitation AND laptop approval before enrollment', async () => {
    const session = await pairing();
    assert.equal(session.state, 'WAITING'); assert.match(session.pairing_code, /^[A-Za-z0-9_-]{8}$/);
    assert.equal(await prisma.node.count(), 0);
    assert.equal((await decide(session)).status, 409);
    assert.equal((await api('POST', '/api/pairing/invite', { pairing_code: session.pairing_code }, null, { Authorization: 'Bearer wrong' })).status, 401);
    assert.equal((await invite(session)).state, 'INVITED');
    assert.equal(await prisma.node.count(), 0);
    assert.equal((await decide(session, 'approve', session.pairing_code)).status, 401);
    assert.equal((await api('GET', '/api/tasks/request', undefined, { node_id: session.pairing_id, node_secret: session.pairing_secret })).status, 401);
    const saved = await prisma.pairingSession.findUnique({ where: { id: session.pairing_id } });
    assert.notEqual(saved.codeHash, session.pairing_code); assert.notEqual(saved.secretHash, session.pairing_secret);
  });
  test('concurrent approval and lost-response retries create exactly one usable worker', async () => {
    const session = await pairing(); await Promise.all([invite(session), invite(session)]);
    const replies = await Promise.all(Array.from({ length: 6 }, () => decide(session)));
    assert.ok(replies.every(r => r.status === 200), JSON.stringify(replies));
    assert.equal(new Set(replies.map(r => r.body.node_id)).size, 1);
    assert.equal(new Set(replies.map(r => r.body.node_secret)).size, 1);
    assert.equal(await prisma.node.count(), 1);
    const node = replies[0].body;
    assert.equal(node.enrollment_mode, 'paired');
    const poll = await api('GET', `/api/pairing/${session.pairing_id}`, undefined, null, { Authorization: `Bearer ${session.pairing_secret}` });
    assert.equal(poll.body.state, 'APPROVED');
    const dashboard = await api('GET', '/api/dashboard/sync');
    for (const value of [node.node_secret, session.pairing_code, session.pairing_secret]) {
      assert.ok(!JSON.stringify(poll.body).includes(value)); assert.ok(!JSON.stringify(dashboard.body).includes(value));
    }
    const resumed = await api('POST', '/api/nodes/session', { ...hardware, capabilities: ['dummy', 'image_inference'] }, node);
    assert.equal(resumed.status, 200); assert.equal(resumed.body.node_id, node.node_id);
    assert.equal(resumed.body.node_secret, undefined);
    await job(); assert.ok((await take(node)).task_id);
    assert.equal((await decide(session, 'decline')).status, 409);
  });
  test('declined and expired invitations cannot issue worker credentials', async () => {
    const declined = await pairing(); await invite(declined);
    assert.equal((await decide(declined, 'decline')).body.state, 'DECLINED');
    assert.equal((await decide(declined, 'decline')).status, 200);
    assert.equal((await decide(declined)).status, 409);
    const expired = await pairing(); await invite(expired);
    await prisma.pairingSession.update({ where: { id: expired.pairing_id }, data: { expiresAt: new Date(Date.now() - 1) } });
    const poll = await api('GET', `/api/pairing/${expired.pairing_id}`, undefined, null, { Authorization: `Bearer ${expired.pairing_secret}` });
    assert.equal(poll.body.state, 'EXPIRED');
    assert.equal((await decide(expired)).status, 410);
    assert.equal((await api('POST', '/api/pairing/invite', { pairing_code: expired.pairing_code })).status, 404);
    assert.equal(await prisma.node.count(), 0);
  });
  test('revocation blocks work, credential recovery, and shared-token re-enrollment', async () => {
    const session = await pairing(); await invite(session); const node = (await decide(session)).body;
    const other = await register();
    assert.equal((await api('POST', `/api/nodes/${node.node_id}/revoke`, {}, other)).status, 401);
    const revoked = await api('POST', `/api/nodes/${node.node_id}/revoke`, {}, node);
    assert.equal(revoked.body.status, 'REVOKED');
    assert.equal((await api('POST', `/api/nodes/${node.node_id}/revoke`, {}, node)).status, 200);
    assert.equal((await api('GET', '/api/tasks/request', undefined, node)).status, 403);
    assert.equal((await api('POST', '/api/nodes/session', hardware, node)).status, 403);
    assert.equal((await decide(session)).status, 403);
    const saved = await prisma.node.findUnique({ where: { id: node.node_id } });
    const reenrolled = await api('POST', '/api/nodes/register', { ...hardware, registration_key: saved.registrationKey }, null, { Authorization: 'Bearer integration-enrollment' });
    assert.equal(reenrolled.status, 403);
    await prisma.node.update({ where: { id: node.node_id }, data: { lastHeartbeat: new Date(0) } });
    await sweep();
    const dash = (await api('GET', '/api/dashboard/sync')).body;
    assert.equal(dash.nodes.find(n => n.id === node.node_id).status, 'REVOKED');
    assert.equal(dash.hardware.active_nodes, 1);
  });
  test('legacy enrollment can be disabled without preventing approved worker reconnects', async () => {
    const session = await pairing(); await invite(session); const node = (await decide(session)).body;
    const { config } = require('../dist/config'); const previous = config.allowLegacyEnrollment;
    try {
      config.allowLegacyEnrollment = false;
      const r = await api('POST', '/api/nodes/register', { ...hardware, registration_key: randomUUID() }, null, { Authorization: 'Bearer integration-enrollment' });
      assert.equal(r.status, 403);
      assert.equal((await api('POST', '/api/nodes/session', hardware, node)).status, 200);
    } finally { config.allowLegacyEnrollment = previous; }
  });
  test('real owner-side pairing client saves approval and starts the existing agent without an enrollment token', async () => {
    const session = await runPairingClient('owner-client', 'begin');
    assert.equal(await prisma.node.count(), 0);
    assert.ok(!fs.existsSync(path.join(temp, 'owner-client', 'credentials.json')));
    await invite(session);
    const approved = await runPairingClient('owner-client', 'approve');
    assert.equal(approved.state, 'APPROVED');
    const saved = JSON.parse(fs.readFileSync(path.join(temp, 'owner-client', 'credentials.json'), 'utf8'));
    assert.equal(saved.node_id, approved.node_id); assert.equal(saved.control_plane_url, base + '/api');
    const j = await job(['owner-approved compute']);
    await runWorker('owner-client', true);
    const result = (await api('GET', `/api/jobs/${j.id}/results`)).body;
    assert.equal(result.status, 'COMPLETED'); assert.equal(result.items_processed, 1);
    assert.equal(await prisma.node.count(), 1);
    assert.equal((await prisma.task.findFirst()).nodeId, approved.node_id);
  });
  test('real owner-side decline leaves no runnable credential file or worker node', async () => {
    const session = await runPairingClient('declining-client', 'begin'); await invite(session);
    assert.equal((await runPairingClient('declining-client', 'decline')).state, 'DECLINED');
    assert.ok(!fs.existsSync(path.join(temp, 'declining-client', 'credentials.json')));
    assert.equal(await prisma.node.count(), 0);
  });
  test('revoking an existing script worker prevents re-enrollment and rejects active output', async () => {
    const key = randomUUID(); const node = await register({ registration_key: key });
    await job(); const task = await take(node); const output = await upload(node, task);
    assert.equal((await api('POST', `/api/nodes/${node.node_id}/revoke`, {})).status, 200);
    assert.equal((await complete(node, task, output.result_key)).status, 403);
    assert.equal(await prisma.metric.count(), 0);
    const reenrolled = await api('POST', '/api/nodes/register', { ...hardware, registration_key: key }, null, { Authorization: 'Bearer integration-enrollment' });
    assert.equal(reenrolled.status, 403);
    await prisma.task.update({ where: { id: task.task_id }, data: { leaseExpiresAt: new Date(Date.now() - 1) } });
    await sweep();
    assert.equal((await prisma.task.findUnique({ where: { id: task.task_id } })).status, 'QUEUED');
    const healthy = await register(); const recovered = await take(healthy);
    assert.equal(recovered.task_id, task.task_id); assert.notEqual(recovered.lease_token, task.lease_token);
  });
  test('the additive SQL upgrade retains existing worker data and adds pairing tables', async () => {
    const upgradeSchema = `ewaste_upgrade_${randomUUID().replaceAll('-', '')}`;
    assert.match(upgradeSchema, /^ewaste_upgrade_[a-f0-9]{32}$/);
    await rootDb.$executeRawUnsafe(`CREATE SCHEMA "${upgradeSchema}"`);
    try {
      await rootDb.$transaction(async tx => {
        await tx.$executeRawUnsafe(`SET LOCAL search_path TO "${upgradeSchema}"`);
        await tx.$executeRawUnsafe(`CREATE TABLE "Node" (LIKE "${schema}"."Node" INCLUDING ALL)`);
        await tx.$executeRawUnsafe('ALTER TABLE "Node" DROP COLUMN "enrollmentMode", DROP COLUMN "revokedAt", DROP COLUMN "cpuLimit", DROP COLUMN "memoryLimitGb", DROP COLUMN "paused"');
        await tx.$executeRaw`INSERT INTO "Node" (id, "nodeSecret", "cpuCores", "ramGb", capabilities, "baselinePowerW") VALUES ('existing-worker', 'existing-secret', 4, 8.5, '["dummy"]', 45)`;
        const sql = ['20261009_pairing.sql', '20261009_resource_policy.sql'].map(file => fs.readFileSync(path.resolve(__dirname, '../prisma/changes', file), 'utf8')).join('\n');
        const statements = sql.replace(/--[^\n]*/g, '').split(';').map(s => s.trim()).filter(s => s && !['BEGIN', 'COMMIT'].includes(s));
        for (const statement of statements) await tx.$executeRawUnsafe(statement);
        const rows = await tx.$queryRaw`SELECT id, "nodeSecret", "ramGb", "enrollmentMode", "revokedAt" FROM "Node"`;
        assert.deepEqual(rows, [{ id: 'existing-worker', nodeSecret: 'existing-secret', ramGb: 8.5, enrollmentMode: 'legacy', revokedAt: null }]);
        assert.deepEqual(await tx.$queryRaw`SELECT id FROM "PairingSession"`, []);
      });
    } finally {
      await rootDb.$executeRawUnsafe(`DROP SCHEMA "${upgradeSchema}" CASCADE`);
    }
  });
  test('job creation is idempotent and validates chunk size before looping', async () => {
    const key = randomUUID(); const a = await job(['a', 'b'], {}, key); const b = await job(['a', 'b'], {}, key);
    assert.equal(a.id, b.id); assert.equal(await prisma.task.count(), 2);
    const bad = await api('POST', '/api/jobs', { workload_type: 'dummy', items: ['a'], chunk_size: -1 }, null, { 'Idempotency-Key': randomUUID() });
    assert.equal(bad.status, 400);
    assert.equal((await api('POST', '/api/jobs', { workload_type: 'dummy', items: ['different'] }, null, { 'Idempotency-Key': key })).status, 409);
  });
  test('owner limits are bounded, frozen on approval retries and used for assignment eligibility', async () => {
    const session = await pairing(); await invite(session);
    const decision = limits => api('POST', `/api/pairing/${session.pairing_id}/decision`, { decision: 'approve', resource_limits: limits }, null, { Authorization: `Bearer ${session.pairing_secret}` });
    assert.equal((await decision({ cpu: 5, memory_gb: 1 })).status, 400);
    const approved = await decision({ cpu: 0.5, memory_gb: 0.5 });
    assert.equal(approved.status, 200); const node = approved.body;
    assert.deepEqual(node.resource_limits, { cpu: 0.5, memory_gb: 0.5 });
    assert.equal((await decision({ cpu: 2, memory_gb: 2 })).status, 409);
    await job(['too large'], { min_ram_gb: 1 });
    const small = await job(['fits'], { min_ram_gb: 0.25 });
    const task = await take(node); assert.equal(task.job_id, small.id);
    const output = await upload(node, task); assert.equal((await complete(node, task, output.result_key)).status, 200);
    assert.equal((await api('GET', '/api/tasks/request', undefined, node)).status, 204);
    const refreshed = await api('POST', '/api/nodes/session', { ...hardware, resource_limits: { cpu: 64, memory_gb: 64 } }, node);
    assert.deepEqual(refreshed.body.resource_limits, { cpu: 0.5, memory_gb: 0.5 });
  });
  test('pause drains active work, persists across a real worker restart, and resume admits new work', async () => {
    const session = await pairing(); await invite(session); const node = (await decide(session)).body;
    const j = await job(['first', 'second']); const first = await take(node);
    const pause = paused => api('POST', `/api/nodes/${node.node_id}/participation`, { paused }, node);
    const foreign = await register();
    assert.equal((await api('POST', `/api/nodes/${node.node_id}/participation`, { paused: true }, foreign)).status, 403);
    assert.equal((await pause('true')).status, 400);
    const paused = await pause(true); assert.equal(paused.body.paused, true); assert.equal(paused.body.status, 'DRAINING');
    assert.equal((await take(node)).task_id, first.task_id);
    const beat = await api('POST', `/api/nodes/${node.node_id}/heartbeat`, { state: 'WORKING', active_task_id: first.task_id, lease_token: first.lease_token }, node);
    assert.equal(beat.body.action, 'NONE');
    const output = await upload(node, first); await complete(node, first, output.result_key);
    await api('POST', `/api/nodes/${node.node_id}/heartbeat`, { state: 'IDLE' }, node);
    assert.equal((await api('GET', '/api/tasks/request', undefined, node)).status, 204);
    const directory = path.join(temp, 'paused-worker'); fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, 'credentials.json'), JSON.stringify({ node_id: node.node_id, node_secret: node.node_secret, registration_key: randomUUID(), control_plane_url: base + '/api' }));
    await runWorker('paused-worker', true);
    assert.equal((await prisma.node.findUnique({ where: { id: node.node_id } })).paused, true);
    assert.equal(await prisma.metric.count(), 1);
    const resumed = await pause(false); assert.equal(resumed.body.paused, false);
    const second = await take(node); const nextOutput = await upload(node, second); await complete(node, second, nextOutput.result_key);
    assert.equal((await prisma.job.findUnique({ where: { id: j.id } })).status, 'COMPLETED');
  });
  test('concurrent polls never assign the same task to two workers', async () => {
    const workers = await Promise.all(Array.from({ length: 8 }, () => register()));
    const j = await job(Array.from({ length: 8 }, (_, i) => String(i)));
    const tasks = await Promise.all(workers.map(take));
    assert.equal(new Set(tasks.map(t => t.task_id)).size, 8);
    const replay = await take(workers[0]); assert.equal(replay.task_id, tasks[0].task_id); assert.equal(replay.lease_token, tasks[0].lease_token);
    assert.equal((await prisma.job.findUnique({ where: { id: j.id } })).status, 'IN_PROGRESS');
    const results = await Promise.all(tasks.map((task, i) => upload(workers[i], task)));
    const completed = await Promise.all(tasks.map((task, i) => complete(workers[i], task, results[i].result_key)));
    assert.ok(completed.every(r => r.status === 200), JSON.stringify(completed));
    const final = await prisma.job.findUnique({ where: { id: j.id } });
    assert.equal(final.status, 'COMPLETED'); assert.equal(final.completedTasks, 8);
  });
  test('capability and RAM filters leave incompatible tasks queued', async () => {
    const node = await register({ capabilities: ['dummy'], ram_gb: 1 });
    await job(['a'], { min_ram_gb: 4 });
    assert.equal((await api('GET', '/api/tasks/request', undefined, node)).status, 204);
    const img = await input('cat.png', Buffer.from('test'));
    await job([img], { workload_type: 'image_inference', min_ram_gb: 0.5 });
    assert.equal((await api('GET', '/api/tasks/request', undefined, node)).status, 204);
  });
  test('concurrent duplicate completions count metrics exactly once and freeze accepted output', async () => {
    const node = await register(); const j = await job(); const task = await take(node); const out = await upload(node, task);
    const replies = await Promise.all(Array.from({ length: 6 }, () => complete(node, task, out.result_key)));
    assert.ok(replies.every(r => r.status === 200), JSON.stringify(replies));
    assert.equal(await prisma.metric.count(), 1);
    assert.equal((await prisma.job.findUnique({ where: { id: j.id } })).completedTasks, 1);
    const overwritten = await fetch(new URL(out.upload_url, base), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    assert.equal(overwritten.status, 409);
    const aggregate = (await api('GET', `/api/jobs/${j.id}/results`)).body;
    assert.equal(aggregate.predictions.length, 1);
    assert.equal(aggregate.metrics.estimated_energy_wh, 45 / 3600);
  });
  test('wrong-image results are rejected without accepting task or metric', async () => {
    const node = await register(); const j = await job(['first', 'second'], { chunk_size: 2 }); const task = await take(node);
    const bad = await upload(node, task, { status: 'PARTIAL_FAILURE', itemsProcessed: 1, itemsFailed: 1,
      predictions: [{ image: task.payload.items[0].name, classId: 1, className: 'dummy_class_1', confidence: 0.9 }],
      errors: [{ image: 'unassigned.txt', error: 'Bad image' }] });
    assert.equal((await complete(node, task, bad.result_key)).status, 400);
    assert.equal((await prisma.task.findUnique({ where: { id: task.task_id } })).status, 'ASSIGNED');
    assert.equal(await prisma.metric.count(), 0);
    assert.equal((await prisma.job.findUnique({ where: { id: j.id } })).completedTasks, 0);
    const good = await upload(node, task);
    assert.equal((await complete(node, task, good.result_key)).status, 200);
  });
  test('expired leases cannot be revived and old attempts from the same node are rejected', async () => {
    const node = await register(); await job(); const old = await take(node);
    await prisma.task.update({ where: { id: old.task_id }, data: { leaseExpiresAt: new Date(Date.now() - 1) } });
    const heartbeat = await api('POST', `/api/nodes/${node.node_id}/heartbeat`, { state: 'WORKING', active_task_id: old.task_id, lease_token: old.lease_token }, node);
    assert.equal(heartbeat.body.action, 'CANCEL_TASK');
    await Promise.all([sweep(), sweep()]);
    const next = await take(node); assert.equal(next.task_id, old.task_id); assert.notEqual(next.lease_token, old.lease_token); assert.equal(next.retry_count, 1);
    assert.equal((await complete(node, old, 'invalid')).status, 409);
    assert.equal((await api('GET', `/api/tasks/${old.task_id}/upload-url`, undefined, node, { 'x-lease-token': old.lease_token })).status, 409);
    await prisma.task.update({ where: { id: next.task_id }, data: { leaseExpiresAt: new Date(Date.now() + 1000) } });
    const alive = await api('POST', `/api/nodes/${node.node_id}/heartbeat`, { state: 'WORKING', active_task_id: next.task_id, lease_token: next.lease_token }, node);
    assert.equal(alive.body.action, 'NONE'); assert.ok(Date.parse(alive.body.lease_expires_at) > Date.now() + 1000);
  });
  test('failures retry only three times and leave a terminal FAILED job', async () => {
    const node = await register(); const j = await job();
    for (let attempt = 0; attempt < 4; attempt++) {
      const task = await take(node);
      const body = { lease_token: task.lease_token, error: 'Poison input', retryable: true };
      const replies = await Promise.all([api('POST', `/api/tasks/${task.task_id}/fail`, body, node), api('POST', `/api/tasks/${task.task_id}/fail`, body, node)]);
      assert.ok(replies.every(r => r.status === 200));
      assert.equal(replies[0].body.status, attempt < 3 ? 'REQUEUED' : 'FAILED');
    }
    const finished = await prisma.job.findUnique({ where: { id: j.id } });
    assert.equal(finished.status, 'FAILED'); assert.equal(finished.failedTasks, 1);
    assert.equal((await api('GET', '/api/tasks/request', undefined, node)).status, 204);
  });
  test('mixed completed and failed tasks produce downloadable partial results', async () => {
    const node = await register(); const j = await job(['a', 'b']);
    const first = await take(node); const output = await upload(node, first); await complete(node, first, output.result_key);
    const second = await take(node);
    await api('POST', `/api/tasks/${second.task_id}/fail`, { lease_token: second.lease_token, error: 'Corrupt input', retryable: false }, node);
    const result = (await api('GET', `/api/jobs/${j.id}/results`)).body;
    assert.equal(result.status, 'PARTIAL_SUCCESS'); assert.equal(result.items_processed, 1); assert.equal(result.items_failed, 1);
  });
  test('hard attempt deadline prevents a hung worker extending its lease forever', async () => {
    const node = await register(); await job(); const task = await take(node);
    await prisma.task.update({ where: { id: task.task_id }, data: { assignedAt: new Date(Date.now() - 1_000_000) } });
    const reply = await api('POST', `/api/nodes/${node.node_id}/heartbeat`, { state: 'WORKING', active_task_id: task.task_id, lease_token: task.lease_token }, node);
    assert.equal(reply.body.action, 'CANCEL_TASK');
  });
  test('real Python workers execute separate tasks and upload results', async () => {
    const j = await job(['one', 'two', 'three', 'four'], { chunk_size: 2 });
    await Promise.all([runWorker('one'), runWorker('two')]);
    const result = (await api('GET', `/api/jobs/${j.id}/results`)).body;
    assert.equal(result.status, 'COMPLETED', JSON.stringify(result)); assert.equal(result.items_processed, 4);
    assert.equal(await prisma.node.count(), 2); assert.equal(await prisma.metric.count(), 2);
  });
  test('real image inference isolates corrupt input and returns PARTIAL_SUCCESS', async () => {
    const valid = await input('cat.jpg', fs.readFileSync(path.resolve(__dirname, '../../workloads/test-data/sample/cat.jpg')));
    const corrupt = await input('broken.jpg', Buffer.from('not an image'));
    const j = await job([valid, corrupt], { workload_type: 'image_inference', chunk_size: 2 });
    await runWorker('image-worker');
    const result = (await api('GET', `/api/jobs/${j.id}/results`)).body;
    assert.equal(result.status, 'PARTIAL_SUCCESS', JSON.stringify(result)); assert.equal(result.items_processed, 1); assert.equal(result.items_failed, 1);
    assert.equal(result.predictions.length, 1); assert.equal(result.errors.length, 1);
  });
  test('ten genuine demo photos execute as two tasks with exact input accounting', async () => {
    const directory = path.resolve(__dirname, '../../workloads/test-data/demo');
    const names = fs.readdirSync(directory).filter(name => /\.(png|jpg)$/i.test(name)).sort();
    assert.equal(names.length, 10);
    const items = await Promise.all(names.map(name => input(name, fs.readFileSync(path.join(directory, name)))));
    const j = await job(items, { workload_type: 'image_inference', chunk_size: 5 });
    await Promise.all([runWorker('photo-one'), runWorker('photo-two')]);
    const result = (await api('GET', `/api/jobs/${j.id}/results`)).body;
    assert.equal(result.status, 'COMPLETED', JSON.stringify(result));
    assert.equal(result.completed_tasks, 2); assert.equal(result.items_processed, 10); assert.equal(result.items_failed, 0);
    const expected = names.map((name, i) => `${String(i).padStart(5, '0')}_${name}`);
    assert.deepEqual(result.predictions.map(p => p.image).sort(), expected.sort());
    assert.equal(await prisma.metric.count(), 2);
  });
});
