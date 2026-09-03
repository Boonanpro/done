'use client';

/**
 * /scratch/realtime-voice — Phase 0 実験ページ。
 *
 * 検証すること:
 *   1. gpt-realtime-2.1 に編集ツールを直接持たせて
 *      「喋る → 数秒で目の前のLPが変わる → barge-in で軌道修正」が成立するか
 *   2. ボタン方式（set_text / set_style）と生JS直書き（run_js）の成功率・速度比較
 *   3. reasoning effort（minimal〜xhigh）ごとの応答遅延と賢さ
 *   4. プリアンブル（実行前の意図宣言）の制御が効くか
 *
 * すべてこのページ内で完結する（ダンコア・サンドボックスには触らない）。
 * トークン発行は同ディレクトリの api/session ルート（ローカル開発専用）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  DEFAULT_CONFIG,
  buildInstructions,
  buildTools,
  type ExperimentConfig,
  type PreambleMode,
  type RealtimeModel,
  type ReasoningEffort,
  type ToolLane,
} from './session-config';

const OPENAI_CALLS_URL = 'https://api.openai.com/v1/realtime/calls';

type Status = 'idle' | 'connecting' | 'connected' | 'error';

interface LogEntry {
  time: string;
  tag: '🎤' | '🗣' | '🔧' | '⚙' | '⚠';
  text: string;
}

type RtEvent = { type: string; [key: string]: unknown };

function now(): string {
  return new Date().toLocaleTimeString('ja-JP', { hour12: false });
}

/** run_js の実行結果を安全に文字列化する（循環参照・DOM要素対策）。 */
function safeStringify(value: unknown): string {
  try {
    if (value === undefined) return 'undefined';
    if (value instanceof Element) return `<${value.tagName.toLowerCase()}>`;
    return JSON.stringify(value)?.slice(0, 500) ?? String(value);
  } catch {
    return String(value).slice(0, 500);
  }
}

export default function RealtimeVoiceExperiment() {
  const [config, setConfig] = useState<ExperimentConfig>(DEFAULT_CONFIG);
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [log, setLog] = useState<LogEntry[]>([]);
  /** ログ永続化のセッションID（logs/realtime-voice/<id>.jsonl に追記される）。 */
  const [logSession] = useState(() => `practice-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}`);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const genRef = useRef(0);
  /** 直近の発話終了時刻（performance.now）。ツール実行までの遅延計測に使う。 */
  const speechStoppedAtRef = useRef<number | null>(null);
  const configRef = useRef(config);
  configRef.current = config;

  const logBufferRef = useRef<LogEntry[]>([]);
  const pushLog = useCallback((tag: LogEntry['tag'], text: string) => {
    const entry = { time: now(), tag, text };
    logBufferRef.current.push(entry);
    setLog((l) => [...l, entry].slice(-200));
  }, []);

  // ログをサーバーへ永続化（開発CLIが後から logs/realtime-voice/<id>.jsonl を読める）
  useEffect(() => {
    const flush = (useBeacon: boolean) => {
      const batch = logBufferRef.current.splice(0);
      if (!batch.length) return;
      const payload = JSON.stringify({ session_id: logSession, entries: batch });
      if (useBeacon && navigator.sendBeacon) {
        navigator.sendBeacon('/scratch/realtime-voice/api/log', new Blob([payload], { type: 'application/json' }));
      } else {
        void fetch('/scratch/realtime-voice/api/log', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payload,
        }).catch(() => {});
      }
    };
    const t = setInterval(() => flush(false), 3000);
    const onHide = () => flush(true);
    window.addEventListener('pagehide', onHide);
    return () => {
      clearInterval(t);
      window.removeEventListener('pagehide', onHide);
      flush(true);
    };
  }, [logSession]);

  /** 発話終了からの経過秒を「(+1.23s)」形式で返す。計測起点がなければ空文字。 */
  const sinceSpeech = useCallback((): string => {
    const t0 = speechStoppedAtRef.current;
    if (t0 === null) return '';
    return ` (+${((performance.now() - t0) / 1000).toFixed(2)}s)`;
  }, []);

  // ------------------------------------------------------------ tools

  const lpElements = useCallback((): HTMLElement[] => {
    const root = document.getElementById('rt-lp');
    if (!root) return [];
    return Array.from(root.querySelectorAll<HTMLElement>('[data-rt-id]'));
  }, []);

  const findEl = useCallback(
    (id: string): HTMLElement | null =>
      lpElements().find((el) => el.dataset.rtId === id) ?? null,
    [lpElements],
  );

  const executeTool = useCallback(
    (name: string, args: Record<string, unknown>): Record<string, unknown> => {
      if (name === 'get_page_state') {
        return {
          elements: lpElements().map((el) => ({
            id: el.dataset.rtId,
            tag: el.tagName.toLowerCase(),
            text: (el.textContent ?? '').trim().slice(0, 80),
            style: el.getAttribute('style') ?? '',
          })),
        };
      }
      if (name === 'set_text') {
        const el = findEl(String(args.id ?? ''));
        if (!el) return { error: `id "${args.id}" の要素が見つかりません` };
        el.textContent = String(args.text ?? '');
        return { ok: true, id: args.id, text: args.text };
      }
      if (name === 'set_style') {
        const el = findEl(String(args.id ?? ''));
        if (!el) return { error: `id "${args.id}" の要素が見つかりません` };
        const styles = (args.styles ?? {}) as Record<string, string>;
        for (const [k, v] of Object.entries(styles)) {
          // el.style は camelCase キーの代入を受け付ける。無効キーは無視される。
          (el.style as unknown as Record<string, string>)[k] = v;
        }
        return { ok: true, id: args.id, appliedStyle: el.getAttribute('style') ?? '' };
      }
      if (name === 'run_js') {
        const code = String(args.code ?? '');
        try {
          const fn = new Function(code);
          return { ok: true, result: safeStringify(fn()) };
        } catch (e) {
          return { ok: false, error: String(e).slice(0, 500) };
        }
      }
      return { error: `未知のツール: ${name}` };
    },
    [findEl, lpElements],
  );

  // ------------------------------------------------------ connection

  const dcSend = useCallback((obj: unknown) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === 'open') dc.send(JSON.stringify(obj));
  }, []);

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
    micRef.current?.getTracks().forEach((t) => t.stop());
    micRef.current = null;
    if (audioRef.current) {
      audioRef.current.srcObject = null;
      audioRef.current.remove();
      audioRef.current = null;
    }
    setSpeaking(false);
    setStatus((s) => (s === 'error' ? 'error' : 'idle'));
  }, []);

  const connect = useCallback(async () => {
    disconnect();
    genRef.current += 1;
    const myGen = genRef.current;
    const live = () => genRef.current === myGen;

    setStatus('connecting');
    setError(null);
    speechStoppedAtRef.current = null;

    const handledCalls = new Set<string>();
    // 1つの response に複数の function_call が入ることがある。output は即返すが、
    // response.create は「その response が終わってから1回だけ」送る
    // （途中で送ると conversation_already_has_active_response エラーになる）。
    let needFollowupResponse = false;

    const sendToolOutput = (callId: string, output: unknown) => {
      dcSend({
        type: 'conversation.item.create',
        item: {
          type: 'function_call_output',
          call_id: callId,
          output: JSON.stringify(output),
        },
      });
      needFollowupResponse = true;
    };

    const handleFunctionCall = (item: {
      name?: string;
      call_id?: string;
      arguments?: string;
    }) => {
      if (!item.name || !item.call_id || handledCalls.has(item.call_id)) return;
      handledCalls.add(item.call_id);
      let args: Record<string, unknown> = {};
      try {
        args = JSON.parse(item.arguments || '{}');
      } catch {
        /* noop */
      }
      const argsPreview = JSON.stringify(args).slice(0, 160);
      pushLog('🔧', `${item.name}(${argsPreview})${sinceSpeech()}`);
      const result = executeTool(item.name, args);
      if ('error' in result) pushLog('⚠', `ツール失敗: ${String(result.error)}`);
      sendToolOutput(item.call_id, result);
    };

    const handleRtEvent = (msg: RtEvent) => {
      switch (msg.type) {
        case 'input_audio_buffer.speech_stopped':
          speechStoppedAtRef.current = performance.now();
          break;
        case 'output_audio_buffer.started':
          setSpeaking(true);
          pushLog('⚙', `音声応答開始${sinceSpeech()}`);
          break;
        case 'output_audio_buffer.stopped':
        case 'output_audio_buffer.cleared':
          setSpeaking(false);
          break;
        case 'conversation.item.input_audio_transcription.completed': {
          const t = ((msg.transcript as string) || '').trim();
          if (t) pushLog('🎤', t);
          break;
        }
        case 'response.output_audio_transcript.done':
        case 'response.audio_transcript.done': {
          const t = ((msg.transcript as string) || '').trim();
          if (t) pushLog('🗣', t);
          break;
        }
        // ツール呼び出しは output_item.done（早い）と response.done（取りこぼし保険）の両方で拾う
        case 'response.output_item.done': {
          const item = msg.item as { type?: string; name?: string; call_id?: string; arguments?: string };
          if (item?.type === 'function_call') handleFunctionCall(item);
          break;
        }
        case 'response.done': {
          setSpeaking(false);
          const response = (msg.response as { output?: unknown[] }) || {};
          for (const raw of response.output || []) {
            const item = raw as { type?: string; name?: string; call_id?: string; arguments?: string };
            if (item.type === 'function_call') handleFunctionCall(item);
          }
          if (needFollowupResponse) {
            needFollowupResponse = false;
            dcSend({ type: 'response.create' });
          }
          break;
        }
        case 'error':
          pushLog('⚠', `realtime error: ${JSON.stringify(msg).slice(0, 300)}`);
          break;
      }
    };

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
        throw new Error('HTTPS か localhost で開いてください（マイクが許可されません）');
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('このブラウザではマイクを利用できません');
      }

      const cfg = configRef.current;
      const sessRes = await fetch('/scratch/realtime-voice/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      });
      if (!live()) return;
      const sess = await sessRes.json();
      if (!sessRes.ok || !sess.value) {
        throw new Error(sess.error || `トークン発行に失敗 (${sessRes.status})`);
      }
      pushLog('⚙', `セッション発行 OK: ${cfg.model} / effort=${cfg.effort} / lane=${cfg.lane} / preamble=${cfg.preamble}`);

      pc = new RTCPeerConnection();
      audioEl = document.createElement('audio');
      audioEl.autoplay = true;
      audioEl.style.display = 'none';
      document.body.appendChild(audioEl);
      pc.ontrack = (e) => {
        if (audioEl) audioEl.srcObject = e.streams[0];
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

      const dc = pc.createDataChannel('oai-events');
      dc.onmessage = (e) => {
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

      const sdpRes = await fetch(`${OPENAI_CALLS_URL}?model=${encodeURIComponent(cfg.model)}`, {
        method: 'POST',
        body: offer.sdp ?? '',
        headers: { Authorization: `Bearer ${sess.value}`, 'Content-Type': 'application/sdp' },
      });
      if (!live()) {
        cleanupLocal();
        return;
      }
      if (!sdpRes.ok) {
        throw new Error(`WebRTC 接続失敗 (${sdpRes.status}): ${(await sdpRes.text()).slice(0, 300)}`);
      }
      await pc.setRemoteDescription({ type: 'answer', sdp: await sdpRes.text() });
      if (!live()) {
        cleanupLocal();
        return;
      }

      pc.onconnectionstatechange = () => {
        if (pc?.connectionState === 'failed') {
          setError('音声接続が切断されました');
          setStatus('error');
        }
      };

      pcRef.current = pc;
      dcRef.current = dc;
      micRef.current = mic;
      audioRef.current = audioEl;
      setStatus('connected');
      pushLog('⚙', '接続完了。話しかけてください（例:「見出しをもっと大きくして」）');
    } catch (e) {
      cleanupLocal();
      if (!live()) return;
      setError(e instanceof Error ? e.message : '接続に失敗しました');
      setStatus('error');
    }
  }, [dcSend, disconnect, executeTool, pushLog, sinceSpeech]);

  useEffect(() => () => disconnect(), [disconnect]);

  /** 接続中に lane / preamble / effort を変えたら session.update で反映する。 */
  const updateConfig = useCallback(
    (patch: Partial<ExperimentConfig>) => {
      setConfig((prev) => {
        const next = { ...prev, ...patch };
        if (dcRef.current?.readyState === 'open') {
          if (patch.model && patch.model !== prev.model) {
            pushLog('⚙', 'モデル変更は再接続が必要です（切断して接続し直してください）');
          } else {
            dcSend({
              type: 'session.update',
              session: {
                type: 'realtime',
                instructions: buildInstructions(next.lane, next.preamble),
                tools: buildTools(next.lane),
                reasoning: { effort: next.effort },
              },
            });
            pushLog('⚙', `session.update: effort=${next.effort} / lane=${next.lane} / preamble=${next.preamble}`);
          }
        }
        return next;
      });
    },
    [dcSend, pushLog],
  );

  // ------------------------------------------------------------ UI

  const selStyle: React.CSSProperties = {
    padding: '4px 8px',
    borderRadius: 6,
    border: '1px solid #cbd5e1',
    background: '#fff',
    fontSize: 13,
  };
  const labelStyle: React.CSSProperties = { fontSize: 11, color: '#64748b', display: 'block' };

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#f1f5f9', fontFamily: 'system-ui, sans-serif' }}>
      {/* ---------------- 左: 編集対象のサンプルLP ---------------- */}
      <div style={{ flex: '0 0 460px', overflowY: 'auto', height: '100vh', background: '#fff', boxShadow: '2px 0 12px rgba(0,0,0,.08)' }}>
        <div id="rt-lp">
          <section data-rt-id="hero" style={{ background: '#0f172a', color: '#fff', padding: '56px 32px', textAlign: 'center' }}>
            <p data-rt-id="hero-badge" style={{ display: 'inline-block', background: '#f59e0b', color: '#0f172a', fontSize: 12, fontWeight: 700, padding: '4px 12px', borderRadius: 999, marginBottom: 16 }}>
              新発売
            </p>
            <h1 data-rt-id="hero-title" style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.4, margin: '0 0 12px' }}>
              冬のデスクワークに、足元から静かな暖かさを。
            </h1>
            <p data-rt-id="hero-sub" style={{ fontSize: 14, color: '#94a3b8', lineHeight: 1.8, margin: '0 0 24px' }}>
              ポケットウォームは消費電力わずか45Wのパネル型ヒーター。
              エアコンの1/10の電気代で、膝下だけをムラなく暖めます。
            </p>
            <button data-rt-id="hero-cta" style={{ background: '#f59e0b', color: '#0f172a', border: 'none', fontSize: 15, fontWeight: 700, padding: '12px 36px', borderRadius: 8, cursor: 'pointer' }}>
              今すぐ購入する
            </button>
          </section>

          <section data-rt-id="features" style={{ padding: '40px 32px', background: '#fff' }}>
            <h2 data-rt-id="features-title" style={{ fontSize: 20, fontWeight: 700, textAlign: 'center', margin: '0 0 24px', color: '#0f172a' }}>
              選ばれる3つの理由
            </h2>
            {[
              ['feature-1', '⚡ 電気代1時間約1.4円', '45Wの低消費電力。8時間つけっぱなしでも約11円。'],
              ['feature-2', '🔇 動作音ゼロ', 'ファンレス構造。オンライン会議中も気になりません。'],
              ['feature-3', '🔥 3段階の温度調節', '弱・中・強をワンタッチで切替。過熱防止センサー内蔵。'],
            ].map(([id, title, desc]) => (
              <div key={id} data-rt-id={id} style={{ background: '#f8fafc', borderRadius: 12, padding: '16px 20px', marginBottom: 12 }}>
                <h3 data-rt-id={`${id}-title`} style={{ fontSize: 15, fontWeight: 700, margin: '0 0 6px', color: '#0f172a' }}>
                  {title}
                </h3>
                <p data-rt-id={`${id}-desc`} style={{ fontSize: 13, color: '#475569', lineHeight: 1.7, margin: 0 }}>
                  {desc}
                </p>
              </div>
            ))}
          </section>

          <section data-rt-id="price" style={{ padding: '40px 32px', background: '#fffbeb', textAlign: 'center' }}>
            <h2 data-rt-id="price-title" style={{ fontSize: 18, fontWeight: 700, margin: '0 0 8px', color: '#0f172a' }}>
              期間限定価格
            </h2>
            <p data-rt-id="price-amount" style={{ fontSize: 36, fontWeight: 800, color: '#b45309', margin: '0 0 4px' }}>
              ¥12,800
            </p>
            <p data-rt-id="price-note" style={{ fontSize: 12, color: '#92400e', margin: 0 }}>
              送料無料・30日間返品保証つき
            </p>
          </section>

          <section data-rt-id="footer" style={{ padding: '32px', background: '#0f172a', textAlign: 'center' }}>
            <button data-rt-id="footer-cta" style={{ background: '#fff', color: '#0f172a', border: 'none', fontSize: 14, fontWeight: 700, padding: '12px 32px', borderRadius: 8, cursor: 'pointer' }}>
              公式ストアで見る
            </button>
            <p data-rt-id="footer-note" style={{ fontSize: 11, color: '#64748b', marginTop: 16 }}>
              © 2026 Pocket Warm（サンプルLP・実験用）
            </p>
          </section>
        </div>
      </div>

      {/* ---------------- 右: コントロール + ログ ---------------- */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 20, gap: 12, height: '100vh', boxSizing: 'border-box' }}>
        <div style={{ background: '#fff', borderRadius: 12, padding: 16 }}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div>
              <label style={labelStyle}>モデル</label>
              <select style={selStyle} value={config.model} onChange={(e) => updateConfig({ model: e.target.value as RealtimeModel })}>
                <option value="gpt-realtime-2.1">gpt-realtime-2.1</option>
                <option value="gpt-realtime-2.1-mini">gpt-realtime-2.1-mini</option>
                <option value="gpt-realtime-2">gpt-realtime-2</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>reasoning effort</label>
              <select style={selStyle} value={config.effort} onChange={(e) => updateConfig({ effort: e.target.value as ReasoningEffort })}>
                {['minimal', 'low', 'medium', 'high', 'xhigh'].map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={labelStyle}>ツール車線</label>
              <select style={selStyle} value={config.lane} onChange={(e) => updateConfig({ lane: e.target.value as ToolLane })}>
                <option value="semantic">ボタン方式 (set_text/set_style)</option>
                <option value="raw">生JS直書き (run_js)</option>
                <option value="both">両方渡して選ばせる</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>プリアンブル</label>
              <select style={selStyle} value={config.preamble} onChange={(e) => updateConfig({ preamble: e.target.value as PreambleMode })}>
                <option value="intent">実行前に意図を宣言</option>
                <option value="silent">黙って実行</option>
              </select>
            </div>
            <button
              onClick={status === 'connected' || status === 'connecting' ? disconnect : connect}
              style={{
                padding: '8px 24px',
                borderRadius: 8,
                border: 'none',
                fontWeight: 700,
                fontSize: 14,
                cursor: 'pointer',
                color: '#fff',
                background: status === 'connected' ? '#dc2626' : status === 'connecting' ? '#94a3b8' : '#2563eb',
              }}
            >
              {status === 'connected' ? '切断' : status === 'connecting' ? '接続中…' : '🎙 接続'}
            </button>
            <span style={{ fontSize: 13, color: speaking ? '#16a34a' : '#64748b' }}>
              {status === 'connected' ? (speaking ? '🔊 話しています（割り込みOK）' : '👂 聞いています') : status}
            </span>
          </div>
          {error && <p style={{ color: '#dc2626', fontSize: 13, margin: '10px 0 0' }}>{error}</p>}
        </div>

        <div style={{ flex: 1, background: '#0f172a', borderRadius: 12, padding: 16, overflowY: 'auto', fontFamily: 'ui-monospace, monospace', fontSize: 12.5, lineHeight: 1.8 }}>
          {log.length === 0 && (
            <p style={{ color: '#64748b' }}>
              ログがここに出ます。接続して「見出しをもっと大きくして」「価格を9,800円にして」
              「ヒーローの背景を深緑にして」などと話しかけてください。
              (+X.XXs) は発話終了からの経過秒。
            </p>
          )}
          {log.map((e, i) => (
            <div key={i} style={{ color: e.tag === '🎤' ? '#7dd3fc' : e.tag === '🗣' ? '#fde68a' : e.tag === '🔧' ? '#86efac' : e.tag === '⚠' ? '#fca5a5' : '#94a3b8' }}>
              <span style={{ color: '#475569' }}>{e.time}</span> {e.tag} {e.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
