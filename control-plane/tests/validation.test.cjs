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
  const good = { status: 'SUCCESS', itemsProcessed: 1, itemsFailed: 0,
    predictions: [{ image: 'one.png', classId: 281, className: 'tabby', confidence: 0.6 }], errors: [] };
  const one = [{ name: 'one.png' }]; const two = [...one, { name: 'two.png' }];
  assert.doesNotThrow(() => validateResult(good, one));
  assert.throws(() => validateResult(good, two));
  assert.throws(() => validateResult({ ...good, itemsProcessed: 0, predictions: [] }, one));
  assert.throws(() => validateResult({ ...good, itemsProcessed: 2, predictions: [good.predictions[0], good.predictions[0]] }, two));
});

test('results must account for exact assigned identities across predictions and errors', () => {
  const assigned = [{ name: '00000_cat.png' }, { name: '00001_broken.png' }];
  const good = { status: 'PARTIAL_FAILURE', itemsProcessed: 1, itemsFailed: 1,
    predictions: [{ image: assigned[0].name, classId: 281, className: 'tabby', confidence: 0.8 }],
    errors: [{ image: assigned[1].name, error: 'Invalid image' }] };
  assert.doesNotThrow(() => validateResult(good, assigned));
  for (const image of ['invented.png', assigned[0].name, ' ' + assigned[1].name]) {
    assert.throws(() => validateResult({ ...good, errors: [{ image, error: 'Invalid image' }] }, assigned));
  }
  assert.throws(() => validateResult({ ...good, predictions: [{ ...good.predictions[0], image: 'other.png' }] }, assigned));
  assert.throws(() => validateResult({ ...good, errors: [{ image: assigned[1].name }] }, assigned));
  assert.throws(() => validateResult({ ...good, status: 'SUCCESS' }, assigned));
});

test('predictions require bounded class IDs, labels and finite confidence', () => {
  const assigned = [{ name: 'one.png' }];
  const prediction = { image: 'one.png', classId: 281, className: 'tabby', confidence: 0.8 };
  const good = { status: 'SUCCESS', itemsProcessed: 1, itemsFailed: 0, predictions: [prediction], errors: [] };
  for (const change of [{ classId: 1000 }, { classId: 1.5 }, { classId: undefined },
    { className: '' }, { confidence: NaN }, { confidence: Infinity }, { confidence: 1.1 }, { confidence: undefined }]) {
    assert.throws(() => validateResult({ ...good, predictions: [{ ...prediction, ...change }] }, assigned));
  }
});
