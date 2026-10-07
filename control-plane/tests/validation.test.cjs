const { test } = require('node:test');
const assert = require('node:assert/strict');
const { parseJob, validateResult } = require('../dist/validation');
const { objectPath, verifySignedUrl, signedUrl } = require('../dist/storage');

test('job validation rejects invalid chunk sizes, resource requests, and unknown workloads', () => {
  const good = { name: 'Demo', workload_type: 'dummy', items: ['a'] };
  for (const chunk_size of [-1, 0, 1.2, '10', 101]) assert.throws(() => parseJob({ ...good, chunk_size }));
  assert.throws(() => parseJob({ ...good, items: [] }));
  assert.throws(() => parseJob({ ...good, min_ram_gb: -5 }));
  assert.throws(() => parseJob({ ...good, workload_type: 'arbitrary-image' }));
  assert.equal(parseJob(good).chunk_size, 10);
});
test('storage blocks traversal and altered or expired signatures', async () => {
  for (const key of ['../../secret', 'inputs/../secret', 'inputs/a/../../b', 'inputs//b']) assert.throws(() => objectPath(key));
  const url = new URL(await signedUrl('GET', 'inputs/example/image.jpg'), 'http://localhost');
  const p = url.searchParams;
  assert.doesNotThrow(() => verifySignedUrl('GET', p.get('key'), p.get('expires'), p.get('signature')));
  assert.throws(() => verifySignedUrl('PUT', p.get('key'), p.get('expires'), p.get('signature')));
  assert.throws(() => verifySignedUrl('GET', p.get('key'), '0', p.get('signature')));
});
test('results cannot silently drop, duplicate, or invent item counts', () => {
  const good = { itemsProcessed: 1, itemsFailed: 0, predictions: [{ image: 'one.png', confidence: 0.6 }], errors: [] };
  assert.doesNotThrow(() => validateResult(good, 1));
  assert.throws(() => validateResult(good, 2));
  assert.throws(() => validateResult({ ...good, itemsProcessed: 0, predictions: [] }, 1));
  assert.throws(() => validateResult({ ...good, itemsProcessed: 2, predictions: [good.predictions[0], good.predictions[0]] }, 2));
});
