const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const mobile = path.join(__dirname, '..', 'mobile');
const plugin = fs.readFileSync(path.join(mobile, 'plugins/withDanVoiceCall.js'), 'utf8');
const resume = fs.readFileSync(path.join(mobile, 'native/voice/DanLifelogResume.kt'), 'utf8');

// 2026-11-08: the phone's battery ran out and the recording stayed off until the owner happened to open the app.
test('the boot receiver, the resume screen and their permission are in the manifest', () => {
  assert.match(plugin, /android\.permission\.RECEIVE_BOOT_COMPLETED/);
  assert.match(plugin, /app\.done\.dan\.voice\.DanLifelogResumeReceiver/);
  assert.match(plugin, /android\.intent\.action\.BOOT_COMPLETED/);
  assert.match(plugin, /android\.intent\.action\.MY_PACKAGE_REPLACED/);
  assert.match(plugin, /app\.done\.dan\.voice\.DanLifelogResumeActivity/);
});

test('the resume code is copied into the build', () => {
  assert.match(plugin, /'DanLifelogResume\.kt'/);
});

test('the offer only appears when the switch is on and nothing records', () => {
  assert.match(resume, /if \(!DanPhoneLifelog\.isEnabled\(context\) \|\| DanPhoneLifelog\.capturing\(\)\) return/);
  assert.match(resume, /録音を再開/);
});
