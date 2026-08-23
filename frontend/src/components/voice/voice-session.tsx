'use client';

/**
 * VoiceSession — チャット統合音声モード（V1）。
 *
 * scratch 実験ページ（/scratch/realtime-voice-lp）で実測検証した機構の本番移植:
 *   - 応答スケジューラ + watchdog + guardian（沈黙の自動復旧）
 *   - レート制限の冷却バックオフ
 *   - 会話ダイエット（古いツール結果の自動削除）
 *   - コストメーター（実測トークン×公表単価）
 *
 * チャット統合で新しく足したもの:
 *   - 文字起こしを部屋の履歴に保存（/api/v1/voicelog/{roomId}）＝部屋が共有記憶
 *   - delegate_to_dan はこの部屋の room_id で実行＝ダンが同じ文脈で働く
 *   - VoiceOrb（ChatGPT風・ユーザー発話で全体が揺れ、AI発話で内部の雲が揺らぐ）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

import { VoiceOrb } from './voice-orb';

const OPENAI_CALLS_URL = 'https://api.openai.com/v1/realtime/calls';

type Status = 'idle' | 'connecting' | 'connected' | 'error';
type RtEvent = { type: string; [key: string]: unknown };

const TOOL_LABELS: Record<string, string> = {
  delegate_to_dan: 'ダンへ委譲',
  check_dan_status: '進行確認',
  look_at_screen: '画面確認',
};

interface VoiceSessionProps {
  roomId: string;
  chatTitle?: string;
  onClose: () => void;
}

export function VoiceSession({ roomId, chatTitle, onClose }: VoiceSessionProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [currentActivity, setCurrentActivity] = useState<string | null>(null);
  /** オーブ下に出す活動フィード（ツール実行・委譲の進行を1行ずつ）。文字起こしは出さない。 */
  const [activity, setActivity] = useState<string[]>([]);
  const [sessionCost, setSessionCost] = useState(0);

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
  const delegateWsRef = useRef<WebSocket | null>(null);
  const displayStreamRef = useRef<MediaStream | null>(null);
  const genRef = useRef(0);

  // ---- 応答制御（scratch 実証済みパターン） ----
  const responseActiveRef = useRef(false);
  const pendingResponseRef = useRef(false);
  const responseTickRef = useRef(0);
  const pendingItemsRef = useRef<unknown[]>([]);
  const lastDcEventAtRef = useRef(0);
  const guardianTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cooldownUntilRef = useRef(0);
  const lastImageItemIdsRef = useRef<string[]>([]);
  const toolOutputItemsRef = useRef<Array<{ id: string; size: number }>>([]);
  const delegatingRef = useRef(false);
  const danActivityRef = useRef<string[]>([]);

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
    (role: 'user' | 'assistant', content: string) => {
      void fetch(`/api/v1/voicelog/${encodeURIComponent(roomId)}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ role, content: content.slice(0, 7500) }),
      }).catch(() => {});
    },
    [authHeaders, roomId],
  );

  const dcSend = useCallback((obj: unknown) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === 'open') dc.send(JSON.stringify(obj));
  }, []);

  const flushPendingItems = useCallback(() => {
    const items = pendingItemsRef.current.splice(0);
    for (const item of items) dcSend(item);
  }, [dcSend]);

  const injectItem = useCallback(
    (item: unknown) => {
      if (responseActiveRef.current) pendingItemsRef.current.push(item);
      else dcSend(item);
    },
    [dcSend],
  );

  const scheduleResponse = useCallback(() => {
    if (responseActiveRef.current || performance.now() < cooldownUntilRef.current) {
      pendingResponseRef.current = true;
      return;
    }
    flushPendingItems();
    responseActiveRef.current = true;
    dcSend({ type: 'response.create' });
    const tick = responseTickRef.current;
    setTimeout(() => {
      if (responseTickRef.current !== tick) return;
      if (!dcRef.current || dcRef.current.readyState !== 'open') return;
      responseActiveRef.current = true;
      dcSend({ type: 'response.create' });
    }, 6000);
  }, [dcSend, flushPendingItems]);

  const injectSystemAndRespond = useCallback(
    (text: string) => {
      injectItem({
        type: 'conversation.item.create',
        item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] },
      });
      scheduleResponse();
    },
    [injectItem, scheduleResponse],
  );

  /** look_at_screen 用の画面共有キャプチャ（初回のみ許可ダイアログ） */
  const captureScreenshot = useCallback(async (): Promise<string | null> => {
    let stream = displayStreamRef.current;
    if (!stream || !stream.active) {
      const constraints: MediaStreamConstraints & { video: Record<string, unknown> } = {
        video: { preferCurrentTab: false },
        audio: false,
      };
      stream = await navigator.mediaDevices.getDisplayMedia(constraints);
      displayStreamRef.current = stream;
    }
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await new Promise((r) => setTimeout(r, 200));
    const scale = Math.min(1, 1280 / (video.videoWidth || 1280));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round((video.videoWidth || 1280) * scale);
    canvas.height = Math.round((video.videoHeight || 720) * scale);
    canvas.getContext('2d')!.drawImage(video, 0, 0, canvas.width, canvas.height);
    video.pause();
    video.srcObject = null;
    return canvas.toDataURL('image/jpeg', 0.7);
  }, []);

  const executeTool = useCallback(
    async (name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (name === 'delegate_to_dan') {
        const task = String(args.task ?? '').trim();
        if (!task) return { error: 'task が空です' };
        const ws = delegateWsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          return { error: '実行エンジン（ダン）に接続できていません。' };
        }
        if (delegatingRef.current) {
          return { error: '別の委譲作業が進行中です。完了を待ってから次を頼んでください。' };
        }
        ws.send(JSON.stringify({ type: 'delegate', task, room_id: roomId }));
        delegatingRef.current = true;
        danActivityRef.current = [];
        pushLog('📋', `委譲: ${task.slice(0, 200)}`);
        return { status: 'delegated', note: '開発エージェントに渡しました。数分かかることがあります。完了したら通知が届きます。' };
      }

      if (name === 'check_dan_status') {
        return {
          running: delegatingRef.current,
          recent_activity: danActivityRef.current.slice(-6),
          note: delegatingRef.current ? 'ダンは作業中です。完了すると通知が届きます。' : '進行中の委譲作業はありません。',
        };
      }

      if (name === 'look_at_screen') {
        try {
          const dataUrl = await captureScreenshot();
          if (!dataUrl) return { error: 'スクリーンショットを取得できませんでした' };
          for (const oldId of lastImageItemIdsRef.current) {
            injectItem({ type: 'conversation.item.delete', item_id: oldId });
          }
          const id = `item_img_${Date.now()}`;
          lastImageItemIdsRef.current = [id];
          injectItem({
            type: 'conversation.item.create',
            item: { id, type: 'message', role: 'user', content: [{ type: 'input_image', image_url: dataUrl }] },
          });
          return { ok: true, note: 'ユーザーの画面のスクリーンショットを会話に添付しました。' };
        } catch (e) {
          return { error: `画面キャプチャに失敗（共有が許可されなかった可能性）: ${String(e).slice(0, 120)}` };
        }
      }

      return { error: `未知のツール: ${name}` };
    },
    [captureScreenshot, injectItem, pushLog, roomId],
  );

  const disconnect = useCallback(() => {
    genRef.current += 1;
    for (const ref of [dcRef, pcRef] as const) {
      try {
        ref.current?.close();
      } catch {
        /* noop */
      }
      ref.current = null;
    }
    try {
      delegateWsRef.current?.close();
    } catch {
      /* noop */
    }
    delegateWsRef.current = null;
    if (guardianTimerRef.current) {
      clearInterval(guardianTimerRef.current);
      guardianTimerRef.current = null;
    }
    pendingItemsRef.current = [];
    displayStreamRef.current?.getTracks().forEach((t) => t.stop());
    displayStreamRef.current = null;
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
    setSpeaking(false);
    setCurrentActivity(null);
    setStatus((s) => (s === 'error' ? 'error' : 'idle'));
  }, []);

  const connect = useCallback(async () => {
    disconnect();
    genRef.current += 1;
    const myGen = genRef.current;
    const live = () => genRef.current === myGen;

    setStatus('connecting');
    setError(null);
    setActivity([]);
    responseActiveRef.current = false;
    pendingResponseRef.current = false;
    pendingItemsRef.current = [];
    lastImageItemIdsRef.current = [];
    toolOutputItemsRef.current = [];
    cooldownUntilRef.current = 0;
    delegatingRef.current = false;

    const handledCalls = new Set<string>();

    const handleFunctionCall = async (item: { name?: string; call_id?: string; arguments?: string }) => {
      if (!item.name || !item.call_id || handledCalls.has(item.call_id)) return;
      handledCalls.add(item.call_id);
      let args: Record<string, unknown> = {};
      try {
        args = JSON.parse(item.arguments || '{}');
      } catch {
        /* noop */
      }
      setCurrentActivity(TOOL_LABELS[item.name] || item.name);
      pushActivity(`🔧 ${TOOL_LABELS[item.name] || item.name}`);
      pushLog('🔧', `${item.name}(${JSON.stringify(args).slice(0, 140)})`);
      const result = await executeTool(item.name, args);
      setCurrentActivity(null);
      if ('error' in result) pushLog('⚠', `ツール失敗: ${String(result.error).slice(0, 150)}`);
      const output = JSON.stringify(result);
      const outputItemId = `item_out_${Date.now()}_${Math.floor(Math.random() * 1e4)}`;
      dcSend({
        type: 'conversation.item.create',
        item: { id: outputItemId, type: 'function_call_output', call_id: item.call_id, output },
      });
      toolOutputItemsRef.current.push({ id: outputItemId, size: output.length });
      const items = toolOutputItemsRef.current;
      let total = items.reduce((a, x) => a + x.size, 0);
      while (items.length > 3 && (total > 24_000 || items.length > 8)) {
        const oldest = items.shift()!;
        total -= oldest.size;
        injectItem({ type: 'conversation.item.delete', item_id: oldest.id });
      }
      scheduleResponse();
    };

    const handleRtEvent = (msg: RtEvent) => {
      switch (msg.type) {
        case 'response.created':
          responseActiveRef.current = true;
          responseTickRef.current += 1;
          break;
        case 'output_audio_buffer.started':
          setSpeaking(true);
          break;
        case 'output_audio_buffer.stopped':
        case 'output_audio_buffer.cleared':
          setSpeaking(false);
          break;
        case 'conversation.item.input_audio_transcription.completed': {
          const t = ((msg.transcript as string) || '').trim();
          if (t) {
            saveTranscript('user', t);
            pushLog('🎤', t);
          }
          break;
        }
        case 'response.output_audio_transcript.done':
        case 'response.audio_transcript.done': {
          const t = ((msg.transcript as string) || '').trim();
          if (t) {
            saveTranscript('assistant', t);
            pushLog('🗣', t);
          }
          break;
        }
        case 'response.output_item.done': {
          const item = msg.item as { type?: string; name?: string; call_id?: string; arguments?: string };
          if (item?.type === 'function_call') void handleFunctionCall(item);
          break;
        }
        case 'response.done': {
          setSpeaking(false);
          responseActiveRef.current = false;
          const response =
            (msg.response as { output?: unknown[]; status?: string; status_details?: unknown; usage?: Record<string, unknown> }) || {};
          if (response.status && response.status !== 'completed') {
            const details = JSON.stringify(response.status_details ?? {});
            pushLog('⚠', `response ${response.status}: ${details.slice(0, 180)}`);
            if (details.includes('rate_limit_exceeded')) {
              const m = details.match(/try again in ([\d.]+)s/);
              const waitMs = m ? Math.ceil(parseFloat(m[1]) * 1000) + 800 : 8000;
              cooldownUntilRef.current = performance.now() + waitMs;
              setTimeout(() => {
                if (dcRef.current?.readyState === 'open') scheduleResponse();
              }, waitMs + 200);
            }
          }
          const u = response.usage as
            | {
                input_token_details?: { text_tokens?: number; audio_tokens?: number; image_tokens?: number; cached_tokens?: number };
                output_token_details?: { text_tokens?: number; audio_tokens?: number };
              }
            | undefined;
          if (u) {
            const i = u.input_token_details || {};
            const o = u.output_token_details || {};
            const cached = i.cached_tokens || 0;
            const freshText = Math.max(0, (i.text_tokens || 0) + (i.image_tokens || 0) - cached);
            const usd =
              (freshText * 4 + cached * 0.4 + (i.audio_tokens || 0) * 32 + (o.text_tokens || 0) * 16 + (o.audio_tokens || 0) * 64) /
              1_000_000;
            if (usd > 0) setSessionCost((c) => c + usd);
          }
          for (const raw of response.output || []) {
            const item = raw as { type?: string; name?: string; call_id?: string; arguments?: string };
            if (item.type === 'function_call') void handleFunctionCall(item);
          }
          if (pendingResponseRef.current) {
            pendingResponseRef.current = false;
            scheduleResponse();
          }
          break;
        }
      }
    };

    const danActivity = (line: string) => {
      danActivityRef.current = [...danActivityRef.current, line].slice(-6);
    };
    const handleDelegateMsg = (data: RtEvent) => {
      switch (data.type) {
        case 'delegate_started':
          delegatingRef.current = true;
          setCurrentActivity('ダンが作業中（委譲）');
          pushActivity('📋 ダンに作業を委譲');
          break;
        case 'reasoning':
          danActivity(`思考: ${String(data.text || '').slice(0, 60)}`);
          break;
        case 'tool_use':
          danActivity(`ツール実行: ${String(data.name || 'tool')}`);
          pushActivity(`⚙ ダン: ${String(data.name || 'tool')}`);
          break;
        case 'text':
          danActivity(`発言: ${String(data.text || '').slice(0, 60)}`);
          break;
        case 'result': {
          delegatingRef.current = false;
          setCurrentActivity(null);
          pushActivity('✅ ダンの作業完了');
          pushLog('✅', 'ダンの作業完了');
          const text = String(data.text || '');
          // 注: 結果の room 保存はしない。ダン本体の回答は委譲パイプラインが
          // 部屋へ直接投稿する（StyleUp実測 2026-08-23）ため、こちらで保存すると三重になる。
          injectSystemAndRespond(
            `[システム通知] 委譲した作業が完了しました。完了報告:\n${text.slice(0, 4000)}\n\nユーザーに要点を短く報告してください。`,
          );
          break;
        }
        case 'error':
          delegatingRef.current = false;
          setCurrentActivity(null);
          pushLog('⚠', `委譲エラー: ${String(data.message || '').slice(0, 150)}`);
          injectSystemAndRespond(
            `[システム通知] 委譲作業でエラーが発生しました: ${String(data.message || '').slice(0, 200)}。ユーザーに伝えてください。`,
          );
          break;
      }
    };

    const openDelegateWs = (token: string) =>
      new Promise<WebSocket>((resolve, reject) => {
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${proto}//${window.location.host}/ws/realtime-delegate`);
        const to = setTimeout(() => {
          try {
            ws.close();
          } catch {
            /* noop */
          }
          reject(new Error('timeout'));
        }, 12000);
        ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }));
        ws.onmessage = (e) => {
          let data: RtEvent;
          try {
            data = JSON.parse(e.data);
          } catch {
            return;
          }
          if (data.type === 'auth_success') {
            clearTimeout(to);
            resolve(ws);
            return;
          }
          handleDelegateMsg(data);
        };
        ws.onerror = () => {
          clearTimeout(to);
          reject(new Error('ws error'));
        };
      });

    let pc: RTCPeerConnection | null = null;
    let mic: MediaStream | null = null;
    let audioEl: HTMLAudioElement | null = null;
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

      const sessRes = await fetch('/api/v1/voicelog/session', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ chat_title: chatTitle ?? null }),
      });
      if (!live()) return;
      const sess = await sessRes.json();
      if (!sessRes.ok || !sess.value) throw new Error(sess.detail || sess.error || `セッション発行に失敗 (${sessRes.status})`);

      try {
        delegateWsRef.current = await openDelegateWs(token);
      } catch {
        // 委譲不可でも会話は可能
      }
      if (!live()) return;

      pc = new RTCPeerConnection();
      audioEl = document.createElement('audio');
      audioEl.autoplay = true;
      audioEl.style.display = 'none';
      document.body.appendChild(audioEl);

      const audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;

      pc.ontrack = (e) => {
        if (audioEl) audioEl.srcObject = e.streams[0];
        // AI音声の音量 → オーブの雲の揺らめき
        try {
          const src = audioCtx.createMediaStreamSource(e.streams[0]);
          const analyser = audioCtx.createAnalyser();
          analyser.fftSize = 1024;
          src.connect(analyser);
          aiAnalyserRef.current = analyser;
        } catch {
          /* noop */
        }
      };

      try {
        mic = await navigator.mediaDevices.getUserMedia({ audio: true });
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
      dc.onmessage = (e) => {
        lastDcEventAtRef.current = performance.now();
        try {
          handleRtEvent(JSON.parse(e.data));
        } catch {
          /* noop */
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      if (!live()) {
        cleanupLocal();
        return;
      }
      const sdpRes = await fetch(`${OPENAI_CALLS_URL}?model=${encodeURIComponent(sess.model)}`, {
        method: 'POST',
        body: offer.sdp ?? '',
        headers: { Authorization: `Bearer ${sess.value}`, 'Content-Type': 'application/sdp' },
      });
      if (!live()) {
        cleanupLocal();
        return;
      }
      if (!sdpRes.ok) throw new Error(`接続に失敗 (${sdpRes.status})`);
      await pc.setRemoteDescription({ type: 'answer', sdp: await sdpRes.text() });
      if (!live()) {
        cleanupLocal();
        return;
      }

      pcRef.current = pc;
      dcRef.current = dc;
      micRef.current = mic;
      audioRef.current = audioEl;
      lastDcEventAtRef.current = performance.now();
      setStatus('connected');

      if (guardianTimerRef.current) clearInterval(guardianTimerRef.current);
      guardianTimerRef.current = setInterval(() => {
        if (!dcRef.current || dcRef.current.readyState !== 'open') return;
        if (performance.now() < cooldownUntilRef.current) return;
        if (!responseActiveRef.current && (pendingResponseRef.current || pendingItemsRef.current.length > 0)) {
          pendingResponseRef.current = false;
          scheduleResponse();
          return;
        }
        if (responseActiveRef.current && performance.now() - lastDcEventAtRef.current > 20_000) {
          responseActiveRef.current = false;
          scheduleResponse();
        }
      }, 4000);
    } catch (e) {
      cleanupLocal();
      if (!live()) return;
      setError(e instanceof Error ? e.message : '接続に失敗しました');
      setStatus('error');
    }
  }, [authHeaders, chatTitle, dcSend, disconnect, executeTool, injectItem, injectSystemAndRespond, saveTranscript, scheduleResponse]);

  useEffect(() => {
    void connect();
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col items-center gap-3 p-4">
      <div className="flex w-full items-center justify-between">
        <span className="text-xs text-muted-foreground">
          音声モード{sessionCost > 0 ? ` ・ $${sessionCost.toFixed(2)}` : ''}
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
