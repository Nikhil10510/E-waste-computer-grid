const { test } = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { PrismaClient } = require('@prisma/client');
const rootPath = path.resolve(__dirname, '..');
const cli = require.resolve('prisma/build/index.js');
function command(args, env) {
  const result = spawnSync(process.execPath, args, { cwd: rootPath, env, encoding: 'utf8', timeout: 120000 });
  assert.ifError(result.error);
  return result;
}
async function fixture(action) {
  const schema = 'ewaste_test_migration_' + randomUUID().replaceAll('-', '');
  const url = new URL(process.env.TEST_DATABASE_URL); url.searchParams.set('schema', schema);
  const env = { ...process.env, DATABASE_URL: url.toString() };
  const root = new PrismaClient({ datasources: { db: { url: process.env.TEST_DATABASE_URL } } });
  const db = new PrismaClient({ datasources: { db: { url: url.toString() } } });
  try {
    await root.$executeRawUnsafe(`CREATE SCHEMA "${schema}"`);
    await action(db, env);
  } finally {
    await db.$disconnect();
    assert.match(schema, /^ewaste_test_migration_[a-f0-9]{32}$/);
    await root.$executeRawUnsafe(`DROP SCHEMA IF EXISTS "${schema}" CASCADE`); await root.$disconnect();
  }
}
const enabled = { skip: !process.env.TEST_DATABASE_URL };
test('fresh migration deployment creates schema and reruns without changes', enabled, async () => {
  await fixture(async (db, env) => {
    for (let i = 0; i < 2; i++) { const r = command(['scripts/deploy_database.cjs'], env); assert.equal(r.status, 0, r.stdout + r.stderr); }
    assert.equal(await db.taskAttempt.count(), 0);
    const rows = await db.$queryRaw`SELECT migration_name FROM "_prisma_migrations" WHERE finished_at IS NOT NULL`;
    assert.equal(rows.length, 2);
  });
});
test('legacy db-push installation upgrades without erasing queued jobs or credentials', enabled, async () => {
  await fixture(async (db, env) => {
    let r = command([cli, 'db', 'push', '--schema', 'prisma/migrations/202610100001_baseline/schema.prisma', '--skip-generate'], env);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    const node = await db.node.create({ data: { name: 'Preserved owner', cpuCores: 4, ramGb: 8, capabilities: ['dummy'], baselinePowerW: 45 } });
    const id = randomUUID(), taskId = randomUUID();
    await db.$executeRaw`INSERT INTO "Job" (id, name, status, "totalTasks") VALUES (${id}, 'Preserved job', 'QUEUED', 1)`;
    await db.$executeRaw`INSERT INTO "Task" (id, "jobId", payload) VALUES (${taskId}, ${id}, '{"workload_type":"dummy","items":[{"name":"00000.txt","content":"data"}],"min_ram_gb":0.25}'::jsonb)`;
    r = command(['scripts/deploy_database.cjs'], env); assert.equal(r.status, 0, r.stdout + r.stderr);
    assert.equal((await db.node.findUnique({ where: { id: node.id } })).nodeSecret, node.nodeSecret);
    const job = await db.job.findUnique({ where: { id } }); assert.equal(job.name, 'Preserved job'); assert.equal(job.cancelledTasks, 0);
    assert.equal((await db.task.findUnique({ where: { id: taskId } })).status, 'QUEUED');
    assert.equal(await db.taskAttempt.count(), 0); // Never invent historical assignments.
  });
});
test('migration refuses unexpected schema drift without dropping user tables', enabled, async () => {
  await fixture(async (db, env) => {
    const r = command([cli, 'db', 'push', '--schema', 'prisma/migrations/202610100001_baseline/schema.prisma', '--skip-generate'], env);
    assert.equal(r.status, 0, r.stdout + r.stderr);
    await db.$executeRawUnsafe('CREATE TABLE "UnexpectedUserData" (value TEXT)');
    await db.$executeRawUnsafe("INSERT INTO \"UnexpectedUserData\" VALUES ('preserve me')");
    const attempted = command(['scripts/deploy_database.cjs'], env);
    assert.notEqual(attempted.status, 0); assert.match(attempted.stderr, /differs.*nothing was reset/);
    assert.deepEqual(await db.$queryRawUnsafe('SELECT * FROM "UnexpectedUserData"'), [{ value: 'preserve me' }]);
  });
});
