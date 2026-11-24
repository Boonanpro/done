'use client';

/** Live 1 owns conversation; the server answers delegations and speaks job results into the call. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { CallSketch } from './call-sketch';
import { CallOwnerScreen } from './call-owner-screen';
import { X } from 'lucide-react';

import { VoiceEdgeGlow } from './voice-edge-glow';

import type { LiveJob } from './live-jobs';
import { VoiceStage } from './voice-stage';
import { WorkWaiting, isWorking } from './work-waiting';
import { WaitingAudio } from './waiting-audio';
import { QUIET_SPEECH_MIC, liftQuietSpeech } from './quiet-speech';
import { playCallEndTone, playCallStartTone, voiceGain } from './call-tones';

type Status = 'idle' | 'connecting' | 'connected' | 'error';
type RtEvent = { type: string; [key: string]: unknown };

interface VoiceSessionProps {
  roomId: string;
  /** 本人が今見ている部屋（通話をかけた部屋と違えば、作業の頼みはそちらへ行く。call-provider.tsx） */
  focusRoomId?: string;
  chatTitle?: string;
  onClose: () => void;
  /** ダンが画面に出す物の札の幅（エディターの会話は狭い） */
  stageWidthClass?: string;
}

export function VoiceSession({ roomId, focusRoomId, onClose, stageWidthClass = 'w-[520px]' }: VoiceSessionProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);
  const [stageShown, setStageShown] = useState(false);   // a scene is on the stage: its card shows bottom-right
  const liveSessionIdRef = useRef('');
  const [callSession, setCallSession] = useState('');   // the connected call, for the parts drawn with it
  const workingJobsRef = useRef(false);
  const waitingAudioRef = useRef<WaitingAudio | null>(null);
  const flushTranscriptsRef = useRef<(() => void) | null>(null);

  // ---- 開発CLI監視用のファイルログ（scratch実験ページと同じ受け口に流す） ----
  const [logSession] = useState(() => `chat-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}`);
  const logBufferRef = useRef<Array<{ time: string; tag: string; text: string }>>([]);
  const pushLog = useCallback((tag: string, text: string) => {
    logBufferRef.current.push({
      time: new Date().toLocaleTimeString('ja-JP', { hour12: false }),
      tag,
      text,
    });
  }, []);
  useEffect(() => {
    const flush = () => {
      const batch = logBufferRef.current.splice(0);
      if (!batch.length) return;
      void fetch('/scratch/realtime-voice/api/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: logSession, entries: batch }),
      }).catch(() => {});
    };
    const t = setInterval(flush, 3000);
    return () => {
      clearInterval(t);
      flush();
    };
  }, [logSession]);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const genRef = useRef(0);

  const guardianTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---- オーブ駆動用の音量計測 ----
  const audioCtxRef = useRef<AudioContext | null>(null);
  // True from the start tone until the call ends: only a call that was open plays the hang-up tone.
  const openCallRef = useRef(false);
  const micAnalyserRef = useRef<AnalyserNode | null>(null);
  const aiAnalyserRef = useRef<AnalyserNode | null>(null);
  const levelBufRef = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(new ArrayBuffer(512)));

  const readLevel = useCallback((analyser: AnalyserNode | null): number => {
    if (!analyser) return 0;
    const buf = levelBufRef.current;
    analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i += 1) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    // RMS を体感リニアに寄せる（小声でも反応するよう平方根で持ち上げ）
    return Math.min(1, Math.sqrt(Math.sqrt(sum / buf.length)) * 1.6);
  }, []);
  const getUserLevel = useCallback(() => readLevel(micAnalyserRef.current), [readLevel]);
  const getAiLevel = useCallback(() => readLevel(aiAnalyserRef.current), [readLevel]);

  const authHeaders = useCallback((): Record<string, string> => {
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('done-token') || '' : '';
    return { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  }, []);

  /** 文字起こしを部屋の履歴へ保存（失敗しても会話は止めない） */
  const saveTranscript = useCallback(
    (role: 'user' | 'assistant', content: string, createdAt?: string) => {
      void fetch(`/api/v1/voicelog/${encodeURIComponent(roomId)}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ role, content: content.slice(0, 7500), created_at: createdAt, session_id: liveSessionIdRef.current || undefined }),
        keepalive: true,
      }).catch(() => {});
    },
    [authHeaders, roomId],
  );

  const dcSend = useCallback((obj: unknown) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === 'open') dc.send(JSON.stringify(obj));
  }, []);

  // The server speaks job results into the call itself, and the chat shows the work; this only tracks whether work runs
  // (the waiting sound plays while it does).
  useEffect(() => {
    if (status !== 'connected') return;
    let polling = false;
    let disposed = false;
    const poll = async () => {
      if (polling || disposed) return;
      polling = true;
      try {
        const response = await fetch('/api/v1/voicelog/command-center', {
          method:'POST', headers:authHeaders(), body:JSON.stringify({room_id:roomId,args:{action:'jobs'}}),
        });
        if (!response.ok || disposed) return;
        const data = await response.json();
        const rows: LiveJob[] = data.jobs || [];
        workingJobsRef.current = rows.some(job => ['queued','running'].includes(job.state));
      } catch (error) { pushLog('⚠', '作業状況の同期に失敗しました'); }
      finally { polling = false; }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 1500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [status,roomId,authHeaders,pushLog]);

  const disconnect = useCallback(() => {
    if (openCallRef.current) { openCallRef.current = false; playCallEndTone(); }
    waitingAudioRef.current?.close(); waitingAudioRef.current = null;
    workingJobsRef.current = false;
    genRef.current += 1;
    flushTranscriptsRef.current?.(); flushTranscriptsRef.current = null;
    const sessionId = liveSessionIdRef.current;
    liveSessionIdRef.current = '';
    if (sessionId) void fetch('/api/v1/voicelog/live/backend/close', {
      method:'POST',headers:authHeaders(),body:JSON.stringify({session_id:sessionId}),keepalive:true,
    }).catch(() => {});
    const channel = dcRef.current, peer = pcRef.current;
    dcRef.current = null; pcRef.current = null;
    if (channel?.readyState === 'open') {
      let closed = false;
      const finish = () => { if (closed) return; closed = true; channel.close(); peer?.close(); };
      channel.addEventListener('message', event => { try { if (JSON.parse(event.data).type === 'session.closed') finish(); } catch {} });
      channel.send(JSON.stringify({ type: 'session.close' }));
      setTimeout(finish, 3000);
    } else { channel?.close(); peer?.close(); }
    if (guardianTimerRef.current) {
      clearInterval(guardianTimerRef.current);
      guardianTimerRef.current = null;
    }
    micRef.current?.getTracks().forEach((t) => t.stop());
    micRef.current = null;
    if (audioRef.current) {
      audioRef.current.srcObject = null;
      audioRef.current.remove();
      audioRef.current = null;
    }
    void audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    micAnalyserRef.current = null;
    aiAnalyserRef.current = null;
    setStatus((s) => (s === 'error' ? 'error' : 'idle'));
  }, [authHeaders]);

  const connect = useCallback(async () => {
    disconnect();
    genRef.current += 1;
    const myGen = genRef.current;
    const live = () => genRef.current === myGen;

    setStatus('connecting');
    setError(null);
    let outputPlaying = false;
    let lastOutput = 0;
    let started = false;
    const waiting = new WorkWaiting(active => waitingAudioRef.current?.set(active));
    type Transcript = { text: string; end: number; at: string; timer?: ReturnType<typeof setTimeout> };
    const transcripts: Partial<Record<'user' | 'assistant', Transcript>> = {};
    const flush = (role: 'user' | 'assistant') => {
      const row = transcripts[role];
      if (!row) return;
      clearTimeout(row.timer); delete transcripts[role];
      if (row.text.trim()) { saveTranscript(role, row.text.trim(), row.at); pushLog(role === 'user' ? '🎤' : '🗣', row.text.trim()); }
    };
    flushTranscriptsRef.current = () => { flush('user'); flush('assistant'); };
    let ending = false;
    let hangupTimer: ReturnType<typeof setTimeout> | undefined;
    // The server ends the call (backend end_call → session.close): a browser call closes the voice panel.
    const hangUp = () => {
      if (ending || !live()) return;
      ending = true;
      waiting.close();
      disconnect();
      onClose();
    };
    let ready: () => void = () => {};
    let failed: (error: Error) => void = () => {};
    const opened = new Promise<void>((resolve, reject) => { ready = resolve; failed = reject; });
    void opened.catch(() => {});
    const handleLiveEvent = (msg: RtEvent) => {
      if (!live()) return;
      if (msg.type === 'session.started') {
        started = true; ready();
        pushLog('✅', 'Live 1 connected');
      } else if (msg.type === 'response.event' && (msg.event as { item?: { type?: string; name?: string } } | undefined)?.item?.type === 'function_call'
                 && (msg.event as { item?: { name?: string } }).item?.name === 'end_call') {
        // The backend chose end_call: hang up 3.5 s later, as the phone app does (mobile/voice.tsx), so 「切るね」 is said
        // in full. The server's session.close took 10 s more to reach this page (2026-11-03, voice_goal_call.py).
        if (!hangupTimer) hangupTimer = setTimeout(hangUp, 3500);
      } else if (msg.type === 'session.closed') {
        flush('user'); flush('assistant');
        if (started) hangUp();
        else failed(new Error('音声モデルへの接続が終了しました'));
      } else if (msg.type === 'error') {
        const message = String((msg.error as { message?: string })?.message || 'Live 1 error');
        pushLog('⚠', message);
        if (!started) failed(new Error(message));
      } else if (msg.type === 'session.input_transcript.delta' || msg.type === 'session.output_transcript.delta') {
        waiting.speech(performance.now());
        const role = msg.type === 'session.input_transcript.delta' ? 'user' : 'assistant';
        const delta = String(msg.delta || '');
        if (!delta) return;
        let row = transcripts[role];
        if (row && Number(msg.start_ms) - row.end > 1600) { flush(role); row = undefined; }
        if (!row) {
          row = { text: '', end: Number(msg.end_ms), at: new Date().toISOString() };
          transcripts[role] = row;
        }
        row.text += delta; row.end = Number(msg.end_ms);
        clearTimeout(row.timer); row.timer = setTimeout(() => flush(role), 2500);
        if (role === 'assistant') lastOutput = performance.now();
      }
    };

    let pc: RTCPeerConnection | null = null;
    let mic: MediaStream | null = null;
    let audioEl: HTMLAudioElement | null = null;
    let sessionId = '';
    const closeSession = () => {
      if (!sessionId) return;
      if (liveSessionIdRef.current === sessionId) liveSessionIdRef.current = '';
      void fetch('/api/v1/voicelog/live/backend/close', {
        method:'POST',headers:authHeaders(),body:JSON.stringify({session_id:sessionId}),keepalive:true,
      }).catch(() => {});
      sessionId = '';
    };
    const cleanupLocal = () => {
      try {
        pc?.close();
      } catch {
        /* noop */
      }
      mic?.getTracks().forEach((t) => t.stop());
      if (audioEl) {
        audioEl.srcObject = null;
        audioEl.remove();
      }
    };

    try {
      if (typeof window !== 'undefined' && !window.isSecureContext) {
        throw new Error('音声にはHTTPSかlocalhostが必要です');
      }
      const token = localStorage.getItem('done-token') || '';

      if (!live()) return;

      pc = new RTCPeerConnection();
      audioEl = document.createElement('audio');
      audioEl.autoplay = true;
      audioEl.style.display = 'none';
      document.body.appendChild(audioEl);

      const audioCtx = new AudioContext({ sampleRate: 48000 });
      audioCtxRef.current = audioCtx;
      waitingAudioRef.current = new WaitingAudio(audioCtx, audioCtx.destination);
      if (!live()) { cleanupLocal(); return; }

      pc.ontrack = (e) => {
        const stream = e.streams[0] || new MediaStream([e.track]);
        if (audioEl) { audioEl.srcObject = stream; void audioEl.play().catch(() => {}); }
        // Dan's voice plays louder than GPT-Live sends it, so the PC volume can stay low for other videos (11/22).
        // The element keeps pulling the remote stream (Chrome plays a WebRTC stream into Web Audio only then) but is
        // muted; the voice is heard through gain → limiter. If Web Audio fails, the element plays it as before.
        try {
          const voice = audioCtx.createMediaStreamSource(stream);
          const gain = audioCtx.createGain();
          gain.gain.value = voiceGain();
          const limiter = audioCtx.createDynamicsCompressor();
          limiter.threshold.value = -2; limiter.knee.value = 0; limiter.ratio.value = 20;
          limiter.attack.value = 0.002; limiter.release.value = 0.2;
          voice.connect(gain); gain.connect(limiter); limiter.connect(audioCtx.destination);
          void audioCtx.resume().catch(() => {});
          if (audioEl) audioEl.muted = true;
        } catch {
          if (audioEl) audioEl.muted = false;
        }
        // AI音声の音量 → オーブの雲の揺らめき
        try {
          const src = audioCtx.createMediaStreamSource(stream);
          const analyser = audioCtx.createAnalyser();
          analyser.fftSize = 1024;
          src.connect(analyser);
          aiAnalyserRef.current = analyser;
        } catch {
          /* noop */
        }
      };

      try {
        mic = await navigator.mediaDevices.getUserMedia({ audio: QUIET_SPEECH_MIC });
      } catch {
        throw new Error('マイクの使用が許可されませんでした');
      }
      if (!live()) {
        cleanupLocal();
        return;
      }
      // What Live hears. Muting and stopping still act on the raw mic tracks.
      const uplink = await liftQuietSpeech(audioCtx, mic);
      for (const track of uplink.getAudioTracks()) pc.addTrack(track, uplink);
      // マイク音量 → オーブ全体の揺れ
      try {
        const src = audioCtx.createMediaStreamSource(mic);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 1024;
        src.connect(analyser);
        micAnalyserRef.current = analyser;
      } catch {
        /* noop */
      }

      const dc = pc.createDataChannel('oai-events');
      pcRef.current = pc; dcRef.current = dc; micRef.current = mic; audioRef.current = audioEl;
      dc.onmessage = event => { try { handleLiveEvent(JSON.parse(event.data)); } catch (error) { pushLog('⚠', String(error)); } };
      dc.onclose = () => { failed(new Error('Live 1の接続が閉じました')); if (live() && !ending) setStatus('error'); };
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const peer = pc;
      if (peer.iceGatheringState !== 'complete') await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { peer.removeEventListener('icegatheringstatechange', check); reject(new Error('音声接続の準備がタイムアウトしました')); }, 10000);
        function check() { if (peer.iceGatheringState === 'complete') { clearTimeout(timer); peer.removeEventListener('icegatheringstatechange', check); resolve(); } }
        peer.addEventListener('icegatheringstatechange', check); check();
      });
      if (!live()) { cleanupLocal(); return; }
      const response = await fetch('/api/v1/voicelog/live/session', {
        method: 'POST', headers: authHeaders(),
        body: JSON.stringify({ room_id: roomId, sdp: peer.localDescription?.sdp, provider: 'openai',
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, server_delegation: true }),
      });
      const session = await response.json();
      if (!response.ok) throw new Error(session.detail || 'Live 1への接続に失敗しました');
      sessionId = String(session.session?.id || '');
      if (!live()) { closeSession(); cleanupLocal(); return; }
      liveSessionIdRef.current = sessionId;
      await peer.setRemoteDescription({ type: 'answer', sdp: session.transport.sdp });
      let timeout: ReturnType<typeof setTimeout> | undefined;
      try { await Promise.race([opened, new Promise<void>((_, reject) => { timeout = setTimeout(() => reject(new Error('Live 1の開始がタイムアウトしました')), 30000); })]); }
      finally { clearTimeout(timeout); }
      if (!live()) { cleanupLocal(); return; }
      setCallSession(sessionId);
      setStatus('connected');
      // The call can be spoken into from here: say so with a tone (the owner could not tell when, 11/22).
      openCallRef.current = true; playCallStartTone();
      // Live is full duplex. Observe actual audio instead of guessing from backend turns.
      const samples = new Float32Array(1024);
      guardianTimerRef.current = setInterval(() => {
        if (!live() || ending) return;
        const analyser = aiAnalyserRef.current;
        if (!analyser) return;
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
        if (rms > .004) { lastOutput = performance.now(); outputPlaying = true; }
        else if (performance.now() - lastOutput > 500) outputPlaying = false;
        waiting.update(performance.now(), isWorking(undefined, workingJobsRef.current),
          outputPlaying || readLevel(micAnalyserRef.current) > .025, started && !ending);
      }, 100);
    } catch (e) {
      cleanupLocal();
      closeSession();
      if (!live()) return;
      setError(e instanceof Error ? e.message : '接続に失敗しました');
      setStatus('error');
    }
  }, [authHeaders, dcSend, disconnect, onClose, roomId, saveTranscript, pushLog]);

  // 見ている部屋が変わったらサーバーへ（つながった直後にも1回。同じ部屋は送り直さない）
  // （サーバーの通話の準備がまだなら少し待って送り直す。最大10回）
  const sentFocusRef = useRef('');
  const [focusRetry, setFocusRetry] = useState(0);
  useEffect(() => {
    const room = focusRoomId || roomId;
    const session = liveSessionIdRef.current;
    if (status !== 'connected' || !session || sentFocusRef.current === `${session}:${room}`) return;
    sentFocusRef.current = `${session}:${room}`;
    const again = () => {
      sentFocusRef.current = '';
      if (focusRetry < 10) window.setTimeout(() => setFocusRetry((n) => n + 1), 1500);
    };
    void fetch('/api/v1/voicelog/live/backend/focus', {
      method: 'POST', headers: authHeaders(), body: JSON.stringify({ session_id: session, room_id: room }),
    }).then((r) => (r.ok ? r.json() : null)).then((d) => { if (!d?.accepted) again(); }).catch(again);
  }, [authHeaders, focusRoomId, roomId, status, focusRetry]);

  useEffect(() => {
    void connect();
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <VoiceEdgeGlow getUserLevel={getUserLevel} getAiLevel={getAiLevel} active={status === 'connected'} />

      {status === 'connected' && <div className="fixed left-1/2 top-3 z-[61] flex -translate-x-1/2 items-center gap-2">
        <CallSketch key={liveSessionIdRef.current} room={roomId} session={liveSessionIdRef.current} />
        <CallOwnerScreen key={`screen-${callSession}`} room={roomId} session={callSession} />
      </div>}

      {(status === 'connecting' || status === 'error') && (
        <div className="dark pointer-events-auto fixed left-1/2 top-3 z-[61] flex -translate-x-1/2 items-center gap-2 rounded-full border border-neutral-800 bg-neutral-950/90 px-3 py-1 text-xs text-neutral-300 shadow-lg" data-voice-status={status}>
          {status === 'connecting' && <span>音声モードに接続中…</span>}
          {status === 'error' && (
            <>
              <span className="max-w-[60vw] truncate text-red-400">{error}</span>
              <button type="button" onClick={() => void connect()} className="rounded-full border border-neutral-700 px-2 py-0.5 hover:bg-neutral-800">再接続</button>
            </>
          )}
          <button
            type="button"
            onClick={() => { disconnect(); onClose(); }}
            className="rounded-full p-0.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
            aria-label="音声モードを閉じる"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div
        className={`dark fixed bottom-4 right-4 z-50 ${stageWidthClass} max-h-[85vh] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-2xl border border-neutral-800 bg-neutral-950 p-4 shadow-2xl ${stageShown ? '' : 'pointer-events-none invisible'}`}
        data-voice-stage-card={stageShown ? 'shown' : 'hidden'}
      >
        <VoiceStage roomId={roomId} active={status === 'connected'} className="w-full" onShown={setStageShown} />
      </div>
    </>
  );
}
