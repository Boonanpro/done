// 48 kHz input -> 16 kHz PCM in 20 ms packets. A low-pass filter precedes this node.
class GeminiMic extends AudioWorkletProcessor {
  constructor() { super(); this.packet = new Int16Array(320); this.index = 0; this.phase = 0; this.sum = 0; }
  process(inputs, outputs) {
    for (const output of outputs[0] || []) output.fill(0);
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const value of input) {
      this.sum += value;
      if (++this.phase === 3) {
        this.packet[this.index++] = Math.round(Math.max(-1, Math.min(1, this.sum / 3)) * 32767);
        this.phase = 0; this.sum = 0;
        if (this.index === 320) {
          this.port.postMessage(this.packet.buffer, [this.packet.buffer]);
          this.packet = new Int16Array(320); this.index = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('gemini-mic', GeminiMic);
