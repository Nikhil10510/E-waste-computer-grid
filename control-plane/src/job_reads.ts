import { Prisma, PrismaClient, Task } from '@prisma/client';
import { check, number, TaskPayload } from './validation';
import { config } from './config';

export function safeError(value: unknown): string {
  let message = String(value ?? 'Execution failed').slice(0, 2000);
  for (const secret of [config.adminToken, config.enrollmentToken, config.storageSecret]) {
    if (secret) message = message.split(secret).join('[redacted]');
  }
  return message.replace(/https?:\/\/[^\s"'<>]+/gi, '[remote URL redacted]')
    .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]');
}

export function pagination(query: Record<string, unknown>) {
  const parse = (value: unknown, fallback: number, max: number, name: string) => {
    check(value === undefined || (typeof value === 'string' && /^\d+$/.test(value)), `Invalid ${name}`);
    return number(value === undefined ? fallback : Number(value), name, 1, max, true);
  };
  const page = parse(query.page, 1, 10000, 'page');
  const limit = parse(query.limit, 25, 100, 'limit');
  return { page, limit, skip: (page - 1) * limit };
}

export const publicJob = (job: { requestKey: string | null; requestHash: string | null }) => {
  const { requestKey, requestHash, ...visible } = job;
  return visible;
};

export function taskItems(task: Pick<Task, 'id' | 'status' | 'payload' | 'result' | 'lastError'>) {
  const payload = task.payload as unknown as TaskPayload;
  const result = task.result as any;
  const predictions = new Map<string, any>((result?.predictions || []).map((p: any) => [p.image, p]));
  const errors = new Map<string, any>((result?.errors || []).map((e: any) => [e.image, e]));
  return payload.items.map(item => {
    const prediction = task.status === 'COMPLETED' ? predictions.get(item.name) : undefined;
    const error = task.status === 'COMPLETED' ? errors.get(item.name)?.error : task.lastError;
    return { image: item.name, original_name: item.name.replace(/^\d{5}_/, ''), task_id: task.id,
      status: prediction ? 'PROCESSED' : task.status === 'COMPLETED' || task.status === 'FAILED' ? 'FAILED' : task.status,
      ...(prediction ? { classId: prediction.classId, className: prediction.className, confidence: prediction.confidence } : {}),
      ...(error ? { error: safeError(error) } : {}) };
  });
}

export function publicTask(task: Task & { attempts?: any[]; metric?: { executionTimeMs: number } | null }) {
  const payload = task.payload as unknown as TaskPayload;
  return { id: task.id, job_id: task.jobId, status: task.status, worker_id: task.nodeId,
    retry_count: task.retryCount, assigned_at: task.assignedAt, completed_at: task.completedAt,
    lease_expires_at: task.leaseExpiresAt, last_error: task.lastError ? safeError(task.lastError) : null,
    workload_type: payload.workload_type, item_count: payload.items.length, min_ram_gb: payload.min_ram_gb,
    execution_time_ms: task.metric?.executionTimeMs ?? null,
    attempts: task.attempts?.map(a => ({ number: a.number, worker_id: a.nodeId, worker_name: a.workerName,
      status: a.status, assigned_at: a.assignedAt, finished_at: a.finishedAt,
      execution_time_ms: a.executionTimeMs, error: a.error ? safeError(a.error) : null })) || [] };
}

export async function jobSummary(db: Prisma.TransactionClient | PrismaClient, jobId: string) {
  const job = await db.job.findUnique({ where: { id: jobId } });
  check(job, 'Job not found', 404);
  const tasks = await db.task.findMany({ where: { jobId }, select: { id: true, payload: true, result: true, status: true } });
  const metrics = await db.metric.findMany({ where: { jobId }, select: { executionTimeMs: true, energyWh: true, nodeId: true } });
  let processed = 0, failed = 0, cancelled = 0, total = 0;
  const counts: Record<string, number> = {};
  for (const task of tasks) {
    const count = (task.payload as unknown as TaskPayload).items.length;
    total += count; counts[task.status] = (counts[task.status] || 0) + 1;
    if (task.status === 'COMPLETED') {
      processed += (task.result as any)?.itemsProcessed || 0;
      failed += (task.result as any)?.itemsFailed || 0;
    } else if (task.status === 'FAILED') failed += count;
    else if (task.status === 'CANCELLED') cancelled += count;
  }
  const now = Date.now();
  const elapsed = job.startedAt ? Math.max(0, (job.completedAt?.getTime() ?? now) - job.startedAt.getTime()) : null;
  return { job: publicJob(job), task_counts: counts,
    items: { total, processed, failed, cancelled, pending: total - processed - failed - cancelled },
    timing: { queue_wait_ms: Math.max(0, (job.startedAt?.getTime() ?? job.completedAt?.getTime() ?? now) - job.createdAt.getTime()),
      elapsed_ms: elapsed, cumulative_execution_ms: metrics.reduce((sum, m) => sum + m.executionTimeMs, 0),
      throughput_items_per_second: elapsed && job.completedAt ? processed * 1000 / elapsed : null },
    metrics: { contributing_workers: new Set(metrics.map(m => m.nodeId)).size,
      estimated_energy_wh: metrics.reduce((sum, m) => sum + m.energyWh, 0), metric_type: 'ESTIMATED',
      scope: 'Accepted successful execution only; excludes retries, staging, uploads and idle host energy' },
    scheduling: { policy: 'FIFO with capability and approved RAM eligibility; one active task per worker' } };
}
