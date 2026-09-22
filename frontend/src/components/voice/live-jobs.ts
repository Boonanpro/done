type JobEvent = { seq: number; kind: string; text: string };
export type LiveJob = { id: string; task: string; state: string; seq: number; created_at: string;
  events: JobEvent[]; report_message_id?: string; confirmation?: { id: string; summary: string } };

/** Speech receives observations, not a replay of the original imperative task. */
export function liveJobObservation(job: LiveJob, event: JobEvent) {
  const kind = ['result','error','confirmation'].includes(event.kind) ? 'commentary' : 'thinking';
  const state = event.kind === 'progress' ? '作業中。完了結果はまだありません。' :
    event.kind === 'confirmation' ? '本人への確認待ち' : event.kind === 'error' ? '問題が発生' : job.state;
  // Identifiers stay in the application/backend context. They are not speech
  // content and must not become something the caller hears read aloud.
  return {kind, text:`状態: ${state}\n今回の報告: ${event.text}`} as const;
}

/** Coalesce progress, retain confirmations and results, never replay old completions. */
export class LiveJobs {
  private seen = new Map<string, number>();
  constructor(private connectedAt = Date.now()) {}
  updates(jobs: LiveJob[]) {
    const updates: { job: LiveJob; event: JobEvent }[] = [];
    for (const job of jobs) {
      const previous = this.seen.get(job.id);
      this.seen.set(job.id, job.seq);
      if (previous === undefined && Date.parse(job.created_at) < this.connectedAt &&
          ['completed', 'failed', 'cancelled'].includes(job.state)) continue;
      let fresh = job.events.filter(e => e.seq > (previous ?? 0));
      if (previous === undefined && Date.parse(job.created_at) < this.connectedAt) fresh = fresh.slice(-1);
      const progress = fresh.filter(e => e.kind === 'progress' && !fresh.some(r => r.kind === 'result' && r.text === e.text)).slice(-1);
      for (const event of fresh.filter(e => ['confirmation', 'result', 'error', 'applied'].includes(e.kind)).concat(progress).sort((a,b) => a.seq-b.seq)) {
        updates.push({ job, event });
      }
    }
    return updates;
  }
}
