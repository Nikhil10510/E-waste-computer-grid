import { Router, RequestHandler } from 'express';
import { randomBytes, createHash, randomUUID } from 'node:crypto';
import { Prisma, PrismaClient, PairingSession } from '@prisma/client';
import { config } from './config';
import { check, equalSecret, number, text, workloads } from './validation';

const hash = (value: string) => createHash('sha256').update(value).digest('hex');

export function parseHardware(body: any) {
  check(body && typeof body === 'object' && !Array.isArray(body), 'Expected worker hardware');
  const capabilities = body.capabilities;
  check(Array.isArray(capabilities) && capabilities.length > 0 && capabilities.every(c => workloads.includes(c)), 'Invalid capabilities');
  return {
    name: text(body.name || 'Worker', 'name'), cpuCores: number(body.cpu_cores, 'cpu_cores', 1, 4096, true),
    ramGb: number(body.ram_gb, 'ram_gb', 0.1, 65536), os: text(body.os || 'unknown', 'os'),
    capabilities: [...new Set(capabilities)] as string[], baselinePowerW: number(body.baseline_power_w, 'baseline_power_w', 1, 10000),
  };
}

export function parseResourceLimits(value: any, hardware: { cpuCores: number; ramGb: number }) {
  const limits = value === undefined ? { cpu: Math.min(2, hardware.cpuCores), memory_gb: Math.min(2, hardware.ramGb) } : value;
  check(limits && typeof limits === 'object' && !Array.isArray(limits), 'Invalid resource_limits');
  return { cpuLimit: number(limits.cpu, 'CPU limit', 0.25, Math.min(64, hardware.cpuCores)),
    memoryLimitGb: number(limits.memory_gb, 'RAM limit', 0.25, hardware.ramGb) };
}

export function resourceLimits(node: { cpuLimit: number | null; memoryLimitGb: number | null; cpuCores: number; ramGb: number; enrollmentMode: string }) {
  if (node.enrollmentMode === 'legacy' && node.cpuLimit === null) return null;
  return { cpu: Math.min(node.cpuLimit ?? 2, node.cpuCores), memory_gb: Math.min(node.memoryLimitGb ?? 2, node.ramGb) };
}

export function nodeSession(node: { id: string; nodeSecret: string; enrollmentMode: string; status: string; paused: boolean; cpuLimit: number | null; memoryLimitGb: number | null; cpuCores: number; ramGb: number }) {
  return { node_id: node.id, node_secret: node.nodeSecret, enrollment_mode: node.enrollmentMode,
    paused: node.paused, status: node.status, resource_limits: resourceLimits(node),
    heartbeat_interval_seconds: Math.max(1, Math.min(30, Math.floor(config.leaseMs / 3000))) };
}

// A bounded, per-process limit. Multi-instance deployments must also enforce
// shared limits at their gateway; never trust client-supplied X-Forwarded-For.
export function pairingRateLimit(): RequestHandler {
  const buckets = new Map<string, { count: number; expires: number }>();
  return (req, res, next) => {
    const now = Date.now();
    for (const [key, bucket] of buckets) if (bucket.expires <= now) buckets.delete(key);
    const kind = req.method === 'GET' ? 'poll' : req.path === '/' ? 'create' : req.path === '/invite' ? 'invite' : 'decision';
    const limit = kind === 'poll' ? 120 : kind === 'create' ? 10 : 30;
    const key = `${req.ip}:${kind}`;
    if (!buckets.has(key)) {
      if (buckets.size >= 5000) { res.setHeader('Retry-After', '60'); res.status(429).json({ error: 'Pairing busy; retry later' }); return; }
      buckets.set(key, { count: 0, expires: now + 60_000 });
    }
    const bucket = buckets.get(key)!;
    if (++bucket.count > limit) {
      res.setHeader('Retry-After', String(Math.max(1, Math.ceil((bucket.expires - now) / 1000))));
      res.status(429).json({ error: 'Too many pairing requests; retry later' }); return;
    }
    next();
  };
}

function visibleState(session: PairingSession) {
  return { pairing_id: session.id, state: session.expiresAt <= new Date() ? 'EXPIRED' : session.state,
    expires_at: session.expiresAt, grid_name: config.gridName, worker_name: (session.hardware as any).name };
}

export function pairingRouter(prisma: PrismaClient, admin: RequestHandler) {
  const router = Router();
  router.use('/pairing', pairingRateLimit());

  router.post('/pairing', async (req, res) => {
    const hardware = parseHardware(req.body);
    const code = randomBytes(6).toString('base64url'); // 48 bits; case-sensitive.
    const secret = randomBytes(32).toString('base64url');
    const session = await prisma.pairingSession.create({ data: {
      codeHash: hash(code), secretHash: hash(secret), hardware,
      expiresAt: new Date(Date.now() + config.pairingTtlMs),
    } });
    res.status(201).json({ ...visibleState(session), pairing_code: code, pairing_secret: secret });
  });

  router.post('/pairing/invite', admin, async (req, res) => {
    const code = text(req.body?.pairing_code, 'pairing_code', 8);
    check(/^[A-Za-z0-9_-]{8}$/.test(code), 'Invalid pairing_code');
    const session = await prisma.$transaction(async tx => {
      const found = await tx.pairingSession.findUnique({ where: { codeHash: hash(code) } });
      check(found, 'Pairing code unavailable', 404);
      await tx.$queryRaw`SELECT id FROM "PairingSession" WHERE id = ${found.id} FOR UPDATE`;
      const current = await tx.pairingSession.findUniqueOrThrow({ where: { id: found.id } });
      check(current.expiresAt > new Date() && ['WAITING', 'INVITED'].includes(current.state), 'Pairing code unavailable', 404);
      return current.state === 'INVITED' ? current : tx.pairingSession.update({ where: { id: current.id }, data: { state: 'INVITED', invitedAt: new Date() } });
    });
    res.json(visibleState(session));
  });

  async function authenticate(tx: Prisma.TransactionClient | PrismaClient, id: string, authorization: string | undefined) {
    const session = await tx.pairingSession.findUnique({ where: { id } });
    check(session && equalSecret(hash((authorization || '').replace(/^Bearer /, '')), session.secretHash), 'Invalid pairing credentials', 401);
    return session;
  }

  router.get('/pairing/:id', async (req, res) => {
    const session = await authenticate(prisma, String(req.params.id), req.headers.authorization);
    res.json(visibleState(session)); // Neither code nor credentials returned by polling.
  });

  router.post('/pairing/:id/decision', async (req, res) => {
    check(['approve', 'decline'].includes(req.body?.decision), 'decision must be approve or decline');
    const response = await prisma.$transaction(async tx => {
      const id = String(req.params.id);
      await authenticate(tx, id, req.headers.authorization);
      await tx.$queryRaw`SELECT id FROM "PairingSession" WHERE id = ${id} FOR UPDATE`;
      const session = await tx.pairingSession.findUniqueOrThrow({ where: { id } });
      check(session.expiresAt > new Date(), 'Pairing session expired', 410);
      if (session.state === 'APPROVED' && req.body.decision === 'approve') {
        const node = await tx.node.findUniqueOrThrow({ where: { id: session.nodeId! } });
        check(!node.revokedAt, 'Worker access revoked; pair again', 403);
        if (req.body.resource_limits !== undefined) {
          const requested = parseResourceLimits(req.body.resource_limits, node);
          const accepted = resourceLimits(node)!;
          check(requested.cpuLimit === accepted.cpu && requested.memoryLimitGb === accepted.memory_gb, 'Approval retry cannot change the accepted limits', 409);
        }
        return { ...visibleState(session), ...nodeSession(node) };
      }
      if (session.state === 'DECLINED' && req.body.decision === 'decline') return visibleState(session);
      check(session.state === 'INVITED', 'No invitation awaiting approval', 409);
      if (req.body.decision === 'decline') {
        return visibleState(await tx.pairingSession.update({ where: { id }, data: { state: 'DECLINED', decidedAt: new Date() } }));
      }
      const hardware = session.hardware as ReturnType<typeof parseHardware>;
      const limits = parseResourceLimits(req.body.resource_limits, hardware);
      const node = await tx.node.create({ data: { ...hardware, nodeSecret: randomBytes(32).toString('base64url'),
        ...limits,
        registrationKey: randomUUID(), enrollmentMode: 'paired', status: 'OFFLINE' } });
      const approved = await tx.pairingSession.update({ where: { id }, data: { state: 'APPROVED', nodeId: node.id, decidedAt: new Date() } });
      // Retrying a lost approval response recovers the SAME credential and node.
      return { ...visibleState(approved), ...nodeSession(node) };
    });
    res.json(response);
  });
  return router;
}
