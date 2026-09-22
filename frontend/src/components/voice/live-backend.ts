/** Live owns speech. The application backend owns history, reasoning and tools. */
type Item = Record<string, unknown>;
type Call = Item & { type: 'function_call'; name: string; call_id: string; arguments?: string };
export type LiveWorkState = {state: 'reasoning'|'reading'|'executing'|'complete'|'failed'; tool?: string; action?: string; query?: unknown; result?: string};
export class LiveBackend {
  private closed = false;
  private revision = 0;
  private queue = Promise.resolve();
  private inputs: Item[] = [];
  private calls = new Map<string, Promise<Item>>();
  private delegations = new Set<string>();
  private speechCoverage = new Map<number, number>();
  private speechTurns = new Map<string, number>();
  private finalRequired = new Set<number>();
  private finalSpeech = new Map<number,{length:number;context:()=>Item[]}>();
  private active: { revision: number; id: string } | null = null;
  private steering: Promise<void> = Promise.resolve();

  constructor(private request: (input: Item[], onText?: (text: string) => void) => Promise<{ output: Item[] }>,
    private execute: (name: string, args: Item, delegationId: string) => Promise<Item>,
    private report: (text: string, delegationId: string) => void,
    private error: (message: string) => void,
    private onClose: () => void = () => {},
    private steer?: (input: Item[]) => Promise<{ accepted: boolean }>,
    private observe?: (state: LiveWorkState, delegationId: string) => void) {}

  close() { if (this.closed) return; this.closed = true; this.onClose(); }
  addInput(item: Item) { this.inputs.push(item); }

  /** Cover each spoken input once, whether Live delegates it or the active-job
   * fallback does. A later extension of the same utterance remains steerable. */
  delegateSpeech(id: string, turn: number, length: number, context: () => Item[]) {
    if (turn && (this.speechCoverage.get(turn) ?? -1) >= length) return;
    if (turn) this.speechCoverage.set(turn,length);
    this.speechTurns.set(id,turn);
    if(this.speechTurns.size>128)this.speechTurns.delete(this.speechTurns.keys().next().value!);
    if (this.speechCoverage.size > 128) this.speechCoverage.delete(this.speechCoverage.keys().next().value!);
    this.delegate(id,context);
  }

  followupSpeech(turn: number, length: number, context: () => Item[]) {
    this.finalSpeech.set(turn,{length,context});
    if(this.finalSpeech.size>128)this.finalSpeech.delete(this.finalSpeech.keys().next().value!);
    if (this.finalRequired.delete(turn)) this.speechCoverage.delete(turn);
    this.delegateSpeech(`followup-${turn}-${length}`,turn,length,()=>[...context(),{role:'user',
      content:'実行中の仕事への追加発言です。未反映の補足や変更があれば同じ仕事へ届けてください。既に反映済みの内容や、仕事に関係しない会話で新しい仕事を作らないでください。'}]);
  }

  delegate(id: string, context: () => Item[]) {
    if (this.closed || this.delegations.has(id)) return;
    this.delegations.add(id);
    const revision = ++this.revision;
    const active = this.active;
    if (active && this.steer) {
      const input = [...context(), ...this.inputs.splice(0)];
      this.steering = this.steering.then(async () => {
        if (this.closed) return;
        const result = await this.steer!(input);
        if (result.accepted) {
          active.revision = revision; active.id = id;
        } else {
          this.enqueue(id, revision, () => input);
        }
      }).catch(error => { if (!this.closed) this.error(String(error)); });
      return;
    }
    this.enqueue(id, revision, context);
  }

  private enqueue(id: string, revision: number, context: () => Item[]) {
    this.queue = this.queue.then(async () => {
      if (this.closed || revision !== this.revision) return;
      const active = { revision, id };
      this.active = active;
      let backgroundRevision: number | undefined;
      const report = (text: string) => {
        // The job feed owns completion reporting. A coordinator's acceptance
        // sentence is neither a second spoken answer nor job completion.
        if (backgroundRevision !== active.revision) this.report(text,active.id);
      };
      try {
      this.observe?.({state:'reasoning'},active.id);
      let input = [...context(), ...this.inputs.splice(0)];
      for (let step = 0; step < 16; step++) {
        if (this.closed) return;
        const requestRevision = active.revision;
        let delivered = '', buffered = '';
        const response = await this.request(input, delta => {
          if (this.closed || requestRevision !== active.revision || active.revision !== this.revision) return;
          buffered += delta;
          // Deliver complete sentences, never individual tokens or worker commentary.
          const end = Math.max(buffered.lastIndexOf('。'),buffered.lastIndexOf('！'),buffered.lastIndexOf('？'));
          if (end >= 0) {
            const sentence = buffered.slice(0,end+1);buffered=buffered.slice(end+1);
            delivered += sentence;report(sentence);
          }
        });
        if ((response as {awaiting_final_input?:boolean}).awaiting_final_input) {
          const turn=this.speechTurns.get(active.id);
          if (turn) {
            this.finalRequired.add(turn);
            const final=this.finalSpeech.get(turn);
            if(final)this.followupSpeech(turn,final.length,final.context);
          }
        }
        await this.steering;
        const calls = response.output.filter(item => item.type === 'function_call') as Call[];
        if (!calls.length) {
          const text = response.output.filter(item => item.type === 'message').flatMap(item =>
            (item.content as Array<{ type: string; text?: string }> || []).filter(c => c.type === 'output_text').map(c => c.text || '')).join('\n');
          if (!this.closed && active.revision === this.revision) {
            this.observe?.({state:backgroundRevision === active.revision ? 'executing' : 'complete'},active.id);
            // Steering may replace a final answer after an earlier sentence was
            // already spoken. Do not silently discard that revised answer.
            const remaining = delivered && text.startsWith(delivered) ? text.slice(delivered.length) : text;
            if (remaining.trim()) report(remaining);
          }
          return;
        }
        const results = await Promise.all(calls.map(call => {
          if (!this.calls.has(call.call_id)) this.calls.set(call.call_id, this.run(call, requestRevision, active.id));
          return this.calls.get(call.call_id)!;
        }));
        calls.forEach((call,index) => {
          let args: Item;
          try {args=JSON.parse(call.arguments || '{}');} catch {return;}
          const result=JSON.parse(String(results[index].output || '{}'));
          if ((call.name==='delegate_to_dan' || (call.name==='command_center' && ['delegate','work'].includes(String(args.action)))) && result.accepted)
            backgroundRevision=active.revision;
          if (call.name==='control_dan_task' && !result.error && ['running','queued','awaiting_confirmation','paused'].includes((result.job || result).state))
            backgroundRevision=active.revision;
        });
        input = [...results, ...this.inputs.splice(0)];
      }
      throw new Error('確認処理が長くなったため停止しました');
      } finally { if (this.active === active) this.active = null; }
    }).catch(error => { if (!this.closed) {
      this.observe?.({state:'failed'},id);
      this.error(error instanceof Error ? error.message : String(error));
    } });
  }

  private async run(call: Call, revision: number, delegationId: string): Promise<Item> {
    let result: Item;
    try {
      const args = JSON.parse(call.arguments || '{}');
      // A follow-up question must not discard a lookup already selected by the
      // worker. Only side-effecting actions need revalidation after new input.
      const readOnly = ['read_room_history', 'check_dan_status', 'web_search'].includes(call.name)
        || (call.name === 'command_center' && ['search','read','overview','list','status','requests','jobs'].includes(String(args.action)));
      if (this.closed || (revision !== this.revision && !readOnly)) throw new Error('Request superseded; action not started');
      this.observe?.({state:readOnly?'reading':'executing',tool:call.name,action:args.action as string|undefined,query:args.keywords||args.query},delegationId);
      result = await this.execute(call.name, args, delegationId);
      if (!this.closed) this.observe?.({state:result.error?'failed':'reasoning',tool:call.name,action:args.action as string|undefined,
        result:result.error ? String(result.error).slice(0,300) : 'ツールの結果を受信済み'},delegationId);
    } catch (error) { result = { error: error instanceof Error ? error.message : String(error) }; }
    return { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result) };
  }
}

/** Consume a streamed tool turn without retrying a possibly executed request. */
export async function readLiveBackendStream(response: Response, onText?: (text: string) => void): Promise<{output:Item[]}> {
  if (!response.ok) {
    const data = await response.json().catch(()=>({}));
    throw new Error(data.detail || `作業担当への接続に失敗しました (${response.status})`);
  }
  if (!response.body) throw new Error('作業担当の応答ストリームがありません');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let pending = '', completed: {output:Item[]} | undefined;
  try {
    while (true) {
      const {done,value}=await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value,{stream:true});
      let split;
      while ((split=pending.indexOf('\n\n'))>=0) {
        const frame=pending.slice(0,split);pending=pending.slice(split+2);
        const data=frame.split('\n').filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n');
        if (!data) continue;
        const event=JSON.parse(data);
        if(event.type==='text_delta') onText?.(event.text);
        else if(event.type==='completed') {
          completed=event;
          // The application completion frame is authoritative. A proxy may keep
          // the HTTP stream open; do not hold the next tool until transport EOF.
          void reader.cancel().catch(()=>{});
          return completed!;
        }
        else if(event.type==='error') throw new Error(event.message);
      }
      if(done) break;
    }
    if(!completed) throw new Error('作業担当の応答が途中で切れました。自動再実行はしていません。');
    return completed;
  } finally {reader.releaseLock();}
}

let appendSequence = 0;
const appendEventId = () => `voice-${Date.now()}-${++appendSequence}`;

/** Appends have a 500-token ceiling; large records stay in the backend. */
export function appendLive(send: (event: Item) => void, kind: 'commentary' | 'thinking', text: string, delegationId: string | null = null) {
  // Tool records are context, not 10 separate invitations to start speaking.
  // Preserve the full record silently, then finish this delegation once.
  let record: Item | undefined;
  try { const value=JSON.parse(text); if(value && typeof value==='object' && !Array.isArray(value))record=value; } catch {}
  if(kind==='commentary' && record && !record.evidence_type) {
    appendLive(send,'thinking',text,delegationId);
    send({type:'session.commentary.append',event_id:appendEventId(),delegation_id:delegationId,
      content:'確認結果を受信しました。直前の結果に基づいて、今の質問に答えてください。'});
    return;
  }
  // Evidence is context, not a sequence of sentences to announce. Sending
  // every JSON fragment as commentary can make Live answer and then restart.
  let evidence = false;
  try { evidence = JSON.parse(text).evidence_type === 'search_excerpts'; } catch {}
  if (evidence && kind === 'commentary') {
    const result = JSON.parse(text);
    if (Array.isArray(result.evidence_context)) {
      for (const content of result.evidence_context) if (typeof content === 'string')
        send({type:'session.thinking.append',event_id:appendEventId(),delegation_id:delegationId,content});
    }
    // The server selects a complete source passage and caps it at 450 tokens.
    // Never start speaking from an incomplete JSON/source fragment.
    if (typeof result.spoken_evidence === 'string') {
      send({type:'session.commentary.append',event_id:appendEventId(),delegation_id:delegationId,content:result.spoken_evidence});
    } else {
      appendLive(send, 'thinking', text, delegationId);
    }
    return;
  }
  let part = '', bytes = 0;
  const flush = () => { if (part) send({ type: `session.${kind}.append`, event_id: appendEventId(), delegation_id: delegationId, content: part }); part = ''; bytes = 0; };
  for (const char of text) {
    const cp = char.codePointAt(0)!;
    const size = cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
    if (bytes + size > 480) flush();
    part += char; bytes += size;
  }
  flush();
}
