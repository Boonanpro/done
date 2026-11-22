import { promptRequest } from '@/lib/prompts-api';

export interface CircuitStep {
  at: string; node: string; label: string; detail: string;
  ms?: number; model?: string; prompts?: string[]; prompt?: string;
}
export const localStep = (node: string, label: string, detail = ''): CircuitStep =>
  ({at: new Date().toISOString(), node, label, detail});

export async function silentTrial(opts: {
  room: string; preview: boolean; words: string; file: File | null; signal: AbortSignal;
  append: (...steps: CircuitStep[]) => void; session: (id: string) => void;
}) {
  const {room, preview, signal, append} = opts;
  const ctx = new AudioContext();
  const peer = new RTCPeerConnection();
  const channel = peer.createDataChannel('oai-events');
  const destination = ctx.createMediaStreamDestination();
  const source = ctx.createBufferSource();
  let sessionId = '';
  let ended = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  let settle!: () => void;
  let fail!: (err: Error) => void;
  const done = new Promise<void>((ok, no) => { settle = ok; fail = no; });
  void done.catch(() => {});
  const abort = () => { peer.close(); fail(new Error('音声テストを終了しました。')); };
  signal.addEventListener('abort', abort);
  let ownerWords = '', answer = '', played = false, previewed = false;
  const check = () => { if (signal.aborted || ended) throw new Error('音声テストを終了しました。'); };
  const previewRoute = async () => {
    if (!preview || previewed || !ownerWords.trim()) return;
    previewed = true;
    const rows = await promptRequest<CircuitStep[]>('/circuit/preview', {room, channel:'voice', words:ownerWords});
    check();
    append(...rows);
  };
  let delegated = false;
  let clipEnded = false;
  let finishing = false;
  const finish = async () => {
    if (finishing) return;
    finishing = true;
    check();
    if (!ownerWords.trim()) throw new Error('音声の文字起こしを受け取れませんでした。');
    append(localStep('voice', '聞き取った言葉', ownerWords));
    if (preview && delegated) await previewRoute();
    if (answer) append(localStep('voice', 'ダンが話した言葉', answer));
    if (preview && !delegated) append(localStep('voice', 'この音声への返答中に委譲の記録なし'));
    settle();
  };
  function idle() {
    if (!clipEnded) return;
    clearTimeout(timer);
    timer = setTimeout(() => { void finish().catch(fail); }, preview ? 6000 : 12000);
  }
  try {
    await ctx.resume();
    let bytes: ArrayBuffer;
    if (opts.file) {
      if (opts.file.size > 16 * 1024 * 1024) throw new Error('16MB以下の音声を選んでください。');
      bytes = await opts.file.arrayBuffer();
    } else {
      const {audio} = await promptRequest<{audio: string}>('/circuit/speech', {words:opts.words});
      bytes = Uint8Array.from(atob(audio), c => c.charCodeAt(0)).buffer;
    }
    check();
    const buffer = await ctx.decodeAudioData(bytes);
    if (buffer.duration > 90) throw new Error('90秒以内の音声を選んでください。');
    source.buffer = buffer;
    // No hardware microphone, media element or speaker destination in either mode.
    source.connect(destination);
    destination.stream.getAudioTracks().forEach(track => peer.addTrack(track, destination.stream));
    source.onended = () => { clipEnded = true; if (!ended) append(localStep('owner', '音声入力の終わり')); idle(); };
    const modelAudio = ctx.createAnalyser();
    peer.ontrack = event => {
      const stream = event.streams[0] || new MediaStream([event.track]);
      ctx.createMediaStreamSource(stream).connect(modelAudio);
    };
    channel.onmessage = ({data}) => {
      if (ended || signal.aborted) return;
      let msg;
      try { msg = JSON.parse(data); } catch { return; }
      if (msg.type === 'session.started' && !played) {
        played = true;
        append(localStep('owner', '音声を入力', opts.file?.name || opts.words));
        source.start();
      } else if (msg.type === 'session.input_transcript.delta') {
        if (!ownerWords && msg.delta) append(localStep('voice', '聞き取り開始'));
        ownerWords += msg.delta || ''; idle();
      } else if (msg.type === 'session.output_transcript.delta') {
        if (!answer && msg.delta) append(localStep('voice', 'ダンの返答開始'));
        answer += msg.delta || ''; idle();
      } else if (msg.type === 'session.delegation.created') {
        delegated = true;
        append(localStep('router', '音声モデルから委譲'));
        idle();
      } else if (msg.type === 'session.closed') {
        void finish().catch(fail);
      } else if (msg.type === 'error') fail(new Error('音声モデルがエラーを返しました。'));
    };
    channel.onclose = () => { if (!ended) fail(new Error('音声接続が閉じました。')); };
    await peer.setLocalDescription(await peer.createOffer());
    if (peer.iceGatheringState !== 'complete') await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('音声接続を準備できませんでした。')), 10000);
      peer.onicegatheringstatechange = () => {
        if (peer.iceGatheringState === 'complete') { clearTimeout(timeout); resolve(); }
      };
    });
    check();
    const endpoint = preview ? '/live/preview-session' : '/live/session';
    const session = await promptRequest<{session: {id:string}; transport:{sdp:string}; preview_only?: boolean; prompts?: string[]}>(
      endpoint, {room_id:room, sdp:peer.localDescription?.sdp, timezone:Intl.DateTimeFormat().resolvedOptions().timeZone}, '/api/v1/voicelog');
    sessionId = session.session.id;
    check();
    if (preview && !session.preview_only) throw new Error('実行前で止める音声接続を確認できませんでした。');
    if (session.prompts?.length) append({...localStep('voice', '通話の指示文を準備'), prompts:session.prompts});
    if (!preview) opts.session(sessionId);
    await peer.setRemoteDescription({type:'answer', sdp:session.transport.sdp});
    deadline = setTimeout(() => fail(new Error('音声テストが時間内に応答しませんでした。')), (buffer.duration + 45) * 1000);
    await done;
  } finally {
    ended = true;
    clearTimeout(deadline);
    source.onended = null;
    clearTimeout(timer);
    signal.removeEventListener('abort', abort);
    channel.onclose = channel.onmessage = null;
    if (channel.readyState === 'open') channel.send(JSON.stringify({type:'session.close'}));
    peer.close();
    destination.stream.getTracks().forEach(track => track.stop());
    await ctx.close();
    if (sessionId && !preview) await promptRequest('/live/backend/close', {session_id:sessionId}, '/api/v1/voicelog').catch(() => {});
  }
}

