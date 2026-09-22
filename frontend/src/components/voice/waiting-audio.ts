/** Quiet, seamless surf-like noise. Stays outside the microphone/voice meters. */
export class WaitingAudio {
  private source: AudioBufferSourceNode;
  private gain: GainNode;
  constructor(context: AudioContext, output: AudioNode) {
    const size = context.sampleRate * 8;
    const buffer = context.createBuffer(1, size, context.sampleRate);
    const data = buffer.getChannelData(0);
    let seed = 179, brown = 0;
    for (let i = 0; i < size; i++) {
      seed = (Math.imul(seed, 1664525) + 1013904223) | 0;
      brown = .97 * brown + .03 * (seed / 2147483648);
      const wave = .4 + .6 * Math.pow(Math.sin(Math.PI * i / size), 2);
      const seam = Math.min(1, i / 2400, (size - i) / 2400);
      data[i] = brown * wave * seam;
    }
    this.gain = context.createGain(); this.gain.gain.value = 0; this.gain.connect(output);
    this.source = context.createBufferSource(); this.source.buffer = buffer;
    this.source.loop = true; this.source.connect(this.gain); this.source.start();
  }
  set(active: boolean) {
    const now = this.gain.context.currentTime;
    this.gain.gain.cancelScheduledValues(now);
    this.gain.gain.setTargetAtTime(active ? .09 : 0, now, active ? .15 : .02);
  }
  close() { this.source.stop(); this.source.disconnect(); this.gain.disconnect(); }
}
