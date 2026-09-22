const {test} = require('node:test');
const assert = require('node:assert/strict');
const {transform} = require('../mobile/scripts/patch-incall-focus.cjs');

test('media sharing patch changes call focus only, is repeatable, rejects incompatible dependency', () => {
  const source = `new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT);
audioManager.requestAudioFocus(this, AudioManager.STREAM_VOICE_CALL, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT);
audioManager.requestAudioFocus(this, AudioManager.STREAM_RING, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT);`;
  const changed = transform(source);
  assert.equal((changed.match(/AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK/g)||[]).length,2);
  assert.ok(changed.includes('STREAM_RING, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)'));
  assert.equal(transform(changed), changed);
  assert.throws(() => transform(source.replace('STREAM_VOICE_CALL', 'STREAM_MUSIC')), /source changed/);
  assert.throws(() => transform(source + source), /source changed/);
});
