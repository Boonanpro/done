/** Gemini Live audio transport. Existing LiveBackend owns Astra and tool execution. */
type Event = { type: string; [key: string]: unknown };
type Message = {
  setupComplete?: object;
  serverContent?: {
    interrupted?: boolean; turnComplete?: boolean; interactionStatus?: string;
    inputTranscription?: { text?: string }; outputTranscription?: { text?: string };
    modelTurn?: { parts?: Array<{ inlineData?: { data: string; mimeType: string } }> };
  };
  interactionStatus?: string;
  toolCall?: { functionCalls?: Array<{ id: string; name: string; args?: { request?: string } }> };
  toolCallCancellation?: { ids?: string[] };
  sessionResumptionUpdate?: { resumable?: boolean; newHandle?: string };
  goAway?: object;
  error?: { message?: string };
};

export class GeminiTransport {
  connectionState = 'connecting';
  interactionStatus = 'IDLE';
  readonly model = 'gemini-3.8-live-extended-thinking';
  readonly output: MediaStreamAudioDestinationNode;
  private socket: WebSocket | null = null;
  private input: MediaStreamAudioSourceNode | null = null;
  private filter: BiquadFilterNode | null = null;
  private capture: AudioWorkletNode | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private at = 0;
  private closed = false;
  private greeted = false;
  private resumeHandle = '';
  private retries = 0;
  private pending = new Set<string>();
  private seen = new Set<string>();
  private outgoing: object[] = [];
  private commentary = '';
  private commentaryTimer?: ReturnType<typeof setTimeout>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;

  constructor(private context: AudioContext, private session: { token: string; session: { id: string } },
    private emit: (event: Event) => void, private interruptOutput: () => void,
    private resumeOutput: () => void) {
    this.output = context.createMediaStreamDestination();
  }

  async start(microphone: MediaStream) {
    if (this.context.sampleRate !== 48000) throw new Error('Gemini音声には48kHzの入力処理が必要です');
    await this.context.audioWorklet.addModule('/gemini-mic-worklet.js');
    if (this.closed) return;
    this.input = this.context.createMediaStreamSource(microphone);
    this.filter = this.context.createBiquadFilter();
    this.filter.type = 'lowpass'; this.filter.frequency.value = 7000; this.filter.Q.value = .707;
    this.capture = new AudioWorkletNode(this.context, 'gemini-mic');
    this.input.connect(this.filter).connect(this.capture).connect(this.context.destination);
    this.capture.port.onmessage = event => {
      if (this.connectionState !== 'connected' || !this.socket || this.socket.bufferedAmount > 64000) return;
      const bytes = new Uint8Array(event.data as ArrayBuffer);
      let binary = ''; for (const value of bytes) binary += String.fromCharCode(value);
      this.send({ realtimeInput: { audio: { data: btoa(binary), mimeType: 'audio/pcm;rate=16000' } } });
    };
    await this.open();
  }

  private open(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.closed) { reject(new Error('音声接続は終了しています')); return; }
      this.connectionState = 'connecting';
      const socket = new WebSocket('wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token=' + encodeURIComponent(this.session.token));
      this.socket = socket;
      let ready = false;
      const timeout = setTimeout(() => { reject(new Error('Geminiの開始がタイムアウトしました')); socket.close(); }, 20000);
      socket.onopen = () => this.send({ setup: {
        model: 'models/' + this.model,
        ...(this.resumeHandle ? { sessionResumption: { handle: this.resumeHandle } } : {}),
      } });
      socket.onmessage = async event => {
        if (this.closed || socket !== this.socket) return;
        try {
          const raw = typeof event.data === 'string' ? event.data : await (event.data as Blob).text();
          const message = JSON.parse(raw) as Message;
          if (message.setupComplete) {
            clearTimeout(timeout); ready = true; this.connectionState = 'connected';
            for (const pending of this.outgoing.splice(0)) this.send(pending);
            this.emit({ type: 'session.started', session: { id: this.session.session.id, model: this.model } });
            resolve();
          }
          this.receive(message);
        } catch { this.emit({ type: 'error', error: { message: 'Geminiの応答を処理できませんでした' } }); }
      };
      socket.onerror = () => { if (!ready) { clearTimeout(timeout); reject(new Error('Geminiへの接続に失敗しました')); } };
      socket.onclose = () => {
        clearTimeout(timeout);
        if (!ready) reject(new Error('Geminiの接続が開始前に閉じました'));
        if (this.closed || socket !== this.socket) return;
        this.stopAudio();
        if (ready && this.resumeHandle && this.retries++ < 3) {
          this.connectionState = 'connecting';
          this.reconnectTimer = setTimeout(() => { void this.open().catch(() => this.fail()); }, 300);
        } else this.fail();
      };
    });
  }

  private fail() {
    if (this.closed) return;
    this.connectionState = 'failed';
    this.emit({ type: 'session.closed' });
  }

  receive(message: Message) {
    if (this.closed) return;
    if (message.error) this.emit({ type: 'error', error: { message: message.error.message || 'Gemini error' } });
    const update = message.sessionResumptionUpdate;
    if (update?.resumable && update.newHandle) this.resumeHandle = update.newHandle;
    const content = message.serverContent;
    const status = message.interactionStatus || content?.interactionStatus;
    // turnComplete ends an utterance, never the background task or connection.
    if (status) this.interactionStatus = status;
    if (content?.interrupted) { this.stopAudio(); this.interruptOutput(); this.emit({ type: 'audio.interrupted' }); }
    for (const role of ['input', 'output'] as const) {
      const text = (role === 'input' ? content?.inputTranscription : content?.outputTranscription)?.text;
      if (text) this.emit({ type: `session.${role}_transcript.delta`, delta: text, start_ms: performance.now(), end_ms: performance.now() });
    }
    for (const part of content?.modelTurn?.parts || []) {
      if (part.inlineData?.mimeType.startsWith('audio/pcm')) this.play(part.inlineData.data);
    }
    for (const id of message.toolCallCancellation?.ids || []) this.pending.delete(id);
    for (const call of message.toolCall?.functionCalls || []) {
      if (this.seen.has(call.id)) continue;
      this.seen.add(call.id);
      if (call.name !== 'ask_dan') continue;
      // LiveBackend steers the active request to the newest input. Settle older
      // function IDs so Gemini does not keep waiting for a superseded response.
      for (const id of this.pending) this.send({ toolResponse: { functionResponses: [{ id, name: 'ask_dan', response: {
        status: 'superseded', detail: '最新の依頼へ更新中です。最終結果は新しい呼び出しへ返ります。', scheduling: 'SILENT',
      } }] } });
      this.pending.clear();
      this.pending.add(call.id);
      this.emit({ type: 'session.delegation.created', delegation: { id: call.id }, request: call.args?.request || '' });
    }
    if (message.goAway && this.resumeHandle) this.socket?.close();
  }

  private play(encoded: string) {
    const data = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
    const pcm = new DataView(data.buffer);
    const buffer = this.context.createBuffer(1, Math.floor(data.length / 2), 24000);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < channel.length; i++) channel[i] = pcm.getInt16(i * 2, true) / 32768;
    const source = this.context.createBufferSource(); source.buffer = buffer; source.connect(this.output);
    this.resumeOutput();
    this.at = Math.max(this.at, this.context.currentTime + .015);
    this.sources.add(source);
    source.onended = () => { this.sources.delete(source); source.disconnect(); };
    source.start(this.at); this.at += buffer.duration;
  }

  private stopAudio() {
    for (const source of this.sources) { try { source.stop(); source.disconnect(); } catch {} }
    this.sources.clear(); this.at = 0;
  }

  private send(message: object) {
    if (this.closed) return;
    const setup = 'setup' in message;
    if (this.socket?.readyState === WebSocket.OPEN && (setup || this.connectionState === 'connected')) {
      this.socket.send(JSON.stringify(message));
    } else if (!setup && !('realtimeInput' in message)) this.outgoing.push(message);
  }

  complete(id: string, text: string) {
    if (this.pending.delete(id)) {
      this.send({ toolResponse: { functionResponses: [{ id, name: 'ask_dan', response: { result: text, scheduling: 'WHEN_IDLE' } }] } });
    } else if (!this.seen.has(id)) this.notify(text);
  }

  error(text: string) {
    for (const id of this.pending) this.send({ toolResponse: { functionResponses: [{ id, name: 'ask_dan', response: { error: text, scheduling: 'WHEN_IDLE' } }] } });
    this.pending.clear();
    this.notify(text);
  }

  notify(text: string) {
    this.send({ clientContent: { turns: [{ role: 'user', parts: [{ text: 'バックエンドからの報告です。未確認・途中・完了を区別して伝えてください。\n' + text }] }], turnComplete: true } });
  }

  sendText(text: string) {
    this.send({ clientContent: { turns: [{ role: 'user', parts: [{ text }] }], turnComplete: true } });
  }

  append(event: Event) {
    if (event.type !== 'session.commentary.append') return;
    this.commentary += String(event.content || '');
    clearTimeout(this.commentaryTimer);
    this.commentaryTimer = setTimeout(() => { const text = this.commentary; this.commentary = ''; if (text) this.notify(text); }, 0);
  }

  greet() {
    if (this.greeted || this.connectionState !== 'connected') return false;
    this.greeted = true;
    this.sendText('日本語で「もしもし」とだけ一度話し、その後は相手の話を聞いてください。');
    return true;
  }

  close() {
    if (this.closed) return;
    this.closed = true; this.connectionState = 'closed';
    clearTimeout(this.commentaryTimer); clearTimeout(this.reconnectTimer);
    this.socket?.close(); this.stopAudio(); this.pending.clear();
    this.outgoing = [];
    this.capture?.disconnect(); this.filter?.disconnect(); this.input?.disconnect();
    this.output.disconnect(); this.output.stream.getTracks().forEach(track => track.stop());
  }
}
