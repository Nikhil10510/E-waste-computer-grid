import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import { randomUUID } from 'node:crypto';
import { Prisma, PrismaClient, Task } from '@prisma/client';
import { config } from './config';
import { check, equalSecret, fileName, fingerprint, HttpError, number, parseJob, TaskPayload, text, validateResult, workloads } from './validation';
import { objectExists, objectPath, putObject, readResult, resultKey, signedUrl, verifySignedUrl } from './storage';

export const prisma = new PrismaClient();
export const app = express();
app.disable('x-powered-by');
app.use(cors({ origin: config.corsOrigins, exposedHeaders: ['Content-Disposition'] }));
app.use((_req, res, next) => { res.setHeader('Cache-Control', 'no-store'); next(); });

function bearer(req: Request) { return (req.headers.authorization || '').replace(/^Bearer /, ''); }
function admin(req: Request, _res: Response, next: NextFunction) {
  check(equalSecret(bearer(req), config.adminToken), 'Invalid admin token', 401); next();
}
async function worker(req: Request, res: Response, next: NextFunction) {
  const id = text(req.headers['x-node-id'], 'x-node-id');
  const node = await prisma.node.findUnique({ where: { id } });
  check(node && equalSecret(bearer(req), node.nodeSecret), 'Invalid worker credentials', 401);
  res.locals.node = node; next();
}

// Local storage follows the same expiring URL contract as S3.
app.get('/api/storage', async (req, res) => {
  check(config.storageDriver === 'local', 'Local storage disabled', 404);
  const key = text(req.query.key, 'key', 300);
  verifySignedUrl('GET', key, req.query.expires, req.query.signature);
  check(await objectExists(key), 'Object not found', 404);
  res.sendFile(objectPath(key), { dotfiles: 'allow' });
});
app.put('/api/storage', express.raw({ type: 'application/json', limit: config.maxResultBytes }), async (req, res) => {
  check(config.storageDriver === 'local', 'Local storage disabled', 404);
  const key = text(req.query.key, 'key', 300);
  verifySignedUrl('PUT', key, req.query.expires, req.query.signature);
  check(/^outputs\/[a-f0-9-]+\/[a-f0-9-]+\/[a-f0-9-]+\/result.json$/.test(key), 'Invalid output key');
  check(Buffer.isBuffer(req.body), 'Expected application/json');
  const [, jobId, taskId, leaseToken] = key.split('/');
  await prisma.$transaction(async tx => {
    await lockTask(tx, taskId);
    const task = await tx.task.findUniqueOrThrow({ where: { id: taskId } });
    check(task.jobId === jobId && task.status === 'ASSIGNED' && task.leaseToken === leaseToken && task.leaseExpiresAt! > new Date(), 'Attempt is no longer active', 409);
    await putObject(key, req.body, 'application/json');
  });
  res.status(204).end();
});
app.post('/api/inputs', admin, express.raw({ type: 'application/octet-stream', limit: config.maxFileBytes }), async (req, res) => {
  const name = fileName(req.query.name);
  check(/\.(jpe?g|png|webp|bmp)$/i.test(name), 'Upload an image file');
  check(Buffer.isBuffer(req.body) && req.body.length > 0, 'Expected nonempty application/octet-stream body');
  const key = `inputs/${randomUUID()}/${name}`;
  await putObject(key, req.body, 'application/octet-stream');
  res.status(201).json({ key, name });
});
app.use(express.json({ limit: '5mb' }));
app.get('/api/health', async (_req, res) => {
  await prisma.$queryRaw`SELECT 1`;
  res.json({ status: 'ok', storage: config.storageDriver });
});
app.post('/api/nodes/register', async (req, res) => {
  check(equalSecret(bearer(req), config.enrollmentToken), 'Invalid enrollment token', 401);
  const body = req.body || {};
  const capabilities = body.capabilities;
  check(Array.isArray(capabilities) && capabilities.length > 0 && capabilities.every(c => workloads.includes(c)), 'Invalid capabilities');
  const registrationKey = text(body.registration_key, 'registration_key', 100);
  const data = {
    name: text(body.name || 'Worker', 'name'), cpuCores: number(body.cpu_cores, 'cpu_cores', 1, 4096, true),
    ramGb: number(body.ram_gb, 'ram_gb', 0.1, 65536), os: text(body.os || 'unknown', 'os'),
    capabilities: [...new Set(capabilities)] as string[], baselinePowerW: number(body.baseline_power_w, 'baseline_power_w', 1, 10000),
  };
  const node = await prisma.node.upsert({ where: { registrationKey }, create: { ...data, registrationKey }, update: data });
  res.json({ node_id: node.id, node_secret: node.nodeSecret, status: node.status, heartbeat_interval_seconds: Math.max(1, Math.min(30, Math.floor(config.leaseMs / 3000))) });
});

type Tx = Prisma.TransactionClient;
async function lockTask(tx: Tx, taskId: string) {
  const rows = await tx.$queryRaw<{ id: string }[]>`SELECT id FROM "Task" WHERE id = ${taskId} FOR UPDATE`;
  check(rows.length, 'Task not found', 404);
}
function assertAttempt(task: Task, nodeId: string, token: unknown, active = true) {
  check(typeof token === 'string' && task.nodeId === nodeId && task.leaseToken === token, 'Stale or foreign task attempt', 409);
  if (active) check(task.status === 'ASSIGNED' && task.leaseExpiresAt && task.leaseExpiresAt > new Date(), 'Task lease expired or attempt finished', 409);
}
async function reconcileJob(tx: Tx, jobId: string) {
  // Metric inserts take foreign-key KEY SHARE locks. NO KEY UPDATE serializes
  // counters without upgrading those locks into a concurrent-completion deadlock.
  await tx.$queryRaw`SELECT id FROM "Job" WHERE id = ${jobId} FOR NO KEY UPDATE`;
  const tasks = await tx.task.findMany({ where: { jobId }, select: { status: true, result: true } });
  const completed = tasks.filter(t => t.status === 'COMPLETED');
  const failed = tasks.filter(t => t.status === 'FAILED').length;
  const terminal = completed.length + failed === tasks.length;
  const partial = failed > 0 || completed.some(t => ((t.result as any)?.itemsFailed || 0) > 0);
  const status = terminal ? (completed.length === 0 ? 'FAILED' : partial ? 'PARTIAL_SUCCESS' : 'COMPLETED') : 'IN_PROGRESS';
  await tx.job.update({ where: { id: jobId }, data: { completedTasks: completed.length, failedTasks: failed, status, completedAt: terminal ? new Date() : null } });
  return status;
}
async function failAttempt(tx: Tx, task: Task, error: string, retryable: boolean) {
  const retry = retryable && task.retryCount < config.maxRetries;
  await tx.task.update({ where: { id: task.id }, data: {
    status: retry ? 'QUEUED' : 'FAILED', leaseExpiresAt: null, lastError: error,
    retryCount: retry ? { increment: 1 } : task.retryCount,
  } });
  await reconcileJob(tx, task.jobId);
  return retry ? 'REQUEUED' : 'FAILED';
}

app.post('/api/nodes/:node_id/heartbeat', worker, async (req, res) => {
  const nodeId = res.locals.node.id;
  check(req.params.node_id === nodeId, 'Node ID mismatch', 403);
  const body = req.body || {};
  check(['IDLE', 'WORKING'].includes(body.state), 'Invalid worker state');
  let leaseExpiresAt: Date | undefined;
  const action = await prisma.$transaction(async tx => {
    await tx.$queryRaw`SELECT id FROM "Node" WHERE id = ${nodeId} FOR NO KEY UPDATE`;
    await tx.node.update({ where: { id: nodeId }, data: { lastHeartbeat: new Date(), status: body.state } });
    if (!body.active_task_id) return body.state === 'WORKING' ? 'CANCEL_TASK' : 'NONE';
    const taskId = text(body.active_task_id, 'active_task_id');
    const rows = await tx.$queryRaw<{ id: string }[]>`SELECT id FROM "Task" WHERE id = ${taskId} FOR UPDATE`;
    if (!rows.length) return 'CANCEL_TASK';
    const task = await tx.task.findUniqueOrThrow({ where: { id: taskId } });
    if (task.nodeId !== nodeId || task.leaseToken !== body.lease_token || task.status !== 'ASSIGNED' || !task.leaseExpiresAt || task.leaseExpiresAt <= new Date()) return 'CANCEL_TASK';
    const deadline = task.assignedAt!.getTime() + config.maxAttemptMs;
    if (deadline <= Date.now()) return 'CANCEL_TASK';
    leaseExpiresAt = new Date(Math.min(Date.now() + config.leaseMs, deadline));
    await tx.task.update({ where: { id: taskId }, data: { leaseExpiresAt } });
    return 'NONE';
  });
  res.json({ acknowledged: true, action, lease_expires_at: leaseExpiresAt });
});

app.post('/api/jobs', admin, async (req, res) => {
  const parsed = parseJob(req.body);
  const requestKey = text(req.headers['idempotency-key'], 'Idempotency-Key', 100);
  const requestHash = fingerprint(parsed);
  const existing = await prisma.job.findUnique({ where: { requestKey } });
  if (existing) { check(existing.requestHash === requestHash, 'Idempotency key reused with different job', 409); res.json(existing); return; }
  for (const item of parsed.items) if (item.key) check(await objectExists(item.key), `Input not found: ${item.name}`, 400);
  try {
    const job = await prisma.$transaction(async tx => {
      const job = await tx.job.create({ data: { name: parsed.name, requestKey, requestHash, status: 'QUEUED', totalTasks: Math.ceil(parsed.items.length / parsed.chunk_size) } });
      const tasks = [];
      for (let i = 0; i < parsed.items.length; i += parsed.chunk_size) tasks.push({ jobId: job.id, payload: { workload_type: parsed.workload_type, items: parsed.items.slice(i, i + parsed.chunk_size), min_ram_gb: parsed.min_ram_gb } });
      await tx.task.createMany({ data: tasks });
      return job;
    }, { timeout: 20_000 });
    res.status(201).json(job);
  } catch (e: any) {
    if (e.code !== 'P2002') throw e;
    const job = await prisma.job.findUniqueOrThrow({ where: { requestKey } });
    check(job.requestHash === requestHash, 'Idempotency key reused with different job', 409);
    res.json(job);
  }
});

app.get('/api/tasks/request', worker, async (_req, res) => {
  const nodeId = res.locals.node.id;
  const task = await prisma.$transaction(async tx => {
    await tx.$queryRaw`SELECT id FROM "Node" WHERE id = ${nodeId} FOR NO KEY UPDATE`;
    const node = await tx.node.findUniqueOrThrow({ where: { id: nodeId } });
    await tx.node.update({ where: { id: nodeId }, data: { lastHeartbeat: new Date() } });
    const active = await tx.task.findFirst({ where: { nodeId, status: 'ASSIGNED' } });
    // Recover the same assignment when the preceding HTTP response was lost.
    if (active) return active.leaseExpiresAt! > new Date() ? active : null;
    const capabilities = node.capabilities as string[];
    if (!Array.isArray(capabilities) || !capabilities.length) return null;
    const rows = await tx.$queryRaw<{ id: string }[]>`
      SELECT id FROM "Task" WHERE status = 'QUEUED'
      AND payload->>'workload_type' IN (${Prisma.join(capabilities)})
      AND COALESCE((payload->>'min_ram_gb')::numeric, 2) <= ${node.ramGb}
      ORDER BY "createdAt", id LIMIT 1 FOR UPDATE SKIP LOCKED`;
    if (!rows.length) return null;
    const task = await tx.task.update({ where: { id: rows[0].id }, data: {
      nodeId, status: 'ASSIGNED', leaseToken: randomUUID(), assignedAt: new Date(),
      leaseExpiresAt: new Date(Date.now() + Math.min(config.leaseMs, config.maxAttemptMs)),
    } });
    await tx.node.update({ where: { id: nodeId }, data: { status: 'WORKING' } });
    await tx.job.updateMany({ where: { id: task.jobId, status: 'QUEUED' }, data: { status: 'IN_PROGRESS' } });
    return task;
  });
  if (!task) { res.status(204).end(); return; }
  const payload = task.payload as unknown as TaskPayload;
  const items = await Promise.all(payload.items.map(async item => ({ ...item, download_url: item.key ? await signedUrl('GET', item.key) : undefined })));
  res.json({ task_id: task.id, job_id: task.jobId, lease_token: task.leaseToken, lease_expires_at: task.leaseExpiresAt,
    attempt_deadline: new Date(task.assignedAt!.getTime() + config.maxAttemptMs), retry_count: task.retryCount,
    payload: { ...payload, items } });
});

app.get('/api/tasks/:task_id/upload-url', worker, async (req, res) => {
  const task = await prisma.task.findUnique({ where: { id: String(req.params.task_id) } });
  check(task, 'Task not found', 404);
  assertAttempt(task, res.locals.node.id, req.headers['x-lease-token']);
  const key = resultKey(task.jobId, task.id, task.leaseToken!);
  res.json({ upload_url: await signedUrl('PUT', key), result_key: key });
});

app.post('/api/tasks/:task_id/complete', worker, async (req, res) => {
  const taskId = String(req.params.task_id);
  const token = req.body?.lease_token;
  const snapshot = await prisma.task.findUnique({ where: { id: taskId } });
  check(snapshot, 'Task not found', 404);
  assertAttempt(snapshot, res.locals.node.id, token, false);
  if (snapshot.status === 'COMPLETED') { res.json({ status: 'TASK_COMPLETED', already_completed: true }); return; }
  assertAttempt(snapshot, res.locals.node.id, token);
  const executionTimeMs = number(req.body.execution_time_ms, 'execution_time_ms', 0, config.maxAttemptMs, true);
  const energyWh = res.locals.node.baselinePowerW * executionTimeMs / 3_600_000;
  const key = resultKey(snapshot.jobId, taskId, snapshot.leaseToken!);
  check(req.body.result_key === key, 'Output does not belong to this attempt');
  check(await objectExists(key), 'Upload result before completing the task');
  const payload = snapshot.payload as unknown as TaskPayload;
  const result = validateResult(await readResult(key), payload.items.length);
  const status = await prisma.$transaction(async tx => {
    await lockTask(tx, taskId);
    const task = await tx.task.findUniqueOrThrow({ where: { id: taskId } });
    assertAttempt(task, res.locals.node.id, token, false);
    if (task.status === 'COMPLETED') return 'TASK_COMPLETED';
    assertAttempt(task, res.locals.node.id, token);
    await tx.task.update({ where: { id: taskId }, data: { status: 'COMPLETED', result: { ...result, result_key: key }, leaseExpiresAt: null, lastError: null } });
    await tx.metric.create({ data: { taskId, nodeId: task.nodeId!, jobId: task.jobId, executionTimeMs, energyWh } });
    const jobStatus = await reconcileJob(tx, task.jobId);
    return ['COMPLETED', 'PARTIAL_SUCCESS'].includes(jobStatus) ? `JOB_${jobStatus}` : 'TASK_COMPLETED';
  });
  res.json({ status });
});

app.post('/api/tasks/:task_id/fail', worker, async (req, res) => {
  const taskId = String(req.params.task_id);
  const error = text(req.body?.error, 'error', 2000);
  check(typeof req.body.retryable === 'boolean', 'retryable must be boolean');
  const status = await prisma.$transaction(async tx => {
    await lockTask(tx, taskId);
    const task = await tx.task.findUniqueOrThrow({ where: { id: taskId } });
    assertAttempt(task, res.locals.node.id, req.body.lease_token, false);
    if (task.status === 'QUEUED' || task.status === 'FAILED') return task.status === 'QUEUED' ? 'REQUEUED' : 'FAILED';
    assertAttempt(task, res.locals.node.id, req.body.lease_token);
    return failAttempt(tx, task, error, req.body.retryable);
  });
  res.json({ status });
});

app.get('/api/dashboard/sync', admin, async (_req, res) => {
  const [nodes, jobs, completed, energy, tasks] = await Promise.all([
    prisma.node.findMany({ select: { id: true, name: true, status: true, cpuCores: true, ramGb: true, capabilities: true, baselinePowerW: true, lastHeartbeat: true }, orderBy: { createdAt: 'asc' } }),
    prisma.job.findMany({ orderBy: { createdAt: 'desc' }, take: 50 }),
    prisma.task.count({ where: { status: 'COMPLETED' } }),
    prisma.metric.aggregate({ _sum: { energyWh: true, executionTimeMs: true } }),
    prisma.task.groupBy({ by: ['status'], _count: { _all: true } }),
  ]);
  const active = nodes.filter(n => n.status !== 'OFFLINE' && n.lastHeartbeat.getTime() > Date.now() - config.offlineMs);
  const displayNodes = nodes.map(n => ({ ...n, status: n.lastHeartbeat.getTime() <= Date.now() - config.offlineMs ? 'OFFLINE' : n.status }));
  res.json({ hardware: { total_nodes: nodes.length, active_nodes: active.length, available_cores: active.reduce((s, n) => s + n.cpuCores, 0), available_ram_gb: active.reduce((s, n) => s + n.ramGb, 0) },
    workloads: { total_tasks_completed: completed, recent_jobs: jobs.map(({ requestKey, requestHash, ...job }) => job), task_counts: Object.fromEntries(tasks.map(t => [t.status, t._count._all])) },
    environmental: { estimated_energy_wh: energy._sum.energyWh || 0, execution_time_ms: energy._sum.executionTimeMs || 0, metric_type: 'ESTIMATED' }, nodes: displayNodes });
});

app.get('/api/jobs/:job_id/results', admin, async (req, res) => {
  const job = await prisma.job.findUnique({ where: { id: String(req.params.job_id) }, include: { tasks: { orderBy: { createdAt: 'asc' } }, metrics: true } });
  check(job, 'Job not found', 404);
  const predictions: unknown[] = []; const errors: unknown[] = [];
  let itemsProcessed = 0; let itemsFailed = 0;
  for (const task of job.tasks) {
    const result = task.result as any;
    if (task.status === 'COMPLETED' && result) {
      itemsProcessed += result.itemsProcessed; itemsFailed += result.itemsFailed;
      predictions.push(...result.predictions.map((p: any) => ({ ...p, task_id: task.id })));
      errors.push(...result.errors.map((e: any) => ({ ...e, task_id: task.id })));
    } else if (task.status === 'FAILED') {
      itemsFailed += (task.payload as any).items.length;
      errors.push({ task_id: task.id, error: task.lastError });
    }
  }
  res.setHeader('Content-Disposition', `attachment; filename="job-${job.id}.json"`);
  res.json({ job_id: job.id, name: job.name, status: job.status, total_tasks: job.totalTasks, completed_tasks: job.completedTasks, failed_tasks: job.failedTasks,
    items_processed: itemsProcessed, items_failed: itemsFailed, predictions, errors,
    metrics: { estimated_energy_wh: job.metrics.reduce((s, m) => s + m.energyWh, 0), execution_time_ms: job.metrics.reduce((s, m) => s + m.executionTimeMs, 0), metric_type: 'ESTIMATED' } });
});

export async function sweep() {
  await prisma.node.updateMany({ where: { lastHeartbeat: { lt: new Date(Date.now() - config.offlineMs) }, status: { not: 'OFFLINE' } }, data: { status: 'OFFLINE' } });
  const expired = await prisma.task.findMany({ where: { status: 'ASSIGNED', leaseExpiresAt: { lte: new Date() } }, select: { id: true }, take: 100 });
  for (const { id } of expired) await prisma.$transaction(async tx => {
    await lockTask(tx, id);
    const task = await tx.task.findUniqueOrThrow({ where: { id } });
    if (task.status !== 'ASSIGNED' || !task.leaseExpiresAt || task.leaseExpiresAt > new Date()) return;
    await failAttempt(tx, task, 'Worker lease expired', true);
  });
}

app.use((_req, _res, next) => next(new HttpError(404, 'Endpoint not found')));
app.use((error: any, _req: Request, res: Response, _next: NextFunction) => {
  const status = error instanceof HttpError ? error.status : error.type === 'entity.too.large' ? 413 : error instanceof SyntaxError ? 400 : 500;
  if (status === 500) console.error(error);
  res.status(status).json({ error: status === 500 ? 'Internal server error' : error.message });
});
