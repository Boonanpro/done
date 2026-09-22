/** Local playback suppression, not cancellation of speech inference or work.
 * A candidate requires continuing microphone speech while Dan was speaking.
 * Release after the model has observed new input and its old playback is quiet.
 * Missing transcripts cannot leave playback suppressed forever.
 */
export class PlaybackInterruption {
  private observedAt = -Infinity;
  private inputAt = -Infinity;
  private outputAt = -Infinity;
  private runAt: number | null = null;
  private candidate = false;
  private transcriptVersion = 0;
  private startVersion = 0;
  private suppressed = false;

  transcript() { this.transcriptVersion++; }
  observe(input: number | null, output: number | null, now: number): boolean {
    if (input === null || output === null || !Number.isFinite(input) || !Number.isFinite(output)) return this.suppressed;
    const fresh = now-this.observedAt <= 400;
    this.observedAt = now;
    if (output > .01) this.outputAt = now;
    if (input > .01) {
      this.inputAt = now;
      if (this.runAt === null || !fresh) {
        this.runAt = now;
        this.candidate = now-this.outputAt <= 400;
        this.startVersion = this.transcriptVersion;
      }
      if (!this.suppressed && this.candidate && now-this.runAt >= 120) this.suppressed = true;
    } else {
      this.runAt = null; this.candidate = false;
      if (this.suppressed && now-this.inputAt >= 300 &&
          ((this.transcriptVersion > this.startVersion && now-this.outputAt >= 200) || now-this.inputAt >= 1200)) {
        this.suppressed = false;
      }
    }
    return this.suppressed;
  }
}
