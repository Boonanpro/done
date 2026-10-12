// Let the app give RN WebRTC's peer factory an audio processing factory. The whisper lift must run after echo
// cancellation (capture post-processing), as it does in the dashboard: lifted before it, the earbuds' echo of Dan's own
// voice was amplified past what echo cancellation removes (calls on 2026-09-26).
const fs = require('node:fs');
const path = require('node:path');

const FIELD = '    public org.webrtc.AudioProcessingFactory audioProcessingFactory;';
const SETTING = '.setAudioProcessingFactory(options.audioProcessingFactory != null ? options.audioProcessingFactory : new org.webrtc.ExternalAudioProcessingFactory())';

function transformOptions(source) {
  if (source.includes(FIELD)) return source;
  const anchor = '    public String fieldTrials;';
  if (source.split(anchor).length !== 2) throw new Error('Review WebRTC audio processing patch: WebRTCModuleOptions changed');
  return source.replace(anchor, `${anchor}\n${FIELD}`);
}

function transformModule(source) {
  if (source.includes(SETTING)) return source;
  const anchor = 'mFactory = PeerConnectionFactory.builder()';
  const create = '.createPeerConnectionFactory();';
  if (source.split(anchor).length !== 2) throw new Error('Review WebRTC audio processing patch: factory creation changed');
  const start = source.indexOf(anchor);
  const end = source.indexOf(create, start);
  if (end < 0 || source.slice(start, end).includes('.setAudioProcessingFactory(')) throw new Error('Review existing WebRTC audio processing factory');
  return source.slice(0, end) + SETTING + '\n                           ' + source.slice(end);
}

function patch(root = path.resolve(__dirname, '..')) {
  const {version} = JSON.parse(fs.readFileSync(path.join(root, 'node_modules/react-native-webrtc/package.json'), 'utf8'));
  if (version !== '124.0.8') throw new Error(`Review Dan audio processing patch for RN WebRTC ${version}`);
  const dir = path.join(root, 'node_modules/react-native-webrtc/android/src/main/java/com/oney/WebRTCModule');
  for (const [file, transform] of [['WebRTCModuleOptions.java', transformOptions], ['WebRTCModule.java', transformModule]]) {
    const full = path.join(dir, file);
    const source = fs.readFileSync(full, 'utf8');
    const result = transform(source);
    if (result !== source) fs.writeFileSync(full, result);
  }
}
module.exports = {patch, transformOptions, transformModule};
if (require.main === module) patch();
