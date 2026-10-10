// Preserve pre-migration installations. Never accept drift, reset or drop data.
const { PrismaClient } = require('@prisma/client');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
require('dotenv').config({ quiet: true });
const root = path.resolve(__dirname, '..');
const cli = require.resolve('prisma/build/index.js');
const baseline = '202610100001_baseline';
const history = '202610100002_task_history';
function run(args, capture = false) {
  const result = spawnSync(process.execPath, [cli, ...args], { cwd: root, env: process.env,
    ...(capture ? { encoding: 'utf8' } : { stdio: 'inherit' }), timeout: 120000 });
  if (result.error) throw new Error('Database command could not run');
  return result.status;
}
async function deploy() {
  if (!process.env.DATABASE_URL) throw new Error('DATABASE_URL is required');
  const schema = new URL(process.env.DATABASE_URL).searchParams.get('schema') || 'public';
  const db = new PrismaClient();
  try {
    const tables = await db.$queryRaw`SELECT table_name FROM information_schema.tables WHERE table_schema = ${schema} AND table_type = 'BASE TABLE'`;
    if (tables.length && !tables.some(t => t.table_name === '_prisma_migrations')) {
      const compare = target => run(['migrate', 'diff', '--from-schema-datasource', 'prisma/schema.prisma',
        '--to-schema-datamodel', target, '--exit-code'], true);
      const before = compare('prisma/migrations/202610100001_baseline/schema.prisma');
      const current = before === 0 ? false : compare('prisma/schema.prisma') === 0;
      if (before !== 0 && !current) throw new Error('Existing schema differs from supported baseline/current schema. Back up and review drift before migration; nothing was reset.');
      for (const migration of current ? [baseline, history] : [baseline]) {
        if (run(['migrate', 'resolve', '--applied', migration]) !== 0) throw new Error('Migration baseline recording failed');
      }
    }
  } finally { await db.$disconnect(); }
  if (run(['migrate', 'deploy']) !== 0) throw new Error('Database migration failed; server was not started');
}
if (require.main === module) deploy().catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = { deploy };
