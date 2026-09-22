const {test} = require('node:test');
const assert = require('node:assert/strict');
const {transform} = require('../mobile/scripts/patch-webrtc-field-trials.cjs');

test('wires options into the actual factory and is idempotent', () => {
  const original = 'mFactory = PeerConnectionFactory.builder()\n .setAudioDeviceModule(adm)\n .createPeerConnectionFactory();';
  const patched = transform(original);
  assert.match(patched, /builder\(\)\s+\.setFieldTrials\(fieldTrials == null \? "" : fieldTrials\)/);
  assert.ok(patched.endsWith('.setAudioDeviceModule(adm)\n .createPeerConnectionFactory();'));
  assert.equal(transform(patched), patched);
});
test('fails closed when the upstream factory or configuration changes', () => {
  assert.throws(() => transform('no factory'));
  assert.throws(() => transform('mFactory = PeerConnectionFactory.builder()\n .setOptions(x)\n .setFieldTrials(other)\n .createPeerConnectionFactory();'));
});
