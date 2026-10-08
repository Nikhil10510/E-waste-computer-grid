import 'dotenv/config';
import path from 'node:path';

function positiveInteger(name: string, fallback: number) {
  const value = Number(process.env[name] || fallback);
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer`);
  return value;
}

export const config = {
  port: positiveInteger('PORT', 8080),
  enrollmentToken: process.env.ENROLLMENT_TOKEN || 'local-enrollment-change-me',
  allowLegacyEnrollment: process.env.ALLOW_LEGACY_ENROLLMENT === 'true' ||
    (process.env.ALLOW_LEGACY_ENROLLMENT === undefined && process.env.NODE_ENV !== 'production'),
  gridName: process.env.GRID_NAME || 'E-Waste Compute Grid',
  pairingTtlMs: positiveInteger('PAIRING_TTL_MS', 600_000),
  adminToken: process.env.ADMIN_TOKEN || 'local-admin-change-me',
  storageSecret: process.env.STORAGE_SECRET || 'local-storage-signing-change-me',
  publicApiUrl: (process.env.PUBLIC_API_URL || '/api').replace(/\/$/, ''),
  storageDriver: process.env.STORAGE_DRIVER || 'local',
  storageDir: path.resolve(process.env.STORAGE_DIR || './.storage'),
  corsOrigins: (process.env.CORS_ORIGINS || 'http://localhost:5173,http://localhost:4173').split(','),
  leaseMs: positiveInteger('TASK_LEASE_MS', 300_000),
  maxAttemptMs: positiveInteger('MAX_ATTEMPT_MS', 900_000),
  sweepMs: positiveInteger('SWEEP_INTERVAL_MS', 10_000),
  offlineMs: positiveInteger('NODE_OFFLINE_MS', 90_000),
  maxRetries: 3,
  maxFileBytes: 20 * 1024 * 1024,
  maxResultBytes: 5 * 1024 * 1024,
};

if (!['local', 's3'].includes(config.storageDriver)) throw new Error('STORAGE_DRIVER must be local or s3');
if (process.env.NODE_ENV === 'production') {
  for (const name of ['ENROLLMENT_TOKEN', 'ADMIN_TOKEN', 'STORAGE_SECRET']) {
    if (!process.env[name] || process.env[name]!.length < 24 || process.env[name]!.startsWith('local-')) {
      throw new Error(`${name} must be a unique secret of at least 24 characters in production`);
    }
  }
  if (!config.publicApiUrl.startsWith('https://')) throw new Error('Production PUBLIC_API_URL must use HTTPS');
}
