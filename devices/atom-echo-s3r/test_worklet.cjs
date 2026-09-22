// Verify that interrupt discards partial audio and silences queued/new blocks.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const registry = {};
class Processor { constructor() { this.port = { postMessage: value => this.sent.push(value) }; this.sent = []; } }
vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../../frontend/public/atom-wifi-worklet.js'), 'utf8'), {
  AudioWorkletProcessor: Processor,
  registerProcessor: (name, cls) => { registry[name] = cls; }, Float32Array, Int16Array, Math,
});
const speaker = new registry['atom-wifi-speaker']();
function process(samples) { speaker.process([[new Float32Array(samples).fill(.2)]], [[new Float32Array(128)]]); }
process(240);
speaker.port.onmessage({ data: 'interrupt' });
process(480);
assert.ok([...new Int16Array(speaker.sent.at(-1))].every(x => x === 0));
speaker.port.onmessage({ data: 'resume' });
process(480);
assert.ok([...new Int16Array(speaker.sent.at(-1))].every(x => x > 0));
console.log('PASS: interrupt drops partial packet, mutes output; next response resumes');
