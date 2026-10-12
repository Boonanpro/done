package app.done.dan.voice;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/**
 * Level control for a whispering user on an in-ear mic. Noise suppression treats a whisper as noise and Live does not
 * take quiet input as speech, so quiet speech is lifted (up to +30 dB) to the level at which the dashboard's calls were
 * understood, while normal speech keeps roughly its own level; a soft limiter keeps peaks from clipping. Same curve as the dashboard's
 * frontend/public/quiet-speech-worklet.js, after an input balance the phone path needs. Runs after echo cancellation
 * (DanQuietSpeechProcessing), as the dashboard's does.
 */
final class DanQuietSpeechLift {
  // Live and whispers, measured on 2026-09-26. From the PC (understood) speech reached about -28 dBFS at its louder parts,
  // with about 29 dB between peaks and average. A -10 dBFS target sent the phone's whispers at -20 dBFS squeezed to about
  // 20 dB and clipping: Live answered but misheard (1たす1 -> いつか成長). A -32 dBFS target kept the shape and Live heard
  // correctly, but let whispers near -40 dBFS go unanswered. Aim between, near the PC's level, without squeezing.
  private static final double TARGET = .07, MAX_GAIN = 31.6; // -23 dBFS, +30 dB
  private final double powerAttack, powerRelease, gainDown, gainUp;
  private double power, gain = 1;
  // Match the dashboard's input balance before lifting. Calls measured on 2026-09-26: what Live received from the phone had
  // 0-300 Hz about 9 dB and 300-1000 Hz about 12 dB above the 2-4 kHz band (the sealed ear's rumble; what the PC sent
  // had neither), and Live did not respond to whispers. From the PC, with both bands near 2-4 kHz,
  // it did. Lifted together with the whisper, the rumble buried the whisper's 1-6 kHz content. A whisper has no voiced
  // fundamental; normal speech keeps its low range at -10 dB.
  private final Biquad rumble, shelf;
  private static final double SHELF_KEEP = .3; // below ~900 Hz: -10 dB

  DanQuietSpeechLift(int rate) {
    powerAttack = k(.010, rate); powerRelease = k(.300, rate);
    gainDown = k(.020, rate); gainUp = k(.200, rate);
    rumble = Biquad.highPass(250, rate); shelf = Biquad.highPass(900, rate);
  }

  /** 2nd-order Butterworth high-pass (RBJ cookbook, Q = 1/sqrt 2). */
  private static final class Biquad {
    private final double b0, b1, b2, a1, a2;
    private double x1, x2, y1, y2;
    private Biquad(double b0, double b1, double b2, double a1, double a2) { this.b0 = b0; this.b1 = b1; this.b2 = b2; this.a1 = a1; this.a2 = a2; }
    static Biquad highPass(double hz, int rate) {
      double w = 2 * Math.PI * hz / rate, alpha = Math.sin(w) / (2 * Math.sqrt(.5)), c = Math.cos(w), a0 = 1 + alpha;
      return new Biquad((1 + c) / 2 / a0, -(1 + c) / a0, (1 + c) / 2 / a0, -2 * c / a0, (1 - alpha) / a0);
    }
    double run(double x) {
      double y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
      x2 = x1; x1 = x; y2 = y1; y1 = y;
      return y;
    }
    void reset() { x1 = x2 = y1 = y2 = 0; }
  }

  private static double k(double seconds, int rate) { return Math.exp(-1 / (seconds * rate)); }

  void reset() { power = 0; gain = 1; rumble.reset(); shelf.reset(); }

  /** numFrames float samples in 16-bit scale (WebRTC's FloatS16), native byte order, processed in place. */
  void processFloat(ByteBuffer buffer, int numFrames) {
    java.nio.FloatBuffer samples = buffer.duplicate().order(ByteOrder.nativeOrder()).asFloatBuffer();
    int n = Math.min(numFrames, samples.capacity());
    for (int i = 0; i < n; i++) samples.put(i, (float) (step(samples.get(i) / 32768.0) * 32768.0));
  }

  private double step(double sample) {
    double in = rumble.run(sample);
    double high = shelf.run(in), x = high + SHELF_KEEP * (in - high);
    double p = x * x;
    double a = p > power ? powerAttack : powerRelease;
    power = a * power + (1 - a) * p;
    double want = Math.min(MAX_GAIN, TARGET / Math.sqrt(power + 1e-12));
    double g = want < gain ? gainDown : gainUp;
    gain = g * gain + (1 - g) * want;
    return Math.tanh(x * gain); // linear until close to full scale
  }
}
