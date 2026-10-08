const { test } = require('node:test');
const assert = require('node:assert/strict');
const { pairingRateLimit, parseHardware } = require('../dist/pairing');

test('pairing rate limits code creation, invitation guesses and polling independently', () => {
  const limit = pairingRateLimit();
  function call(path, method = 'POST', ip = '127.0.0.1') {
    let status = 200; let forwarded = false;
    const res = { setHeader() {}, status(value) { status = value; return this; }, json() {} };
    limit({ path, method, ip }, res, () => { forwarded = true; });
    return { status, forwarded };
  }
  for (let i = 0; i < 10; i++) assert.equal(call('/').forwarded, true);
  assert.equal(call('/').status, 429);
  for (let i = 0; i < 30; i++) assert.equal(call('/invite').forwarded, true);
  assert.equal(call('/invite').status, 429);
  for (let i = 0; i < 120; i++) assert.equal(call('/session', 'GET').forwarded, true);
  assert.equal(call('/session', 'GET').status, 429);
  assert.equal(call('/', 'POST', '127.0.0.2').forwarded, true);
});

test('pairing cannot bypass normal hardware and workload admission validation', () => {
  const body = { name: 'Laptop', cpu_cores: 4, ram_gb: 8.5, os: 'windows', capabilities: ['dummy'], baseline_power_w: 45 };
  assert.equal(parseHardware(body).ramGb, 8.5);
  for (const override of [{ capabilities: ['arbitrary_shell'] }, { cpu_cores: 0 }, { ram_gb: Infinity }, { baseline_power_w: -1 }, { name: ' ' }]) {
    assert.throws(() => parseHardware({ ...body, ...override }));
  }
});
