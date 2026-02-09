/**
 * AudioWorklet processor for capturing microphone PCM data.
 *
 * Converts Float32 input to Int16 PCM and posts it via port.postMessage.
 * Expected AudioContext sampleRate: 16000
 */
class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Int16Array(0);
    // Send chunks of ~50ms (800 samples at 16kHz)
    this._chunkSize = 800;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const float32 = input[0]; // mono channel
    const int16 = new Int16Array(float32.length);

    for (let i = 0; i < float32.length; i++) {
      // Clamp and convert Float32 [-1, 1] to Int16 [-32768, 32767]
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }

    // Append to buffer
    const newBuffer = new Int16Array(this._buffer.length + int16.length);
    newBuffer.set(this._buffer);
    newBuffer.set(int16, this._buffer.length);
    this._buffer = newBuffer;

    // Send complete chunks
    while (this._buffer.length >= this._chunkSize) {
      const chunk = this._buffer.slice(0, this._chunkSize);
      this._buffer = this._buffer.slice(this._chunkSize);
      // Transfer the underlying ArrayBuffer for zero-copy
      this.port.postMessage(chunk.buffer, [chunk.buffer]);
    }

    return true;
  }
}

registerProcessor('pcm-capture-processor', PCMCaptureProcessor);
