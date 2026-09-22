/** Acknowledge the greeting request, then prompt Live to speak before user input. */
export class LiveGreeting {
  private id = '';
  private acknowledged = false;
  private heard = false;
  private userSpoke = false;
  private audioHeard = false;
  private attempts = 0;
  private at = 0;
  private finished = false;
  constructor(
    private send: (event: Record<string, unknown>) => void,
    private report: (type: string) => void,
    private now: () => number = () => performance.now(),
  ) {}
  start(id: string) {
    if (this.id) return;
    this.id = id; this.at = this.now();
    this.send({ type: 'session.instructions.append', event_id: id, delegation_id: null,
      content: '日本語で、相手の発言を待たずに今すぐ「もしもし」とだけ一度話し、その後は相手の話を聞いてください。' });
  }
  observe(event: Record<string, unknown>) {
    if (!this.id || this.finished) return;
    if (event.type === 'session.instructions.appended' && event.client_event_id === this.id && !this.acknowledged) {
      this.acknowledged = true; this.report('greeting_accepted');
      this.nudge();
    } else if (event.type === 'error' && (event.error as { event_id?: string })?.event_id === this.id) {
      this.finished = true; this.report('greeting_rejected');
    } else if (event.type === 'session.input_transcript.delta' && String(event.delta || '').trim()) {
      this.userSpoke = true;
    } else if (event.type === 'session.output_transcript.delta' && String(event.delta || '').trim()) {
      if (!this.heard) this.report('greeting_output_started');
      this.heard = true;
    }
  }
  audio() {
    if (this.id && !this.audioHeard) {
      this.audioHeard = true; this.report('greeting_audio_started');
    }
  }
  tick() {
    if (!this.id || this.finished || this.heard || this.audioHeard || this.userSpoke) return;
    const elapsed = this.now() - this.at;
    if (elapsed >= 12000) { this.finished = true; this.report('greeting_no_output'); }
    else if (this.acknowledged && this.attempts === 1 && elapsed >= 5000) this.nudge();
  }
  private nudge() {
    if (this.heard || this.audioHeard || this.userSpoke) return;
    this.attempts++;
    this.send({ type: 'session.commentary.append', delegation_id: null,
      content: '今、指定の挨拶から会話を始めてください。' });
    this.report(this.attempts === 1 ? 'greeting_prompted' : 'greeting_reprompted');
  }
}
