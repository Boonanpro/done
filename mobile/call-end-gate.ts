import {explicitCallEnd, needsCallControlReview} from './call-intent';

/** A narrow local call control. Transcript arrival gaps alone are never silence.
 * Requires recent real microphone observations, a quiet interval, and an
 * explicit accumulated request. Other meanings stay with Live/Astra.
 */
export class CallEndGate {
  private text = '';
  private changedAt = 0;
  private observedAt = -Infinity;
  private speechAt = -Infinity;
  private heardSpeech = false;
  private fired = false;
  private revision = 0;
  private textRevision = 0;
  private reviewed = -1;
  transcript(text: string, now: number) {
    this.text = text;
    this.changedAt = now;
    this.revision++;
    this.textRevision++;
  }
  microphone(level: number | null, now: number) {
    if (level === null || !Number.isFinite(level)) return;
    // A sampling gap cannot be counted as observed silence.
    if (now - this.observedAt > 400) this.speechAt = now;
    this.observedAt = now;
    if (level > .01) {this.speechAt = now; this.heardSpeech = true; this.revision++;}
  }
  private quiet(now: number) {
    return !this.fired && this.heardSpeech && now-this.observedAt<=400 &&
        now-this.speechAt>=650 && now-this.changedAt>=300;
  }
  shouldEnd(now: number) {
    if (!this.quiet(now) || !explicitCallEnd(this.text)) return false;
    this.fired = true;
    return true;
  }
  takeReview(now: number) {
    if (!this.quiet(now) || this.reviewed === this.textRevision || !needsCallControlReview(this.text)) return null;
    this.reviewed = this.textRevision;
    return {revision:this.revision, text:this.text};
  }
  acceptReview(revision: number, now: number) {
    if (revision !== this.revision || !this.quiet(now)) return false;
    this.fired = true;
    return true;
  }
}
