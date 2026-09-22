/** A waiting sound represents active work, never mere conversational silence. */
export class WorkWaiting {
  private since = 0;
  private quietAfter = 0;
  private audible = false;
  constructor(private output: (active: boolean) => void) {}
  speech(now: number) { this.quietAfter = now + 700; this.set(false); }
  update(now: number, working: boolean, talking: boolean, connected = true) {
    if (talking) this.speech(now);
    if (!connected || !working) { this.since = 0; this.set(false); return; }
    if (!this.since) this.since = now;
    this.set(!talking && now >= this.quietAfter && now - this.since >= 1200);
  }
  close() { this.since = 0; this.set(false); }
  private set(active: boolean) {
    if (this.audible === active) return;
    this.audible = active; this.output(active);
  }
}

export function isWorking(state: unknown, runningJob: boolean) {
  return runningJob || ['reasoning', 'reading'].includes(String(state));
}
