'use client';

/** Live 1 owns conversation; the server answers delegations and speaks job results into the call. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

import { VoiceOrb } from './voice-orb';
import { connectAtomWifi, type AtomWifiTransport } from './atom-wifi-transport';
import { waitForStandbyDrain } from './standby-drain';

import { LiveJobs, type LiveJob } from './live-jobs';
import { LiveGreeting } from './live-greeting';
import { WorkWaiting, isWorking } from './work-waiting';
import { WaitingAudio } from './waiting-audio';

type Status = 'idle' | 'connecting' | 'connected' | 'error';
type RtEvent = { type: string; [key: string]: unknown };

interface VoiceSessionProps {
  roomId: string;
  chatTitle?: string;
  onClose: () => void;
}

export function VoiceSession({ roomId, onClose }: VoiceSessionProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [currentActivity, setCurrentActivity] = useState<string | null>(null);
  /** オーブ下に出す活動フィード（ツール実行・委譲の進行を1行ずつ）。文字起こしは出さない。 */
  const [activity, setActivity] = useState<string[]>([]);
  const liveSessionIdRef = useRef('');
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

  const pushActivity = useCallback((line: string) => {
    setActivity((a) => [...a, line].slice(-5));
  }, []);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const atomWifiRef = useRef<AtomWifiTransport | null>(null);
  const genRef = useRef(0);

  const guardianTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---- オーブ駆動用の音量計測 ----
  const audioCtxRef = useRef<AudioContext | null>(null);
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
        body: JSON.stringify({ role, content: content.slice(0, 7500), created_at: createdAt }),
        keepalive: true,
      }).catch(() => {});
    },
    [authHeaders, roomId],
  );

  const dcSend = useCallback((obj: unknown) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === 'open') dc.send(JSON.stringify(obj));
  }, []);

  // The server speaks job results into the call itself; the screen only shows the activity.
  useEffect(() => {
    if (status !== 'connected') return;
    const jobs = new LiveJobs();
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
        setCurrentActivity(workingJobsRef.current ? '作業中' : null);
        for (const {event} of jobs.updates(rows)) pushActivity(event.text);
      } catch (error) { pushLog('⚠', '作業状況の同期に失敗しました'); }
      finally { polling = false; }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 1500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [status,roomId,authHeaders,pushActivity,pushLog]);

  const disconnect = useCallback(() => {
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
    atomWifiRef.current?.close();
    atomWifiRef.current = null;
    if (audioRef.current) {
      audioRef.current.srcObject = null;
      audioRef.current.remove();
      audioRef.current = null;
    }
    void audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    micAnalyserRef.current = null;
    aiAnalyserRef.current = null;
    setSpeaking(false);
    setCurrentActivity(null);
    setStatus((s) => (s === 'error' ? 'error' : 'idle'));
  }, [authHeaders]);

  const connect = useCallback(async () => {
    disconnect();
    genRef.current += 1;
    const myGen = genRef.current;
    const live = () => genRef.current === myGen;

    setStatus('connecting');
    setError(null);
    setActivity([]);
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
    const endCall = async () => {
      if (ending || !live()) return;
      ending = true;
      waiting.close();
      micRef.current?.getAudioTracks().forEach(track => { track.enabled = false; });
      (window as Window & { atomEvent?: (event: Record<string, unknown>) => void }).atomEvent?.({ type: 'standby_requested' });
      // A completed end-call request wins over further model speech. Allow a
      // short audible tail, but never wait indefinitely for Live to stop talking.
      await waitForStandbyDrain(() => ({ active: live(), generating: false, playing: outputPlaying, epoch: 0 }),
        { tailMs: 150, timeoutMs: 700 });
      if (!live()) return;
      flush('user'); flush('assistant');
      try {
        await atomWifiRef.current?.standby();
        disconnect();
      } catch (error) {
        setError('待機への切り替えに失敗しました'); setStatus('error'); disconnect();
        throw error;
      }
    };
    // The server ends the call (backend end_call → session.close): the Atom returns
    // to standby; a browser call closes the voice panel.
    const hangUp = () => {
      if (ending || !live()) return;
      if (atomWifiRef.current) { void endCall().catch(() => {}); return; }
      ending = true;
      waiting.close();
      disconnect();
      onClose();
    };
    const greeting = new LiveGreeting(dcSend, type => {
      (window as Window & { atomEvent?: (event: { type: string }) => void }).atomEvent?.({ type });
    });
    (window as Window & { __atomGreet?: () => boolean }).__atomGreet = () => {
      if (!live() || !started || ending || !atomWifiRef.current) return false;
      if (dcRef.current?.readyState !== 'open') return false;
      greeting.start(crypto.randomUUID());
      return true;
    };
    let ready: () => void = () => {};
    let failed: (error: Error) => void = () => {};
    const opened = new Promise<void>((resolve, reject) => { ready = resolve; failed = reject; });
    void opened.catch(() => {});
    const handleLiveEvent = (msg: RtEvent) => {
      if (!live()) return;
      greeting.observe(msg);
      if (msg.type === 'session.started') {
        started = true; ready();
        (window as Window & { __atomConfig?: unknown }).__atomConfig = { model: 'gpt-live-1', backend: 'gpt-6-astra' };
        pushLog('✅', 'Live 1 connected');
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
    let atomWifi: AtomWifiTransport | null = null;
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
      atomWifi?.close();
      if (atomWifiRef.current === atomWifi) atomWifiRef.current = null;
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
      atomWifi = await connectAtomWifi(roomId, audioCtx);
      waitingAudioRef.current = new WaitingAudio(audioCtx, atomWifi?.cueOutput ?? audioCtx.destination);
      if (!live()) { cleanupLocal(); return; }
      atomWifiRef.current = atomWifi;
      if (atomWifi) audioEl.volume = 0;

      pc.ontrack = (e) => {
        const stream = e.streams[0] || new MediaStream([e.track]);
        if (audioEl) { audioEl.srcObject = stream; void audioEl.play().catch(() => {}); }
        atomWifi?.play(stream);
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
        mic = atomWifi?.stream ?? await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        throw new Error('マイクの使用が許可されませんでした');
      }
      if (!live()) {
        cleanupLocal();
        return;
      }
      for (const track of mic.getAudioTracks()) pc.addTrack(track, mic);
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
        body: JSON.stringify({ room_id: roomId, sdp: peer.localDescription?.sdp, provider: 'openai', device: !!atomWifi,
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
      setStatus('connected');
      // Live is full duplex. Observe actual audio instead of guessing from backend turns.
      const samples = new Float32Array(1024);
      guardianTimerRef.current = setInterval(() => {
        if (!live() || ending) return;
        greeting.tick();
        const analyser = aiAnalyserRef.current;
        if (!analyser) return;
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
        if (rms > .004) { lastOutput = performance.now(); outputPlaying = true; greeting.audio(); }
        else if (performance.now() - lastOutput > 500) outputPlaying = false;
        waiting.update(performance.now(), isWorking(undefined, workingJobsRef.current),
          outputPlaying || readLevel(micAnalyserRef.current) > .025, started && !ending);
        setSpeaking(outputPlaying);
      }, 100);
    } catch (e) {
      cleanupLocal();
      closeSession();
      if (!live()) return;
      setError(e instanceof Error ? e.message : '接続に失敗しました');
      setStatus('error');
    }
  }, [authHeaders, dcSend, disconnect, onClose, roomId, saveTranscript, pushLog]);

  useEffect(() => {
    void connect();
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col items-center gap-3 p-4">
      <div className="flex w-full items-center justify-between">
        <span className="text-xs text-muted-foreground">
          音声モード
        </span>
        <button
          type="button"
          onClick={() => {
            disconnect();
            onClose();
          }}
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="音声モードを閉じる"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <VoiceOrb size={150} getUserLevel={getUserLevel} getAiLevel={getAiLevel} active={status === 'connected'} />

      <div className="min-h-5 text-center text-xs text-muted-foreground">
        {status === 'connecting' && '接続中…'}
        {status === 'error' && <span className="text-destructive">{error}</span>}
        {status === 'connected' && currentActivity && `（${currentActivity}）`}
        {status === 'connected' && !currentActivity && (speaking ? '' : '')}
      </div>

      {activity.length > 0 && (
        <div className="w-full space-y-1 border-t border-border pt-2">
          {activity.map((line, i) => (
            <p key={i} className="truncate text-center text-xs text-muted-foreground">
              {line}
            </p>
          ))}
        </div>
      )}

      {status === 'error' && (
        <button
          type="button"
          onClick={() => void connect()}
          className="rounded-md border border-border px-3 py-1 text-xs text-foreground hover:bg-accent"
        >
          再接続
        </button>
      )}
    </div>
  );
}
