// Disposable loopback UI fixture. Predictions are synthetic UI fixtures, not
// model accuracy evidence. No existing schema/worker/admin credentials are used.
const { randomUUID } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '../control-plane');
const { PrismaClient } = require(path.join(root, 'node_modules/@prisma/client'));
const schema = 'ewaste_test_browser_' + randomUUID().replaceAll('-', '');
const url = new URL(process.env.TEST_DATABASE_URL);
if (!['localhost', '127.0.0.1', '::1'].includes(url.hostname)) throw new Error('Use a local test database');
const db = new PrismaClient({ datasources: { db: { url: url.toString() } } });
url.searchParams.set('schema', schema);
Object.assign(process.env, { DATABASE_URL: url.toString(), NODE_ENV: 'test', ADMIN_TOKEN: 'local-browser-acceptance',
  ENROLLMENT_TOKEN: randomUUID(), STORAGE_SECRET: randomUUID(), STORAGE_DRIVER: 'local',
  STORAGE_DIR: path.resolve(__dirname, '../.test-data', schema, 'storage'), PUBLIC_API_URL: '/api',
  ALLOW_LEGACY_ENROLLMENT: 'false', CORS_ORIGINS: 'http://127.0.0.1:5179' });
let state, server, stopping = false;
async function stop() {
  if (stopping) return; stopping = true;
  if (server) await new Promise(resolve => server.close(resolve));
  if (state) await state.prisma.$disconnect();
  await db.$executeRawUnsafe(`DROP SCHEMA IF EXISTS "${schema}" CASCADE`); await db.$disconnect();
}
(async () => {
  await db.$executeRawUnsafe(`CREATE SCHEMA "${schema}"`);
  const setup = spawnSync(process.execPath, [path.join(root, 'node_modules/prisma/build/index.js'), 'db', 'push', '--skip-generate'],
    { cwd: root, env: process.env, encoding: 'utf8' });
  if (setup.status) throw new Error('Fixture schema setup failed');
  state = require(path.join(root, 'dist/app'));
  server = await new Promise(resolve => { const s = state.app.listen(0, '127.0.0.1', () => resolve(s)); });
  const base = 'http://127.0.0.1:' + server.address().port;
  async function api(method, route, body, node, extra = {}) {
    const response = await fetch(base + '/api' + route, { method, headers: { 'Content-Type': 'application/json',
      Authorization: 'Bearer ' + (node?.nodeSecret || process.env.ADMIN_TOKEN), 'Idempotency-Key': randomUUID(),
      ...(node ? { 'x-node-id': node.id } : {}), ...extra }, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!response.ok) throw new Error('Fixture API failed'); return response.json();
  }
  const nodes = await Promise.all(['Laptop A (fixture)', 'Laptop B (fixture)'].map(name => state.prisma.node.create({ data: {
    name, cpuCores: 4, ramGb: 8, capabilities: ['dummy', 'image_inference'], baselinePowerW: 45 } })));
  const job = await api('POST', '/jobs', { name: 'Browser acceptance: retry and partial output', workload_type: 'dummy', items: ['a', 'b', 'c'], chunk_size: 2 });
  const failed = await api('GET', '/tasks/request', undefined, nodes[0]);
  await api('POST', `/tasks/${failed.task_id}/fail`, { error: 'Fixture network interruption', retryable: true, lease_token: failed.lease_token }, nodes[0]);
  for (let i = 0; i < 2; i++) {
    const node = nodes[i], task = await api('GET', '/tasks/request', undefined, node);
    const last = task.payload.items.at(-1), partial = task.payload.items.length === 2;
    const result = { status: partial ? 'PARTIAL_FAILURE' : 'SUCCESS', itemsProcessed: partial ? 1 : task.payload.items.length,
      itemsFailed: partial ? 1 : 0, predictions: task.payload.items.filter(item => !partial || item !== last).map(item => ({ image: item.name, classId: 1, className: 'Synthetic UI fixture', confidence: .9 })),
      errors: partial ? [{ image: last.name, error: 'Corrupt input (fixture)' }] : [] };
    const upload = await api('GET', `/tasks/${task.task_id}/upload-url`, undefined, node, { 'x-lease-token': task.lease_token });
    const sent = await fetch(new URL(upload.upload_url, base), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result) });
    if (!sent.ok) throw new Error('Fixture upload failed');
    await api('POST', `/tasks/${task.task_id}/complete`, { lease_token: task.lease_token, result_key: upload.result_key, execution_time_ms: 1000 }, node);
  }
  for (let i = 0; i < 11; i++) await api('POST', '/jobs', { name: `Browser acceptance: waiting job ${i + 1}`, workload_type: 'dummy', items: ['a', 'b', 'c', 'd'], chunk_size: 2 });
  console.log(JSON.stringify({ api: base, token: process.env.ADMIN_TOKEN, fixture_job: job.id, scope: 'Synthetic UI-only fixture' }));
  process.stdin.once('data', () => stop().then(() => process.exit(0))); process.stdin.once('end', () => stop().then(() => process.exit(0)));
  process.on('SIGTERM', () => stop().then(() => process.exit(0)));
})().catch(async () => { console.error('Fixture failed'); await stop(); process.exit(1); });
