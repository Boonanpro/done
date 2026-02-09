/**
 * PCM audio player for Gemini Live API output.
 *
 * Receives PCM 24kHz 16-bit LE mono chunks and plays them
 * seamlessly using AudioContext + AudioBufferSourceNode scheduling.
 */

export class PCMPlayer {
  private ctx: AudioContext | null = null;
  private nextStartTime = 0;
  private isPlaying = false;

  constructor(private sampleRate: number = 24000) {}

  /**
   * Initialize the AudioContext. Must be called from a user gesture.
   */
  init(): void {
    if (!this.ctx) {
      this.ctx = new AudioContext({ sampleRate: this.sampleRate });
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
    this.nextStartTime = 0;
    this.isPlaying = false;
  }

  /**
   * Play a PCM chunk (Int16 LE bytes → Float32 AudioBuffer).
   */
  play(pcmBytes: ArrayBuffer): void {
    if (!this.ctx) return;

    const int16 = new Int16Array(pcmBytes);
    const float32 = new Float32Array(int16.length);

    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }

    const buffer = this.ctx.createBuffer(1, float32.length, this.sampleRate);
    buffer.getChannelData(0).set(float32);

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);

    // Schedule seamlessly after the previous chunk
    const now = this.ctx.currentTime;
    const startTime = this.nextStartTime > now ? this.nextStartTime : now;
    source.start(startTime);
    this.nextStartTime = startTime + buffer.duration;
    this.isPlaying = true;

    source.onended = () => {
      // Check if we're still the latest scheduled source
      if (this.ctx && this.ctx.currentTime >= this.nextStartTime - 0.01) {
        this.isPlaying = false;
      }
    };
  }

  /**
   * Stop all playback and reset scheduling.
   */
  stop(): void {
    if (this.ctx) {
      // Close and recreate to stop all queued sources
      const sr = this.sampleRate;
      this.ctx.close().catch(() => {});
      this.ctx = new AudioContext({ sampleRate: sr });
    }
    this.nextStartTime = 0;
    this.isPlaying = false;
  }

  /**
   * Clean up the AudioContext.
   */
  destroy(): void {
    if (this.ctx) {
      this.ctx.close().catch(() => {});
      this.ctx = null;
    }
    this.isPlaying = false;
  }

  get playing(): boolean {
    return this.isPlaying;
  }
}
