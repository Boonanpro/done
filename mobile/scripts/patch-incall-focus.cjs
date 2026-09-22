// Kept local until the upstream library exposes focus gain as a call option.
// Patch only the two call-focus requests, never ringtone/ringback requests.
const fs = require('node:fs');
const path = require('node:path');

function transform(source) {
  for (const before of [
    'new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)',
    'audioManager.requestAudioFocus(this, AudioManager.STREAM_VOICE_CALL, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)',
  ]) {
    const after = before.replace('AUDIOFOCUS_GAIN_TRANSIENT)', 'AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)');
    const originals = source.split(before).length - 1;
    const patched = source.split(after).length - 1;
    if (originals + patched !== 1) throw new Error('InCallManager call-focus source changed; review the media sharing patch');
    if (originals) source = source.replace(before, after);
  }
  return source;
}

function patch(root = path.resolve(__dirname, '..')) {
  const base = path.join(root, 'node_modules/react-native-incall-manager');
  const {version} = JSON.parse(fs.readFileSync(path.join(base, 'package.json'), 'utf8'));
  if (version !== '4.2.2') throw new Error(`Review Dan call-focus patch for InCallManager ${version}`);
  const file = path.join(base, 'android/src/main/java/com/zxcpoiu/incallmanager/InCallManagerModule.java');
  const source = fs.readFileSync(file, 'utf8'), result = transform(source);
  if (result !== source) fs.writeFileSync(file, result);
}
module.exports = {patch, transform};
if (require.main === module) patch();
