import express, { Request, Response, NextFunction } from 'express';
import cors from 'cors';
import { randomUUID } from 'node:crypto';
import { Prisma, PrismaClient, Task } from '@prisma/client';
import { config } from './config';
import { check, equalSecret, fileName, fingerprint, HttpError, number, parseJob, TaskPayload, text, validateResult } from './validation';
import { objectExists, objectPath, putObject, readResult, resultKey, signedUrl, verifySignedUrl } from './storage';
import { nodeSession, pairingRouter, parseHardware, resourceLimits } from './pairing';
import { jobSummary, pagination, publicJob, publicTask, safeError, taskItems } from './job_reads';

export const prisma = new PrismaClient();
export const app = express();
app.disable('x-powered-by');
app.use(cors({ origin: config.corsOrigins, exposedHeaders: ['Content-Disposition', 'X-Request-ID'] }));
app.use((req, res, next) => {
  res.locals.requestId = randomUUID(); res.setHeader('X-Request-ID', res.locals.requestId);
  res.once('finish', () => {
    if (res.statusCode >= 500) console.error(JSON.stringify({ event: 'request_failed', request_id: res.locals.requestId,
      method: req.method, route: req.route?.path || 'unmatched', status: res.statusCode }));
  });
  next();
});
app.use((_req, res, next) => { res.setHeader('Cache-Control', 'no-store'); next(); });

function bearer(req: Request) { return (req.headers.authorization || '').replace(/^Bearer /, ''); }
function admin(req: Request, _res: Response, next: NextFunction) {
  check(equalSecret(bearer(req), config.adminToken), 'Invalid admin token', 401); next();
}
async function worker(req: Request, res: Response, next: NextFunction) {
  const id = text(req.headers['x-node-id'], 'x-node-id');
  const node = await prisma.node.findUnique({ where: { id } });
  check(node && equalSecret(bearer(req), node.nodeSecret), 'Invalid worker credentials', 401);
  check(!node.revokedAt, 'Worker access revoked; owner approval required', 403);
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
app.use('/api', pairingRouter(prisma, admin));
app.get('/api/health', async (_req, res) => {
  await prisma.$queryRaw`SELECT 1`;
  res.json({ status: 'ok', storage: config.storageDriver });
});
app.get('/api/live', (_req, res) => res.json({ status: 'alive' }));
app.get('/api/ready', async (_req, res) => {
  try { await prisma.$queryRaw`SELECT 1`; res.json({ status: 'ready', storage: config.storageDriver }); }
  catch { res.status(503).json({ status: 'not_ready', error: 'Database unavailable', request_id: res.locals.requestId }); }
});
app.post('/api/nodes/register', async (req, res) => {
  check(config.allowLegacyEnrollment, 'Script enrollment disabled; use pairing approval', 403);
  check(equalSecret(bearer(req), config.enrollmentToken), 'Invalid enrollment token', 401);
  const body = req.body || {};
  const registrationKey = text(body.registration_key, 'registration_key', 100);
  const data = parseHardware(body);
  const node = await prisma.$transaction(async tx => {
    await tx.$queryRaw`SELECT pg_advisory_xact_lock(hashtext(${registrationKey}))::text`;
    const existing = await tx.node.findUnique({ where: { registrationKey } });
    check(!existing || (!existing.revokedAt && existing.enrollmentMode === 'legacy'), 'Worker cannot re-enroll through script enrollment', 403);
    return tx.node.upsert({ where: { registrationKey }, create: { ...data, registrationKey }, update: data });
  });
  res.json({ ...nodeSession(node), status: node.status });
});

app.get('/api/nodes/session', worker, (_req, res) => {
  const { node_secret, ...session } = nodeSession(res.locals.node);
  res.json(session);
});
app.post('/api/nodes/session', worker, async (req, res) => {
  const data = parseHardware(req.body);
  const node = await prisma.$transaction(async tx => {
    await tx.$queryRaw`SELECT id FROM "Node" WHERE id = ${res.locals.node.id} FOR NO KEY UPDATE`;
    const current = await tx.node.findUniqueOrThrow({ where: { id: res.locals.node.id } });
    check(!current.revokedAt, 'Worker access revoked', 403);
    const approved = resourceLimits(current);
    return tx.node.update({ where: { id: current.id }, data: { ...data,
      ...(approved ? { cpuLimit: Math.min(approved.cpu, data.cpuCores), memoryLimitGb: Math.min(approved.memory_gb, data.ramGb) } : {}) } });
  });
  const { node_secret, ...session } = nodeSession(node);
  res.json(session);
});

app.post('/api/nodes/:node_id/participation', worker, async (req, res) => {
  const nodeId = res.locals.node.id;
  check(req.params.node_id === nodeId, 'Node ID mismatch', 403);
  check(typeof req.body?.paused === 'boolean', 'paused must be boolean');
  check(req.body.resource_limits === undefined, 'Changing limits requires a new owner approval');
  const node = await prisma.$transaction(async tx => {
    await tx.$queryRaw`SELECT id FROM "Node" WHERE id = ${nodeId} FOR NO KEY UPDATE`;
    const current = await tx.node.findUniqueOrThrow({ where: { id: nodeId } });
    check(!current.revokedAt, 'Worker access revoked', 403);
    const active = await tx.task.findFirst({ where: { nodeId, status: 'ASSIGNED', leaseExpiresAt: { gt: new Date() } } });
    return tx.node.update({ where: { id: nodeId }, data: { paused: req.body.paused,
      status: req.body.paused ? active ? 'DRAINING' : 'PAUSED' : active ? 'WORKING' : 'IDLE' } });
  });
  const { node_secret, ...session } = nodeSession(node);
  res.json(session);
});

// An owner can revoke their own worker; the grid administrator can revoke any.
app.post('/api/nodes/:node_id/revoke', async (req, res) => {
  const nodeId = String(req.params.node_id);
  const node = await prisma.node.findUnique({ where: { id: nodeId } });
  check(node && (equalSecret(bearer(req), config.adminToken) ||
    (req.headers['x-node-id'] === nodeId && equalSecret(bearer(req), node.nodeSecret))), 'Invalid revocation credentials', 401);
  await prisma.$transaction(async tx => {
    await tx.$queryRaw`SELECT id FROM "Node" WHERE id = ${nodeId} FOR NO KEY UPDATE`;
    await tx.node.update({ where: { id: nodeId }, data: { revokedAt: node.revokedAt || new Date(), status: 'REVOKED' } });
  });
  res.json({ status: 'REVOKED' });
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
  const job = await tx.job.findUniqueOrThrow({ where: { id: jobId } });
  const tasks = await tx.task.findMany({ where: { jobId }, select: { status: true, result: true } });
  const completed = tasks.filter(t => t.status === 'COMPLETED');
  const failed = tasks.filter(t => t.status === 'FAILED').length;
  const cancelled = tasks.filter(t => t.status === 'CANCELLED').length;
  const terminal = completed.length + failed + cancelled === tasks.length;
  const partial = failed > 0 || completed.some(t => ((t.result as any)?.itemsFailed || 0) > 0);
  const status = job.status === 'CANCELLED' ? 'CANCELLED' : terminal ? (completed.length === 0 ? 'FAILED' : partial ? 'PARTIAL_SUCCESS' : 'COMPLETED') : 'IN_PROGRESS';
  await tx.job.update({ where: { id: jobId }, data: { completedTasks: completed.length, failedTasks: failed, cancelledTasks: cancelled, status, completedAt: terminal ? job.completedAt || new Date() : null } });
  return status;
}
async function failAttempt(tx: Tx, task: Task, error: string, retryable: boolean) {
  const retry = retryable && task.retryCount < config.maxRetries;
  await tx.taskAttempt.updateMany({ where: { taskId: task.id, number: task.retryCount, status: 'ASSIGNED' },
    data: { status: retry ? 'REQUEUED' : 'FAILED', finishedAt: new Date(), error: safeError(error) } });
  await tx.task.update({ where: { id: task.id }, data: {
    status: retry ? 'QUEUED' : 'FAILED', leaseExpiresAt: null, lastError: safeError(error), completedAt: retry ? null : new Date(),
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
    const node = await tx.node.findUniqueOrThrow({ where: { id: nodeId } });
    check(!node.revokedAt, 'Worker access revoked', 403);
    await tx.node.update({ where: { id: nodeId }, data: { lastHeartbeat: new Date(),
      status: node.paused ? body.active_task_id ? 'DRAINING' : 'PAUSED' : body.state } });
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
  res.json({ acknowledged: true, action, lease_expires_at: leaseExpiresAt,
    lease_remaining_ms: leaseExpiresAt ? Math.max(0, leaseExpiresAt.getTime() - Date.now()) : undefined });
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
    check(!node.revokedAt, 'Worker access revoked', 403);
    await tx.node.update({ where: { id: nodeId }, data: { lastHeartbeat: new Date() } });
    const active = await tx.task.findFirst({ where: { nodeId, status: 'ASSIGNED' } });
    // Recover the same assignment when the preceding HTTP response was lost.
    if (active) return active.leaseExpiresAt! > new Date() ? active : null;
    if (node.paused) return null;
    const capabilities = node.capabilities as string[];
    if (!Array.isArray(capabilities) || !capabilities.length) return null;
    const rows = await tx.$queryRaw<{ id: string }[]>`
      SELECT id FROM "Task" WHERE status = 'QUEUED'
      AND payload->>'workload_type' IN (${Prisma.join(capabilities)})
      AND COALESCE((payload->>'min_ram_gb')::numeric, 2) <= ${resourceLimits(node)?.memory_gb ?? node.ramGb}
      ORDER BY "createdAt", id LIMIT 1 FOR UPDATE SKIP LOCKED`;
    if (!rows.length) return null;
    const task = await tx.task.update({ where: { id: rows[0].id }, data: {
      nodeId, status: 'ASSIGNED', leaseToken: randomUUID(), assignedAt: new Date(),
      leaseExpiresAt: new Date(Date.now() + Math.min(config.leaseMs, config.maxAttemptMs)),
    } });
    await tx.taskAttempt.create({ data: { taskId: task.id, number: task.retryCount, nodeId,
      workerName: node.name, assignedAt: task.assignedAt! } });
    await tx.node.update({ where: { id: nodeId }, data: { status: 'WORKING' } });
    await tx.job.updateMany({ where: { id: task.jobId, startedAt: null }, data: { startedAt: task.assignedAt } });
    await tx.job.updateMany({ where: { id: task.jobId, status: 'QUEUED' }, data: { status: 'IN_PROGRESS' } });
    return task;
  });
  if (!task) { res.status(204).end(); return; }
  const payload = task.payload as unknown as TaskPayload;
  const items = await Promise.all(payload.items.map(async item => ({ ...item, download_url: item.key ? await signedUrl('GET', item.key) : undefined })));
  res.json({ task_id: task.id, job_id: task.jobId, lease_token: task.leaseToken, lease_expires_at: task.leaseExpiresAt,
    lease_remaining_ms: Math.max(0, task.leaseExpiresAt!.getTime() - Date.now()),
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
  const result = validateResult(await readResult(key), payload.items);
  const status = await prisma.$transaction(async tx => {
    await tx.$queryRaw`SELECT id FROM "Node" WHERE id = ${res.locals.node.id} FOR NO KEY UPDATE`;
    check(!(await tx.node.findUniqueOrThrow({ where: { id: res.locals.node.id } })).revokedAt, 'Worker access revoked', 403);
    await lockTask(tx, taskId);
    const task = await tx.task.findUniqueOrThrow({ where: { id: taskId } });
    assertAttempt(task, res.locals.node.id, token, false);
    if (task.status === 'COMPLETED') return 'TASK_COMPLETED';
    assertAttempt(task, res.locals.node.id, token);
    await tx.task.update({ where: { id: taskId }, data: { status: 'COMPLETED', result: { ...result, result_key: key }, leaseExpiresAt: null, lastError: null, completedAt: new Date() } });
    await tx.taskAttempt.updateMany({ where: { taskId, number: task.retryCount, status: 'ASSIGNED' },
      data: { status: 'COMPLETED', finishedAt: new Date(), executionTimeMs } });
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
    await tx.$queryRaw`SELECT id FROM "Node" WHERE id = ${res.locals.node.id} FOR NO KEY UPDATE`;
    check(!(await tx.node.findUniqueOrThrow({ where: { id: res.locals.node.id } })).revokedAt, 'Worker access revoked', 403);
    await lockTask(tx, taskId);
    const task = await tx.task.findUniqueOrThrow({ where: { id: taskId } });
    assertAttempt(task, res.locals.node.id, req.body.lease_token, false);
    if (task.status === 'QUEUED' || task.status === 'FAILED') return task.status === 'QUEUED' ? 'REQUEUED' : 'FAILED';
    assertAttempt(task, res.locals.node.id, req.body.lease_token);
    return failAttempt(tx, task, error, req.body.retryable);
  });
  res.json({ status });
});

app.post('/api/jobs/:job_id/cancel', admin, async (req, res) => {
  const jobId = String(req.params.job_id);
  const job = await prisma.$transaction(async tx => {
    // Match completion's Task -> Job lock order, including racing assignments.
    await tx.$queryRaw`SELECT id FROM "Task" WHERE "jobId" = ${jobId} ORDER BY id FOR UPDATE`;
    await tx.$queryRaw`SELECT id FROM "Job" WHERE id = ${jobId} FOR NO KEY UPDATE`;
    const current = await tx.job.findUnique({ where: { id: jobId } });
    check(current, 'Job not found', 404);
    if (['COMPLETED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED'].includes(current.status)) return current;
    const unfinished = await tx.task.findMany({ where: { jobId, status: { in: ['QUEUED', 'ASSIGNED'] } }, select: { id: true } });
    await tx.taskAttempt.updateMany({ where: { taskId: { in: unfinished.map(t => t.id) }, status: 'ASSIGNED' },
      data: { status: 'CANCELLED', finishedAt: new Date(), error: 'Cancelled by grid administrator' } });
    await tx.task.updateMany({ where: { jobId, status: { in: ['QUEUED', 'ASSIGNED'] } },
      data: { status: 'CANCELLED', leaseExpiresAt: null, completedAt: new Date(), lastError: 'Cancelled by grid administrator' } });
    return tx.job.update({ where: { id: jobId }, data: { status: 'CANCELLED', cancelledTasks: unfinished.length, completedAt: new Date() } });
  }, { timeout: 20_000 });
  res.json(publicJob(job));
});
app.get('/api/jobs', admin, async (req, res) => {
  const { page, limit, skip } = pagination(req.query);
  const [jobs, total] = await prisma.$transaction([
    prisma.job.findMany({ orderBy: [{ createdAt: 'desc' }, { id: 'asc' }], skip, take: limit }), prisma.job.count(),
  ], { isolationLevel: Prisma.TransactionIsolationLevel.RepeatableRead });
  res.json({ jobs: jobs.map(publicJob), total, page, limit });
});
app.get('/api/jobs/:job_id', admin, async (req, res) => {
  res.json(await prisma.$transaction(tx => jobSummary(tx, String(req.params.job_id)),
    { isolationLevel: Prisma.TransactionIsolationLevel.RepeatableRead, timeout: 20_000 }));
});
app.get('/api/jobs/:job_id/tasks', admin, async (req, res) => {
  const { page, limit, skip } = pagination(req.query);
  const jobId = String(req.params.job_id);
  check(await prisma.job.findUnique({ where: { id: jobId }, select: { id: true } }), 'Job not found', 404);
  const [tasks, total] = await prisma.$transaction([
    prisma.task.findMany({ where: { jobId }, orderBy: [{ createdAt: 'asc' }, { id: 'asc' }], skip, take: limit,
      include: { attempts: { orderBy: { number: 'desc' }, take: 10 }, metric: true } }), prisma.task.count({ where: { jobId } }),
  ], { isolationLevel: Prisma.TransactionIsolationLevel.RepeatableRead });
  res.json({ tasks: tasks.map(publicTask), total, page, limit });
});
app.get('/api/tasks/:task_id', admin, async (req, res) => {
  const { page, limit, skip } = pagination(req.query);
  const taskId = String(req.params.task_id);
  const result = await prisma.$transaction(async tx => {
    const task = await tx.task.findUnique({ where: { id: taskId }, include: { metric: true } });
    check(task, 'Task not found', 404);
    const attempts = await tx.taskAttempt.findMany({ where: { taskId }, orderBy: { number: 'asc' }, skip, take: limit });
    return { task: publicTask({ ...task, attempts }), items: taskItems(task),
      total_attempts: await tx.taskAttempt.count({ where: { taskId } }), page, limit };
  }, { isolationLevel: Prisma.TransactionIsolationLevel.RepeatableRead });
  res.json(result);
});

app.get('/api/dashboard/sync', admin, async (_req, res) => {
  const [nodes, jobs, completed, energy, tasks] = await Promise.all([
    prisma.node.findMany({ select: { id: true, name: true, status: true, cpuCores: true, ramGb: true, capabilities: true, baselinePowerW: true, lastHeartbeat: true, revokedAt: true, enrollmentMode: true, cpuLimit: true, memoryLimitGb: true, paused: true }, orderBy: { createdAt: 'asc' } }),
    prisma.job.findMany({ orderBy: { createdAt: 'desc' }, take: 50 }),
    prisma.task.count({ where: { status: 'COMPLETED' } }),
    prisma.metric.aggregate({ _sum: { energyWh: true, executionTimeMs: true } }),
    prisma.task.groupBy({ by: ['status'], _count: { _all: true } }),
  ]);
  const active = nodes.filter(n => !n.revokedAt && n.status !== 'OFFLINE' && n.lastHeartbeat.getTime() > Date.now() - config.offlineMs);
  const displayNodes = nodes.map(n => ({ ...n, status: n.revokedAt ? 'REVOKED' : n.lastHeartbeat.getTime() <= Date.now() - config.offlineMs ? 'OFFLINE' : n.status }));
  const contributing = active.filter(n => !n.paused);
  res.json({ hardware: { total_nodes: nodes.length, active_nodes: active.length, available_cores: contributing.reduce((s, n) => s + (resourceLimits(n)?.cpu ?? n.cpuCores), 0), available_ram_gb: contributing.reduce((s, n) => s + (resourceLimits(n)?.memory_gb ?? n.ramGb), 0) },
    workloads: { total_tasks_completed: completed, recent_jobs: jobs.map(publicJob), total_jobs: await prisma.job.count(), task_counts: Object.fromEntries(tasks.map(t => [t.status, t._count._all])) },
    environmental: { estimated_energy_wh: energy._sum.energyWh || 0, execution_time_ms: energy._sum.executionTimeMs || 0, metric_type: 'ESTIMATED' }, nodes: displayNodes });
});

app.get('/api/jobs/:job_id/results', admin, async (req, res) => {
  const job = await prisma.job.findUnique({ where: { id: String(req.params.job_id) }, include: { tasks: { orderBy: { createdAt: 'asc' } }, metrics: true } });
  check(job, 'Job not found', 404);
  const predictions: unknown[] = []; const errors: unknown[] = [];
  let itemsProcessed = 0; let itemsFailed = 0; let itemsCancelled = 0;
  for (const task of job.tasks) {
    const result = task.result as any;
    if (task.status === 'COMPLETED' && result) {
      itemsProcessed += result.itemsProcessed; itemsFailed += result.itemsFailed;
      predictions.push(...result.predictions.map((p: any) => ({ ...p, task_id: task.id })));
      errors.push(...result.errors.map((e: any) => ({ image: e.image, error: safeError(e.error), task_id: task.id })));
    } else if (task.status === 'FAILED') {
      itemsFailed += (task.payload as any).items.length;
      errors.push(...taskItems(task).map(item => ({ image: item.image, task_id: task.id, error: item.error, status: 'FAILED' })));
    } else if (task.status === 'CANCELLED') {
      itemsCancelled += (task.payload as any).items.length;
      errors.push(...taskItems(task).map(item => ({ image: item.image, task_id: task.id, error: item.error, status: 'CANCELLED' })));
    }
  }
  res.setHeader('Content-Disposition', `attachment; filename="job-${job.id}.json"`);
  res.json({ job_id: job.id, name: job.name, status: job.status, total_tasks: job.totalTasks, completed_tasks: job.completedTasks, failed_tasks: job.failedTasks,
    cancelled_tasks: job.cancelledTasks, items_cancelled: itemsCancelled,
    items_processed: itemsProcessed, items_failed: itemsFailed, predictions, errors,
    metrics: { estimated_energy_wh: job.metrics.reduce((s, m) => s + m.energyWh, 0), execution_time_ms: job.metrics.reduce((s, m) => s + m.executionTimeMs, 0), metric_type: 'ESTIMATED' } });
});

export async function sweep() {
  await prisma.pairingSession.deleteMany({ where: { state: { not: 'APPROVED' }, expiresAt: { lt: new Date(Date.now() - 86_400_000) } } });
  await prisma.node.updateMany({ where: { revokedAt: null, lastHeartbeat: { lt: new Date(Date.now() - config.offlineMs) }, status: { not: 'OFFLINE' } }, data: { status: 'OFFLINE' } });
  const expired = await prisma.task.findMany({ where: { status: 'ASSIGNED', leaseExpiresAt: { lte: new Date() } }, select: { id: true }, take: 100 });
  for (const { id } of expired) await prisma.$transaction(async tx => {
    await lockTask(tx, id);
    const task = await tx.task.findUniqueOrThrow({ where: { id } });
    if (task.status !== 'ASSIGNED' || !task.leaseExpiresAt || task.leaseExpiresAt > new Date()) return;
    await failAttempt(tx, task, 'Worker lease expired', true);
  });
}

app.use((_req, _res, next) => next(new HttpError(404, 'Endpoint not found')));
app.use((error: any, _req: Request, res: Response, next: NextFunction) => {
  if (res.headersSent) { next(error); return; }
  const unavailable = ['P1001', 'P1002', 'P2024', 'ENOSPC', 'EIO', 'ECONNREFUSED'].includes(error.code);
  const status = error instanceof HttpError ? error.status : error.type === 'entity.too.large' ? 413 : error instanceof SyntaxError ? 400 : unavailable ? 503 : 500;
  if (status >= 500) console.error(JSON.stringify({ event: 'operation_failed', request_id: res.locals.requestId,
    code: /^[A-Z0-9_]{1,30}$/.test(error.code || '') ? error.code : 'UNEXPECTED' }));
  res.status(status).json({ error: status >= 500 ? unavailable ? 'Dependency temporarily unavailable; retry safely' : 'Internal server error' : error.message,
    request_id: res.locals.requestId });
});
