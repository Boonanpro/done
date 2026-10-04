// Level control for the voice uplink, 48 kHz mono. The browser's noise suppression treats a whisper as noise and
// Live does not take quiet input as speech, so quiet speech is lifted to a normal speaking level (up to +30 dB)
// while normal speech keeps roughly its own level; a soft limiter keeps peaks from clipping.
class QuietSpeechLift extends AudioWorkletProcessor {
  constructor() {
    super();
    this.power = 0; this.gain = 1;
    const k = s => Math.exp(-1 / (s * sampleRate));
    this.powerAttack = k(.010); this.powerRelease = k(.300);
    this.gainDown = k(.020); this.gainUp = k(.200);
  }
  process(inputs, outputs) {
    const x = inputs[0][0], y = outputs[0][0];
    if (!x || !y) return true;
    const target = .3, maxGain = 31.6; // -10 dBFS, +30 dB
    for (let i = 0; i < x.length; i++) {
      const p = x[i] * x[i];
      const a = p > this.power ? this.powerAttack : this.powerRelease;
      this.power = a * this.power + (1 - a) * p;
      const want = Math.min(maxGain, target / Math.sqrt(this.power + 1e-12));
      const g = want < this.gain ? this.gainDown : this.gainUp;
      this.gain = g * this.gain + (1 - g) * want;
      y[i] = Math.tanh(x[i] * this.gain * 1.5) / 1.5;
    }
    return true;
  }
}
registerProcessor('quiet-speech-lift', QuietSpeechLift);
