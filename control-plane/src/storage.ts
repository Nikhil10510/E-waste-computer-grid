import { createHmac, randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { S3Client, GetObjectCommand, PutObjectCommand, HeadObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { config } from './config';
import { check, equalSecret } from './validation';

const bucket = process.env.S3_BUCKET || '';
const client = config.storageDriver === 's3' ? new S3Client({
  region: process.env.AWS_REGION || 'ap-south-1', endpoint: process.env.S3_ENDPOINT,
  forcePathStyle: process.env.S3_FORCE_PATH_STYLE === 'true',
}) : null;
if (client && !bucket) throw new Error('S3_BUCKET is required');

export function objectPath(key: string) {
  check(/^(inputs|outputs)\/[a-zA-Z0-9/_.-]+$/.test(key) && !key.split('/').some(x => !x || x === '.' || x === '..'), 'Invalid storage key');
  const resolved = path.resolve(config.storageDir, ...key.split('/'));
  check(resolved.startsWith(config.storageDir + path.sep), 'Invalid storage path');
  return resolved;
}
function signature(method: string, key: string, expires: string) {
  return createHmac('sha256', config.storageSecret).update(`${method}\n${key}\n${expires}`).digest('hex');
}
export function verifySignedUrl(method: string, key: string, expires: unknown, sig: unknown) {
  objectPath(key);
  check(typeof expires === 'string' && /^\d+$/.test(expires) && Number(expires) > Date.now(), 'Storage URL expired', 403);
  check(typeof sig === 'string' && equalSecret(sig, signature(method, key, expires)), 'Invalid storage signature', 403);
}
export async function signedUrl(method: 'GET' | 'PUT', key: string) {
  objectPath(key);
  if (client) {
    const command = method === 'GET' ? new GetObjectCommand({ Bucket: bucket, Key: key }) : new PutObjectCommand({ Bucket: bucket, Key: key, ContentType: 'application/json' });
    return getSignedUrl(client, command, { expiresIn: 3600 });
  }
  const expires = String(Date.now() + 3600_000);
  return `${config.publicApiUrl}/storage?key=${encodeURIComponent(key)}&expires=${expires}&signature=${signature(method, key, expires)}`;
}
export async function putObject(key: string, data: Buffer, contentType: string) {
  const target = objectPath(key);
  if (client) { await client.send(new PutObjectCommand({ Bucket: bucket, Key: key, Body: data, ContentType: contentType })); return; }
  await fs.mkdir(path.dirname(target), { recursive: true });
  const tmp = `${target}.${randomUUID()}.tmp`;
  try { await fs.writeFile(tmp, data); await fs.rename(tmp, target); }
  finally { await fs.rm(tmp, { force: true }); }
}
export async function objectExists(key: string) {
  const target = objectPath(key);
  try {
    if (client) await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
    else await fs.access(target);
    return true;
  } catch (e: any) {
    if (e.code === 'ENOENT' || e.$metadata?.httpStatusCode === 404) return false;
    throw e;
  }
}
export async function readResult(key: string) {
  const target = objectPath(key);
  let data: string;
  if (client) {
    const obj = await client.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
    check((obj.ContentLength ?? Infinity) <= config.maxResultBytes, 'Result too large');
    data = await obj.Body!.transformToString();
  } else {
    check((await fs.stat(target)).size <= config.maxResultBytes, 'Result too large');
    data = await fs.readFile(target, 'utf8');
  }
  try { return JSON.parse(data); } catch { check(false, 'Output must contain valid JSON'); }
}
export function resultKey(jobId: string, taskId: string, leaseToken: string) {
  return `outputs/${jobId}/${taskId}/${leaseToken}/result.json`;
}
