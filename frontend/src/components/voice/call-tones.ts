/** Short tones that mark when a voice call can be spoken into and when it has ended.
 * Why: the call takes a few seconds to open after 「音声」 is pressed, and the owner could not tell when to start talking
 * (11/22). Each tone has its own short-lived AudioContext, so the hang-up tone still plays after the call's context closed. */
type Note = { freq: number; at: number; len: number };

// Start: two notes going up (ポン↑ポン). End: two notes going down. Different enough to tell apart without looking.
const START: Note[] = [{ freq: 784, at: 0, len: 0.12 }, { freq: 1175, at: 0.13, len: 0.2 }];
const END: Note[] = [{ freq: 1047, at: 0, len: 0.12 }, { freq: 659, at: 0.13, len: 0.24 }];

function play(notes: Note[], level = 0.22) {
  try {
    const ctx = new AudioContext();
    void ctx.resume().catch(() => {});
    const t0 = ctx.currentTime + 0.02;
    let last: OscillatorNode | null = null;
    for (const n of notes) {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(n.freq, t0 + n.at);
      gain.gain.setValueAtTime(0.0001, t0 + n.at);
      gain.gain.exponentialRampToValueAtTime(level, t0 + n.at + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + n.at + n.len);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(t0 + n.at); osc.stop(t0 + n.at + n.len + 0.02);
      last = osc;
    }
    if (last) last.onended = () => { void ctx.close().catch(() => {}); };
  } catch {
    /* A missing tone must never stop the call. */
  }
}

export const playCallStartTone = () => play(START);
export const playCallEndTone = () => play(END);

/** How much louder Dan's voice plays than GPT-Live sends it. Raised so the PC volume can stay where other videos are
 * comfortable (11/22). `localStorage['dan-voice-gain']` overrides it for a quick trial. */
export function voiceGain(): number {
  try {
    const saved = Number(localStorage.getItem('dan-voice-gain'));
    if (saved > 0 && saved <= 6) return saved;
  } catch { /* noop */ }
  return 2.2;
}
