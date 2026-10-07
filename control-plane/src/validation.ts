import { createHash, timingSafeEqual } from 'node:crypto';

export class HttpError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function check(condition: unknown, message: string, status = 400): asserts condition {
  if (!condition) throw new HttpError(status, message);
}
export function equalSecret(a: string, b: string) {
  const x = Buffer.from(a); const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}
export function text(value: unknown, name: string, max = 200): string {
  check(typeof value === 'string' && value.trim().length > 0 && value.length <= max, `Invalid ${name}`);
  return value.trim();
}
export function number(value: unknown, name: string, min: number, max: number, integer = false): number {
  check(typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max && (!integer || Number.isInteger(value)), `Invalid ${name}`);
  return value;
}
export function fileName(value: unknown): string {
  const name = text(value, 'filename', 160).replace(/[^a-zA-Z0-9._-]/g, '_');
  check(name !== '.' && name !== '..', 'Invalid filename');
  return name;
}
export function fingerprint(value: unknown) { return createHash('sha256').update(JSON.stringify(value)).digest('hex'); }

export const workloads = ['dummy', 'image_inference'] as const;
export type InputItem = { key?: string; name: string; content?: string; };
export interface TaskPayload { workload_type: string; items: InputItem[]; min_ram_gb: number; }

export function parseJob(body: any) {
  check(body && typeof body === 'object', 'Expected JSON object');
  const name = text(body.name || 'Untitled Job', 'name');
  check(workloads.includes(body.workload_type), 'workload_type must be dummy or image_inference');
  check(Array.isArray(body.items) && body.items.length > 0 && body.items.length <= 10000, 'Provide 1–10000 items');
  const chunkSize = number(body.chunk_size ?? 10, 'chunk_size', 1, 100, true);
  const minRam = number(body.min_ram_gb ?? (body.workload_type === 'dummy' ? 0.25 : 2), 'min_ram_gb', 0.25, 1024);
  const items: InputItem[] = body.items.map((item: unknown, i: number) => {
    if (body.workload_type === 'dummy') return { name: `${String(i).padStart(5, '0')}.txt`, content: text(item, 'dummy item', 1000) };
    check(item && typeof item === 'object', 'Image items must be uploaded input objects');
    const input = item as Record<string, unknown>;
    const key = text(input.key, 'input key', 250);
    check(/^inputs\/[a-f0-9-]{36}\/[a-zA-Z0-9._-]+$/.test(key), 'Invalid input key');
    const name = fileName(input.name);
    check(/\.(jpe?g|png|webp|bmp)$/i.test(name), 'Unsupported image extension');
    return { key, name: `${String(i).padStart(5, '0')}_${name}` };
  });
  return { name, workload_type: body.workload_type as string, items, chunk_size: chunkSize, min_ram_gb: minRam };
}

export function validateResult(value: any, expectedItems: number) {
  check(value && typeof value === 'object', 'Invalid workload result');
  const processed = number(value.itemsProcessed, 'itemsProcessed', 0, expectedItems, true);
  const failed = number(value.itemsFailed, 'itemsFailed', 0, expectedItems, true);
  check(processed + failed === expectedItems && processed > 0, 'Result must account for every input and contain a successful item');
  check(Array.isArray(value.predictions) && value.predictions.length === processed, 'Prediction count does not match itemsProcessed');
  check(Array.isArray(value.errors) && value.errors.length === failed, 'Error count does not match itemsFailed');
  const names = new Set<string>();
  for (const prediction of value.predictions) {
    check(prediction && typeof prediction === 'object', 'Invalid prediction');
    const name = text(prediction.image, 'prediction image', 200);
    check(!names.has(name), 'Duplicate prediction'); names.add(name);
    if (prediction.confidence !== undefined) number(prediction.confidence, 'confidence', 0, 1);
  }
  return value;
}
