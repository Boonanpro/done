'use client';

/**
 * gpt-realtime-2 音声会話レイヤーの React フック。
 *
 * 構成:
 *   - 音声: ブラウザ ↔ OpenAI を WebRTC 直結（最低レイテンシ）
 *   - 委譲: gpt-realtime-2 が delegate_to_dan を呼ぶと、/ws/realtime-delegate
 *           経由でバックグラウンドの開発エージェント（Claude Code CLI）を起動。
 *           進捗は UI に表示し、完了報告は音声セッションに注入して読み上げさせる。
 *
 * OpenAI API キーはブラウザに出さない。サーバー発行の ephemeral トークン(ek_)を使う。
 *
 * 注意: WebRTC とマイク取得は secure context（HTTPS / localhost）が必須。
 *       http:// の IP アドレス直アクセスでは動かないため connect() 冒頭で弾く。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export type RealtimeStatus = 'idle' | 'connecting' | 'connected' | 'error';

export interface TranscriptTurn {
  role: 'user' | 'assistant';
  text: string;
}

interface UseRealtimeVoiceResult {
  status: RealtimeStatus;
  error: string | null;
  speaking: boolean;
  delegating: boolean;
  transcript: TranscriptTurn[];
  progress: string[];
  connect: () => Promise<void>;
  disconnect: () => void;
}

const OPENAI_CALLS_URL = 'https://api.openai.com/v1/realtime/calls';
const ROOM_KEY = 'done-voice-room';

type RtEvent = { type: string; [key: string]: unknown };

function getWsBase(): string {
  if (typeof window === 'undefined') return 'ws://localhost:9000';
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

/** crypto.randomUUID は secure context 限定。非対応環境向けに fallback する。 */
function randomId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
  } catch {
    /* noop */
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** CLI セッションのキー。ブラウザごとに固定して会話の継続（--resume）を効かせる。 */
function getRoomId(): string {
  try {
    let id = localStorage.getItem(ROOM_KEY);
    if (!id) {
      id = `voice-${randomId()}`;
      localStorage.setItem(ROOM_KEY, id);
    }
    return id;
  } catch {
    // localStorage 不可（プライベートモード等）でも会話は成立させる
    return `voice-${randomId()}`;
  }
}

export interface UseRealtimeVoiceOptions {
  /** 委譲タスクを紐づける CLI セッションID。指定があれば localStorage の voice-room より優先。
   *  チャット内から起動した場合に project.room_id を渡し、delegate がそのチャットに書き戻るようにする。 */
  roomId?: string;
  /** 起動元チャットのタイトル。OpenAI realtime session の instructions に注入し、
   *  「今どの会話の文脈にいるか」を AI に伝える。 */
  chatTitle?: string;
}

export function useRealtimeVoice(options?: UseRealtimeVoiceOptions): UseRealtimeVoiceResult {
  const [status, setStatus] = useState<RealtimeStatus>('idle');
  // 最新の options を ref で保持し、connect() がボタン押下時点の値を読めるようにする
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [delegating, setDelegating] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptTurn[]>([]);
  const [progress, setProgress] = useState<string[]>([]);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const delegateWsRef = useRef<WebSocket | null>(null);
  const roomIdRef = useRef<string>('');
  // connect() の世代番号。disconnect / 再接続のたびに +1 し、進行中だった
  // connect() は自分の世代が古くなったら（中断されたら）静かに後始末して抜ける。
  const genRef = useRef(0);

  const disconnect = useCallback(() => {
    genRef.current += 1; // 進行中の connect() を無効化する
    if (dcRef.current) {
      try { dcRef.current.close(); } catch { /* noop */ }
      dcRef.current = null;
    }
    if (pcRef.current) {
      try { pcRef.current.close(); } catch { /* noop */ }
      pcRef.current = null;
    }
    if (micRef.current) {
      micRef.current.getTracks().forEach((t) => t.stop());
      micRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.srcObject = null;
      audioRef.current.remove();
      audioRef.current = null;
    }
    if (delegateWsRef.current) {
      try { delegateWsRef.current.close(); } catch { /* noop */ }
      delegateWsRef.current = null;
    }
    setSpeaking(false);
    setDelegating(false);
    setStatus((s) => (s === 'error' ? 'error' : 'idle'));
  }, []);

  const connect = useCallback(async () => {
    // 直前の接続が残っていれば確実に片付けてから始める
    disconnect();
    genRef.current += 1;
    const myGen = genRef.current;
    /** この connect() がまだ有効か（disconnect / 再接続で中断されていないか）。 */
    const live = () => genRef.current === myGen;

    setStatus('connecting');
    setError(null);
    setTranscript([]);
    setProgress([]);

    // この connect() が確保したリソース。接続成立までは ref に入れず local 管理し、
    // 中断時は自分のぶんだけ片付ける（新しい接続のリソースを壊さないため）。
    let localPc: RTCPeerConnection | null = null;
    let localDc: RTCDataChannel | null = null;
    let localMic: MediaStream | null = null;
    let localAudio: HTMLAudioElement | null = null;
    let localWs: WebSocket | null = null;

    const cleanupLocal = () => {
      try { localDc?.close(); } catch { /* noop */ }
      try { localPc?.close(); } catch { /* noop */ }
      localMic?.getTracks().forEach((t) => t.stop());
      if (localAudio) {
        localAudio.srcObject = null;
        localAudio.remove();
      }
      try { localWs?.close(); } catch { /* noop */ }
    };

    const pushProgress = (line: string) =>
      setProgress((p) => [...p, line].slice(-60));

    const dcSend = (obj: unknown) => {
      if (localDc && localDc.readyState === 'open') localDc.send(JSON.stringify(obj));
    };

    /** gpt-realtime-2 にテキストを注入し、音声で応答させる。 */
    const injectAndRespond = (text: string) => {
      dcSend({
        type: 'conversation.item.create',
        item: {
          type: 'message',
          role: 'user',
          content: [{ type: 'input_text', text }],
        },
      });
      dcSend({ type: 'response.create' });
    };

    const handledCalls = new Set<string>();

    /** delegate_to_dan 呼び出しを実行エンジンに渡す（非同期ハンドオフ）。 */
    const handleDelegate = (callId: string, argsJson: string) => {
      let task = '';
      try {
        task = (JSON.parse(argsJson || '{}').task as string) || '';
      } catch { /* noop */ }
      if (!task) return;

      setDelegating(true);
      pushProgress(`📋 委譲: ${task}`);

      if (localWs && localWs.readyState === WebSocket.OPEN) {
        localWs.send(JSON.stringify({ type: 'delegate', task, room_id: roomIdRef.current }));
      } else {
        setDelegating(false);
        pushProgress('⚠ 実行エンジンに接続できていません（作業は委譲できません）');
      }

      // 関数呼び出しには即時応答する。実作業の完了は後で別ターンとして報告する。
      dcSend({
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: callId,
          output: JSON.stringify({
            status: '開発エージェントに作業を渡しました。完了したら報告が届きます。',
          }),
        },
      });
      dcSend({ type: 'response.create' });
    };

    /** gpt-realtime-2 からの data channel イベント。 */
    const handleRtEvent = (msg: RtEvent) => {
      switch (msg.type) {
        case 'output_audio_buffer.started':
          setSpeaking(true);
          break;
        case 'output_audio_buffer.stopped':
        case 'output_audio_buffer.cleared':
          setSpeaking(false);
          break;
        case 'conversation.item.input_audio_transcription.completed': {
          const t = ((msg.transcript as string) || '').trim();
          if (t) setTranscript((arr) => [...arr, { role: 'user', text: t }]);
          break;
        }
        case 'response.output_audio_transcript.done':
        case 'response.audio_transcript.done': {
          const t = ((msg.transcript as string) || '').trim();
          if (t) setTranscript((arr) => [...arr, { role: 'assistant', text: t }]);
          break;
        }
        case 'response.done': {
          setSpeaking(false);
          const response = (msg.response as { output?: unknown[] }) || {};
          for (const item of response.output || []) {
            const it = item as {
              type?: string;
              name?: string;
              call_id?: string;
              arguments?: string;
            };
            if (
              it.type === 'function_call' &&
              it.name === 'delegate_to_dan' &&
              it.call_id &&
              !handledCalls.has(it.call_id)
            ) {
              handledCalls.add(it.call_id);
              handleDelegate(it.call_id, it.arguments || '{}');
            }
          }
          break;
        }
        case 'error':
          console.warn('[realtime] error event', msg);
          break;
      }
    };

    /** /ws/realtime-delegate からの進捗イベント。 */
    const handleDelegateMsg = (data: RtEvent) => {
      switch (data.type) {
        case 'reasoning':
          pushProgress(`… ${String(data.text || '').slice(0, 200)}`);
          break;
        case 'tool_use':
          pushProgress(`🔧 ${String(data.name || 'tool')}`);
          break;
        case 'text':
          pushProgress(String(data.text || '').slice(0, 200));
          break;
        case 'result': {
          setDelegating(false);
          pushProgress('✅ 作業完了');
          injectAndRespond(
            `[開発エージェントからの作業完了報告]\n${String(data.text || '')}\n\n` +
              'この結果を、ユーザーに音声で簡潔に報告してください。',
          );
          break;
        }
        case 'error':
          setDelegating(false);
          pushProgress(`⚠ エラー: ${String(data.message || '')}`);
          injectAndRespond(
            `[開発エージェントでエラーが発生]\n${String(data.message || '')}\n\n` +
              'この旨をユーザーに音声で簡潔に伝えてください。',
          );
          break;
        case 'busy':
          pushProgress('⚠ 別の作業が進行中です');
          break;
      }
    };

    /** 実行エンジンへの WebSocket を確立し、認証完了したら resolve する。 */
    const openDelegateWs = (token: string) =>
      new Promise<WebSocket>((resolve, reject) => {
        let ws: WebSocket;
        try {
          ws = new WebSocket(`${getWsBase()}/ws/realtime-delegate`);
        } catch (e) {
          reject(e instanceof Error ? e : new Error('WebSocket を作成できませんでした'));
          return;
        }
        let settled = false;
        const to = setTimeout(() => {
          if (settled) return;
          settled = true;
          try { ws.close(); } catch { /* noop */ }
          reject(new Error('実行エンジンへの接続がタイムアウトしました'));
        }, 12000);
        const fail = (msg: string) => {
          if (settled) return;
          settled = true;
          clearTimeout(to);
          try { ws.close(); } catch { /* noop */ }
          reject(new Error(msg));
        };
        ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }));
        ws.onmessage = (e) => {
          let data: RtEvent;
          try { data = JSON.parse(e.data); } catch { return; }
          if (!settled) {
            if (data.type === 'auth_success') {
              settled = true;
              clearTimeout(to);
              resolve(ws);
            } else if (data.type === 'error') {
              fail(String(data.message || '認証に失敗しました'));
            }
            return;
          }
          handleDelegateMsg(data);
        };
        ws.onerror = () => fail('実行エンジンへの接続に失敗しました');
        ws.onclose = () => fail('実行エンジンへの接続が閉じられました');
      });

    try {
      // 0) WebRTC とマイク取得は secure context (HTTPS / localhost) 必須。
      //    http:// の IP アドレス直アクセスでは crypto / mediaDevices が存在せず
      //    動かないので、ここで明確なメッセージを出して弾く（無言で固まらせない）。
      if (typeof window !== 'undefined' && !window.isSecureContext) {
        throw new Error(
          '音声機能には安全な接続（HTTPS）が必要です。' +
            'このPCで使うなら http://localhost:3000/voice を、' +
            'スマホからなら https:// で始まる公開URLを開いてください。' +
            '（http:// のIPアドレス直打ちではブラウザがマイクを許可しません）',
        );
      }
      if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
        throw new Error(
          'このブラウザ／接続ではマイクを利用できません。' +
            '最新の Chrome か Safari で、HTTPS または localhost から開いてください。',
        );
      }

      // 外部から渡された roomId（チャットの project.room_id 等）を優先。
      // 未指定なら従来通り localStorage の voice-room（スタンドアロン会話）に戻す。
      roomIdRef.current = optionsRef.current?.roomId || getRoomId();

      const token = localStorage.getItem('done-token') || '';

      // 1) ephemeral トークンをサーバーから取得（API キーはブラウザに出さない）。
      //    起動元チャットのタイトルがあれば送り、サーバー側で OpenAI セッションの
      //    instructions に注入させる（音声AIが何の文脈で話しているか分かるように）。
      const sessRes = await fetch('/api/v1/realtime/session', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ chat_title: optionsRef.current?.chatTitle ?? null }),
      });
      if (!live()) { cleanupLocal(); return; }
      if (!sessRes.ok) {
        throw new Error(`セッション発行に失敗 (${sessRes.status}): ${await sessRes.text()}`);
      }
      const session = await sessRes.json();
      if (!live()) { cleanupLocal(); return; }
      const ephemeralKey: string = session.value;
      const model: string = session.model;
      if (!ephemeralKey) {
        throw new Error('セッショントークンが空でした（サーバー側の OpenAI 設定を確認してください）');
      }

      // 2) 実行エンジン(delegate)WS。失敗しても音声会話自体は続けられるよう非致命に扱う。
      try {
        localWs = await openDelegateWs(token);
      } catch (wsErr) {
        console.warn('[realtime] delegate WS unavailable:', wsErr);
        pushProgress('⚠ 実行エンジンに接続できませんでした（音声会話は可能・作業の委譲は不可）');
      }
      if (!live()) { cleanupLocal(); return; }

      // 3) WebRTC で gpt-realtime-2 に直結
      const pc = new RTCPeerConnection();
      localPc = pc;

      const audioEl = document.createElement('audio');
      audioEl.autoplay = true;
      audioEl.style.display = 'none';
      document.body.appendChild(audioEl);
      localAudio = audioEl;
      pc.ontrack = (e) => {
        audioEl.srcObject = e.streams[0];
      };

      let mic: MediaStream;
      try {
        mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        throw new Error(
          'マイクの使用が許可されませんでした。' +
            'ブラウザのアドレスバー左のアイコンからマイクを「許可」にして、もう一度お試しください。',
        );
      }
      if (!live()) {
        mic.getTracks().forEach((t) => t.stop());
        cleanupLocal();
        return;
      }
      localMic = mic;
      for (const track of mic.getAudioTracks()) pc.addTrack(track, mic);

      const dc = pc.createDataChannel('oai-events');
      localDc = dc;
      dc.onopen = () => {
        // 入力音声の transcription / noise_reduction / 言語ヒントは
        // サーバー側 build_session_config() で既にセット済みなので、
        // ここで session.update する必要はない（旧 whisper-1 上書きを廃止）。
      };
      dc.onmessage = (e) => {
        let parsed: RtEvent;
        try { parsed = JSON.parse(e.data); } catch { return; }
        handleRtEvent(parsed);
      };

      const offer = await pc.createOffer();
      if (!live()) { cleanupLocal(); return; }
      await pc.setLocalDescription(offer);
      if (!live()) { cleanupLocal(); return; }

      const sdpRes = await fetch(`${OPENAI_CALLS_URL}?model=${encodeURIComponent(model)}`, {
        method: 'POST',
        body: offer.sdp ?? '',
        headers: {
          Authorization: `Bearer ${ephemeralKey}`,
          'Content-Type': 'application/sdp',
        },
      });
      if (!live()) { cleanupLocal(); return; }
      if (!sdpRes.ok) {
        throw new Error(`WebRTC接続に失敗 (${sdpRes.status}): ${await sdpRes.text()}`);
      }
      const answerSdp = await sdpRes.text();
      if (!live()) { cleanupLocal(); return; }
      await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
      if (!live()) { cleanupLocal(); return; }

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed') {
          setError('音声接続が切断されました');
          setStatus('error');
        }
      };

      // 4) 接続成立 — ここで初めて ref に移し、disconnect() の片付け対象にする
      pcRef.current = localPc;
      dcRef.current = localDc;
      micRef.current = localMic;
      audioRef.current = localAudio;
      delegateWsRef.current = localWs;
      setStatus('connected');
    } catch (e) {
      cleanupLocal();
      if (!live()) return; // disconnect による中断 — エラーは表示しない
      setError(e instanceof Error ? e.message : '接続に失敗しました');
      setStatus('error');
    }
  }, [disconnect]);

  // アンマウント時に確実に後始末する
  useEffect(() => () => disconnect(), [disconnect]);

  return { status, error, speaking, delegating, transcript, progress, connect, disconnect };
}
