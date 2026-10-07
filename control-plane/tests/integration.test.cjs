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
      STORAGE_SECRET: 'integration-storage-secret', NODE_ENV: 'test',
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
      itemsProcessed: task.payload.items.length, itemsFailed: 0,
      predictions: task.payload.items.map(item => ({ image: item.name, confidence: 0.9 })), errors: [],
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
  function runWorker(suffix) {
    const python = process.env.TEST_PYTHON || path.resolve(__dirname, process.platform === 'win32' ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python');
    return new Promise((resolve, reject) => {
      const child = spawn(python, [path.resolve(__dirname, '../../worker/agent.py'), '--once'], {
        cwd: path.resolve(__dirname, '../..'), env: { ...process.env, CONTROL_PLANE_URL: base + '/api', ENROLLMENT_TOKEN: 'integration-enrollment',
          EXECUTION_MODE: 'native', DATA_DIR: path.join(temp, suffix), TEMP_EXEC_DIR: path.join(temp, suffix + '-tasks'), PYTHONUTF8: '1' },
      });
      let output = '';
      child.stdout.on('data', chunk => output += chunk); child.stderr.on('data', chunk => output += chunk);
      const timer = setTimeout(() => { child.kill(); reject(new Error('Worker timeout\n' + output)); }, 45000);
      child.on('error', error => { clearTimeout(timer); reject(error); });
      child.on('close', code => { clearTimeout(timer); code === 0 ? resolve(output) : reject(new Error(output)); });
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
  test('job creation is idempotent and validates chunk size before looping', async () => {
    const key = randomUUID(); const a = await job(['a', 'b'], {}, key); const b = await job(['a', 'b'], {}, key);
    assert.equal(a.id, b.id); assert.equal(await prisma.task.count(), 2);
    const bad = await api('POST', '/api/jobs', { workload_type: 'dummy', items: ['a'], chunk_size: -1 }, null, { 'Idempotency-Key': randomUUID() });
    assert.equal(bad.status, 400);
    assert.equal((await api('POST', '/api/jobs', { workload_type: 'dummy', items: ['different'] }, null, { 'Idempotency-Key': key })).status, 409);
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
});
