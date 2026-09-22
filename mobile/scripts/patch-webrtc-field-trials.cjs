// SDK 144 consumes per-factory Environment field trials. The legacy global
// initialization used by RN WebRTC does not configure that Environment.
const fs = require('node:fs');
const path = require('node:path');

function transform(source) {
  const anchor = 'mFactory = PeerConnectionFactory.builder()';
  const setting = '.setFieldTrials(fieldTrials == null ? "" : fieldTrials)';
  if (source.split(anchor).length !== 2) throw new Error('Review WebRTC factory field-trial patch: factory creation changed');
  const tail = source.slice(source.indexOf(anchor) + anchor.length);
  if (tail.trimStart().startsWith(setting)) return source;
  if (tail.slice(0, tail.indexOf('.createPeerConnectionFactory()')).includes('.setFieldTrials(')) {
    throw new Error('Review existing WebRTC per-factory field trials');
  }
  return source.replace(anchor, `${anchor}\n                           ${setting}`);
}

function patch(root = path.resolve(__dirname, '..')) {
  const {version} = JSON.parse(fs.readFileSync(path.join(root, 'node_modules/react-native-webrtc/package.json'), 'utf8'));
  if (version !== '124.0.8') throw new Error(`Review Dan field-trial patch for RN WebRTC ${version}`);
  const file = path.join(root, 'node_modules/react-native-webrtc/android/src/main/java/com/oney/WebRTCModule/WebRTCModule.java');
  const source = fs.readFileSync(file, 'utf8');
  const result = transform(source);
  if (result !== source) fs.writeFileSync(file, result);
}
module.exports = {patch, transform};
if (require.main === module) patch();
