'use client';

/**
 * /scratch/realtime-voice-lp — Phase 1: 本物のLPを音声で編集する。
 *
 * 仕組み:
 *   - 対象ページ（/artifacts/<slug> か /preview/<slug>）を同一オリジンの iframe で開く
 *   - iframe 内の InspectorRuntime が公開する window.__DAN_INSPECTOR__ を使い、
 *     Inspector 手編集と**完全に同じ適用経路**で DOM に反映する
 *   - 同時に POST /api/v1/inspector-overrides で draft として永続化する
 *     （= リロードで消えない・既存の公開/書き戻しレールにそのまま乗る）
 *   - generate_image は GPT Image 2 で生成→完成したら要素に自動適用→音声AIに通知
 *
 * Phase 0 の練習ページ（/scratch/realtime-voice）と対で、こちらは surface='lp'。
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
} from '../realtime-voice/session-config';

const OPENAI_CALLS_URL = 'https://api.openai.com/v1/realtime/calls';
const DEFAULT_TARGET = '/artifacts/test-edit';

type Status = 'idle' | 'connecting' | 'connected' | 'error';

interface LogEntry {
  time: string;
  tag: '🎤' | '🗣' | '🔧' | '⚙' | '⚠' | '💾' | '🖼' | '📋' | '✅';
  text: string;
}

type RtEvent = { type: string; [key: string]: unknown };

/** iframe 内 InspectorRuntime が公開する API（inspector-runtime.tsx の DanInspectorApi）。 */
interface DanInspectorApi {
  slug: string;
  applyOverride: (key: string, styles: Record<string, string>, attrs: Record<string, unknown>) => void;
  getModel: (key: string) => { v: 2; text: string | null; blockStyle: Record<string, string>; spans: unknown[]; attrs: Record<string, string> } | null;
  reapplyAll: () => void;
}

function now(): string {
  return new Date().toLocaleTimeString('ja-JP', { hour12: false });
}

function parseSlug(targetPath: string): string | null {
  const m = targetPath.match(/^\/(?:artifacts|preview)\/([^/?#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** 実行中インジケータに出す日本語ラベル（音声で実況しない代わりに画面で見せる）。 */
const TOOL_LABELS: Record<string, string> = {
  get_page_state: '状態取得',
  set_text: '文言変更',
  set_style: 'スタイル変更',
  generate_image: '画像生成',
  list_source_files: 'ファイル一覧',
  read_source: 'ソース読込',
  edit_source: 'ソース編集',
  write_source: 'ソース書換',
  look_at_page: '全体確認',
  look_at_section: '細部確認',
  look_at_screen: '画面確認',
  check_contrast: 'コントラスト検査',
  check_dan_status: '進行確認',
  delegate_to_dan: 'ダンへ委譲',
  run_js: 'JS実行',
};

function safeStringify(value: unknown): string {
  try {
    if (value === undefined) return 'undefined';
    return JSON.stringify(value)?.slice(0, 500) ?? String(value);
  } catch {
    return String(value).slice(0, 500);
  }
}

export default function RealtimeVoiceLpPage() {
  const [config, setConfig] = useState<ExperimentConfig>({ ...DEFAULT_CONFIG, surface: 'lp' });
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  /** いま実行中の作業（ツール名の日本語ラベル）。音声実況の代わりの視覚インジケータ。 */
  const [currentActivity, setCurrentActivity] = useState<string | null>(null);
  /** セッション累計の概算コスト（USD）。response.done の usage から集計。 */
  const [sessionCost, setSessionCost] = useState(0);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [targetPath, setTargetPath] = useState(DEFAULT_TARGET);
  const [iframeKey, setIframeKey] = useState(0);
  /** ログ永続化のセッションID（logs/realtime-voice/<id>.jsonl に追記される）。 */
  const [logSession] = useState(() => `lp-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}`);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  /** delegate_to_dan ブリッジ WS（ダンコアの /ws/realtime-delegate）。 */
  const delegateWsRef = useRef<WebSocket | null>(null);
  /** look_at_screen 用の画面共有ストリーム（初回だけ許可ダイアログ、以後使い回す）。 */
  const displayStreamRef = useRef<MediaStream | null>(null);
  /** 委譲作業が進行中か。進行中は直接編集をロックする（二重書き込み事故対策）。 */
  const delegatingRef = useRef(false);
  /** ダンの直近の活動（check_dan_status 用）。 */
  const danActivityRef = useRef<string[]>([]);
  const genRef = useRef(0);
  const speechStoppedAtRef = useRef<number | null>(null);
  // response.create は「進行中の response が無いとき」しか送れない。
  // 進行中なら旗を立てて response.done 時に1回だけ送る。
  const responseActiveRef = useRef(false);
  const pendingResponseRef = useRef(false);
  /** response.created を受けるたび増える。応答ウォッチドッグ（要求したのに生成されない検知）用。 */
  const responseTickRef = useRef(0);
  /**
   * 応答中に横から注入できない会話アイテム（look_at_page の画像など）の待機列。
   * 実機で「応答中の画像注入→以後完全沈黙」が2回再現したため、注入は応答の合間まで待たせる。
   */
  const pendingItemsRef = useRef<unknown[]>([]);
  /** データチャンネルの最終受信時刻。応答中のままイベントが途絶する状態の検知用。 */
  const lastDcEventAtRef = useRef(0);
  const guardianTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  /** レート制限の冷却期限（performance.now 基準）。この間は response.create を送らない。 */
  const cooldownUntilRef = useRef(0);
  /** 直近に注入したスクリーンショット群の item id。新しい画像を渡す前に古いのを消す（トークン節約）。 */
  const lastImageItemIdsRef = useRef<string[]>([]);
  /**
   * 会話のダイエット: ツール結果は毎応答で丸ごと再処理される（=TPMを恒常的に食う）ため、
   * 大きい結果に id を付けて追跡し、新しいものを残して古いものを会話から削除する。
   * レート制限牛歩の主因は思考量より「太った会話の再処理」（2026-08-22分析）。
   */
  const toolOutputItemsRef = useRef<Array<{ id: string; size: number }>>([]);
  const configRef = useRef(config);
  configRef.current = config;
  const targetPathRef = useRef(targetPath);
  targetPathRef.current = targetPath;

  const logBufferRef = useRef<LogEntry[]>([]);
  const pushLog = useCallback((tag: LogEntry['tag'], text: string) => {
    const entry = { time: now(), tag, text };
    logBufferRef.current.push(entry);
    setLog((l) => [...l, entry].slice(-250));
  }, []);

  // ログをサーバーへ永続化（開発CLIが後から logs/realtime-voice/<id>.jsonl を読める）。
  // リロードで消える問題の対策。3秒ごとにバッチ送信、ページ離脱時は sendBeacon で残りを送る。
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

  useEffect(() => {
    pushLog('⚙', `ログ保存先: logs/realtime-voice/${logSession}.jsonl（開発CLIが読めます）`);
  }, [logSession, pushLog]);

  const sinceSpeech = useCallback((): string => {
    const t0 = speechStoppedAtRef.current;
    if (t0 === null) return '';
    return ` (+${((performance.now() - t0) / 1000).toFixed(2)}s)`;
  }, []);

  // ---------------------------------------------------- iframe helpers

  const getIframeDoc = useCallback((): Document | null => {
    try {
      return iframeRef.current?.contentDocument ?? null;
    } catch {
      return null;
    }
  }, []);

  const getInspector = useCallback((): DanInspectorApi | null => {
    try {
      const win = iframeRef.current?.contentWindow as unknown as
        | (Window & { __DAN_INSPECTOR__?: DanInspectorApi })
        | null;
      return win?.__DAN_INSPECTOR__ ?? null;
    } catch {
      return null;
    }
  }, []);

  // ---------------------------------------------- 成果物スナップショット

  const snapshotTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /**
   * 編集後ページの完全HTMLを logs/realtime-voice/ に保存する（1.5秒デバウンス）。
   * 実行ログだけでは「何が作られたか」を後から評価できないため、
   * 編集のたび・再読込のたびに成果物の実体を残す。
   */
  const scheduleSnapshot = useCallback(
    (label: string) => {
      if (snapshotTimerRef.current) clearTimeout(snapshotTimerRef.current);
      snapshotTimerRef.current = setTimeout(() => {
        const doc = getIframeDoc();
        if (!doc) return;
        const html = `<!doctype html>\n${doc.documentElement.outerHTML}`;
        void fetch('/scratch/realtime-voice/api/log', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: logSession, snapshot_html: html, snapshot_label: label }),
        })
          .then((r) => r.json())
          .then((d) => {
            if (d?.snapshot) pushLog('💾', `成果物スナップショット保存: ${d.snapshot}`);
          })
          .catch(() => {});
      }, 1500);
    },
    [getIframeDoc, logSession, pushLog],
  );

  // ------------------------------------------------------ persistence

  /** inspector_overrides に draft として保存する。Inspector 手編集と同じ保存先。 */
  const persistOverride = useCallback(
    async (
      key: string,
      styles: Record<string, string>,
      attrs: Record<string, unknown>,
    ): Promise<{ saved: boolean; reason?: string }> => {
      const slug = parseSlug(targetPathRef.current);
      if (!slug) return { saved: false, reason: '対象パスから slug を特定できません' };
      const token = typeof localStorage !== 'undefined' ? localStorage.getItem('done-token') || '' : '';
      try {
        const res = await fetch('/api/v1/inspector-overrides', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ artifact_slug: slug, element_key: key, styles, attrs }),
        });
        if (res.ok) {
          pushLog('💾', `draft保存 OK: ${key}`);
          scheduleSnapshot('edit');
          return { saved: true };
        }
        const reason =
          res.status === 401
            ? '保存に必要なログインが切れています。ユーザーへの案内: 「同じブラウザの新しいタブで http://localhost:3000 （いつものダンのチャット画面）を開き、ログインし直してください。その後もう一度お願いすれば保存できます」。これ以外の画面や手順を推測で説明しないこと。画面への反映自体は済んでいます。'
            : `保存失敗 HTTP ${res.status}`;
        pushLog('⚠', reason);
        return { saved: false, reason };
      } catch (e) {
        const reason = `保存エラー: ${String(e).slice(0, 120)}`;
        pushLog('⚠', reason);
        return { saved: false, reason };
      }
    },
    [pushLog, scheduleSnapshot],
  );

  // ------------------------------------------------------------ tools

  const dcSend = useCallback((obj: unknown) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === 'open') dc.send(JSON.stringify(obj));
  }, []);

  /**
   * 音声モデルの「目」: 画面共有からスクリーンショットを1枚撮る。
   * 初回のみブラウザの共有許可ダイアログが出る（このタブを選んでもらう）。
   * 以後はストリームを使い回して無音でキャプチャできる。
   */
  const captureScreenshot = useCallback(async (): Promise<string | null> => {
    let stream = displayStreamRef.current;
    if (!stream || !stream.active) {
      const constraints: MediaStreamConstraints & { video: Record<string, unknown> } = {
        video: { preferCurrentTab: true },
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
    return canvas.toDataURL('image/jpeg', 0.75);
  }, []);

  /**
   * response.create を安全に発行する。進行中の response があるときは旗だけ立て、
   * response.done 時に1回だけ送る（重複送信は conversation_already_has_active_response
   * エラーになるため）。ツール実行が非同期（DB保存待ち）でも取りこぼさない。
   */
  /** 待機中の会話アイテム（画像など）を、応答の合間に順序どおり流し込む。 */
  const flushPendingItems = useCallback(() => {
    const items = pendingItemsRef.current.splice(0);
    for (const item of items) dcSend(item);
  }, [dcSend]);

  /** 会話アイテムを注入する。応答中なら待機列へ（横から差し込むと沈黙する実機事象対策）。 */
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
    responseActiveRef.current = true; // response.created が来る前の重複送信を防ぐ楽観セット
    dcSend({ type: 'response.create' });
    // ウォッチドッグ: 6秒たっても response.created が来なければ検知してもう一度だけ要求する。
    // （画像注入直後にモデルが完全沈黙した実機事象 2026-08-21 の診断と自動復旧）
    const tick = responseTickRef.current;
    setTimeout(() => {
      if (responseTickRef.current !== tick) return; // 正常に生成された
      const dc = dcRef.current;
      if (!dc || dc.readyState !== 'open') {
        pushLog('⚠', '応答が生成されないまま接続が失われています（response watchdog）');
        return;
      }
      pushLog('⚠', 'response.create に6秒応答なし → 再要求します（response watchdog）');
      responseActiveRef.current = true;
      dcSend({ type: 'response.create' });
    }, 6000);
  }, [dcSend, flushPendingItems, pushLog]);

  /** システム由来の情報（画像生成完了など）を会話へ注入し、応答を促す。 */
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

  const applyStyles = useCallback(
    async (id: string, rawStyles: Record<string, string>) => {
      const insp = getInspector();
      if (!insp) return { error: '対象ページの編集ランタイムに接続できません（iframe 読込中かも）' };
      const doc = getIframeDoc();
      if (doc && !doc.querySelector(`[data-edit-id="${CSS.escape(id)}"]`)) {
        return { error: `id "${id}" の要素が見つかりません（get_page_state で確認してください）` };
      }
      // 適用側は el.style.setProperty() を使うため、プロパティ名は kebab-case 必須。
      // モデルが camelCase で渡してきても効くように正規化する。
      const styles: Record<string, string> = {};
      for (const [k, v] of Object.entries(rawStyles)) {
        styles[k.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`)] = v;
      }
      const key = `@${id}`;
      insp.applyOverride(key, styles, {});
      const { saved, reason } = await persistOverride(key, styles, {});
      return { ok: true, id, saved, ...(reason ? { note: reason } : {}) };
    },
    [getIframeDoc, getInspector, persistOverride],
  );

  const executeTool = useCallback(
    async (name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> => {
      const doc = getIframeDoc();

      // 委譲中は書き込み系ツールをロックする。前回、ダンが draft を整理している最中に
      // 音声側が並行で draft を保存し、完成形とユーザーの見た目がズレる事故が起きた。
      const WRITE_TOOLS = new Set(['set_text', 'set_style', 'generate_image', 'edit_source', 'write_source']);
      if (delegatingRef.current && WRITE_TOOLS.has(name)) {
        return {
          error:
            'ダンの委譲作業が進行中のため、競合を避けるため編集はロックされています。' +
            '完了通知が来てから続けてください（状況は check_dan_status で確認できます）。',
        };
      }

      if (name === 'get_page_state') {
        if (!doc) return { error: '対象ページを読み込めていません' };
        const els = Array.from(doc.querySelectorAll<HTMLElement>('[data-edit-id]'));
        const list = els.slice(0, 100).map((el) => ({
          id: el.getAttribute('data-edit-id'),
          tag: el.tagName.toLowerCase(),
          text: (el.textContent ?? '').trim().slice(0, 60),
          style: (el.getAttribute('style') ?? '').slice(0, 120),
        }));
        return { count: els.length, truncated: els.length > 100, elements: list };
      }

      if (name === 'set_text') {
        const insp = getInspector();
        if (!insp) return { error: '対象ページの編集ランタイムに接続できません' };
        const id = String(args.id ?? '');
        const key = `@${id}`;
        const el = doc?.querySelector(`[data-edit-id="${CSS.escape(id)}"]`);
        if (!el) return { error: `id "${id}" の要素が見つかりません` };
        // 既存の編集モデルを取得して text だけ差し替える（過去のスタイル編集を保全）
        const model = insp.getModel(key) ?? { v: 2 as const, text: null, blockStyle: {}, spans: [], attrs: {} };
        const nextModel = { ...model, text: String(args.text ?? '') };
        const attrs = { model_v2: JSON.stringify(nextModel) };
        insp.applyOverride(key, {}, attrs);
        const { saved, reason } = await persistOverride(key, {}, attrs);
        return { ok: true, id, saved, ...(reason ? { note: reason } : {}) };
      }

      if (name === 'set_style') {
        return applyStyles(String(args.id ?? ''), (args.styles ?? {}) as Record<string, string>);
      }

      if (name === 'generate_image') {
        const prompt = String(args.prompt ?? '').trim();
        const targetId = String(args.target_id ?? '');
        const mode = args.mode === 'src' ? 'src' : 'background';
        const size = typeof args.size === 'string' ? args.size : undefined;
        if (!prompt || !targetId) return { error: 'prompt と target_id が必要です' };
        pushLog('🖼', `画像生成開始: "${prompt.slice(0, 80)}" → ${targetId} (${mode})`);
        // 生成はバックグラウンドで走らせ、完成したら適用+会話に通知する
        void (async () => {
          try {
            const res = await fetch('/scratch/realtime-voice/api/generate-image', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ prompt, size }),
            });
            const data = await res.json();
            if (!res.ok || !data.url) throw new Error(data.error || `HTTP ${res.status}`);
            pushLog('🖼', `画像生成完了 (${data.seconds}s): ${data.url}`);
            if (mode === 'background') {
              await applyStyles(targetId, {
                backgroundImage: `url(${data.url})`,
                backgroundSize: 'cover',
                backgroundPosition: 'center',
              });
            } else {
              const insp = getInspector();
              const key = `@${targetId}`;
              insp?.applyOverride(key, {}, { src: data.url });
              await persistOverride(key, {}, { src: data.url });
            }
            injectSystemAndRespond(
              `[システム通知] 画像生成が完了し、${targetId} に適用しました。ユーザーに一言で報告してください。`,
            );
          } catch (e) {
            pushLog('⚠', `画像生成失敗: ${String(e).slice(0, 200)}`);
            injectSystemAndRespond(
              `[システム通知] 画像生成に失敗しました（${String(e).slice(0, 120)}）。ユーザーに伝えてください。`,
            );
          }
        })();
        return { status: 'generating', note: '20〜60秒で完成し、自動適用されたら通知が届きます' };
      }

      if (name === 'delegate_to_dan') {
        const task = String(args.task ?? '').trim();
        if (!task) return { error: 'task が空です' };
        const ws = delegateWsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          return { error: '実行エンジン（ダン）に接続できていません。委譲は使えませんが、直接編集ツールは使えます。' };
        }
        const slug = parseSlug(targetPathRef.current) || 'unknown';
        // 表示中の実状態（DB override 適用後）を添付する。ソースコードだけ読むと
        // 音声編集で差し替わった題材（何のLPか）を見誤るため、これが正であると明示する。
        let currentState = '';
        if (doc) {
          currentState = Array.from(doc.querySelectorAll<HTMLElement>('[data-edit-id]'))
            .slice(0, 60)
            .map((el) => {
              const text = (el.textContent ?? '').trim().slice(0, 100);
              return `- ${el.getAttribute('data-edit-id')} <${el.tagName.toLowerCase()}>: ${text}`;
            })
            .join('\n');
        }
        // ダン側には「どの成果物のコードを触るか」の文脈を明示して渡す
        const wrapped = [
          '【音声編集セッションからの委譲タスク】',
          `対象成果物: slug=${slug}（表示中ページ: ${targetPathRef.current}、ソース: frontend/src/app/artifacts/${slug}/ 配下）`,
          `指示: ${task}`,
          '',
          '【いまページに表示されている実状態（DBのdraft override適用後。これが正）】',
          'ソースコードの内容と食い違う場合、ユーザーが見ているのはこちら。題材・文言はこの内容を尊重し、' +
            '無関係な題材のコンテンツを作らないこと:',
          currentState || '（取得できませんでした）',
          '',
          '注意: 既存要素の data-edit-id は保持し、新しく追加する編集対象要素にも一意の data-edit-id を付けること。' +
            '完了したら何をどう変えたかを簡潔に報告すること。' +
            '音声側エージェントに残作業を頼む場合は、報告の冒頭に【音声側の残作業】として箇条書きすること。',
        ].join('\n');
        ws.send(JSON.stringify({ type: 'delegate', task: wrapped, room_id: `voice-lp-${slug}` }));
        delegatingRef.current = true;
        danActivityRef.current = [];
        pushLog('📋', `委譲: ${task.slice(0, 120)}`);
        return { status: 'delegated', note: '開発エージェントに渡しました。数分かかることがあります。完了したら通知が届きます。' };
      }

      if (
        name === 'list_source_files' ||
        name === 'read_source' ||
        name === 'edit_source' ||
        name === 'write_source'
      ) {
        const slug = parseSlug(targetPathRef.current);
        if (!slug) return { error: '対象パスから slug を特定できません' };
        const action =
          name === 'list_source_files' ? 'list' : name === 'read_source' ? 'read' : name === 'edit_source' ? 'edit' : 'write';
        try {
          const res = await fetch('/scratch/realtime-voice/api/source', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              action,
              slug,
              file: args.file,
              old_string: args.old_string,
              new_string: args.new_string,
              content: args.content,
            }),
          });
          const data = (await res.json()) as Record<string, unknown>;
          if (!res.ok) return { error: String(data.error || `HTTP ${res.status}`) };
          // 音声セッションのコンテキスト保護（巨大ファイルの丸読み対策）
          if (typeof data.content === 'string' && data.content.length > 40_000) {
            data.content = data.content.slice(0, 40_000);
            data.truncated = true;
          }
          if (action === 'edit' || action === 'write') {
            pushLog('💾', `ソース${action === 'edit' ? '編集' : '書換'}: ${String(args.file)}`);
            scheduleSnapshot('source-edit');
          }
          return data;
        } catch (e) {
          return { error: `ソース操作に失敗: ${String(e).slice(0, 120)}` };
        }
      }

      if (name === 'look_at_page') {
        // ページ全体（スクロール全域・draft適用済み）を「文字が読める解像度」のタイル群で見る。
        // 縮小1枚では小さい文字が判読できず、汎用知能が自分で問題に気付けない（2026-08-22教訓）。
        try {
          const token = localStorage.getItem('done-token') || '';
          const res = await fetch('/scratch/realtime-voice/api/screenshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: targetPathRef.current, token }),
          });
          const data = (await res.json()) as { tiles?: string[]; count?: number; bytes?: number; file?: string; error?: string };
          if (!res.ok || !data.tiles?.length) return { error: String(data.error || `HTTP ${res.status}`) };
          // トークン節約: 古いスクショ群は会話から消して、常に最新セットだけ残す
          for (const oldId of lastImageItemIdsRef.current) {
            injectItem({ type: 'conversation.item.delete', item_id: oldId });
          }
          const newIds: string[] = [];
          data.tiles.forEach((tile, i) => {
            const id = `item_img_${Date.now()}_${i}`;
            newIds.push(id);
            injectItem({
              type: 'conversation.item.create',
              item: { id, type: 'message', role: 'user', content: [{ type: 'input_image', image_url: tile }] },
            });
          });
          lastImageItemIdsRef.current = newIds;
          pushLog('🖼', `ページ全体を高解像度タイル${data.tiles.length}枚でモデルに渡しました (計${Math.round((data.bytes || 0) / 1024)}KB・古いスクショは会話から削除)`);
          return {
            ok: true,
            tiles: data.tiles.length,
            note:
              `ページ全体を上から順に${data.tiles.length}枚の高解像度タイルで添付しました。` +
              'draft編集も反映済みの、ユーザーが見ているのと同じ状態です。文字の可読性・配色・レイアウト崩れなど、' +
              '悪いところに自分の目で気付いてください。',
          };
        } catch (e) {
          return { error: `確認用スクリーンショットに失敗: ${String(e).slice(0, 120)}` };
        }
      }

      if (name === 'look_at_section') {
        const id = String(args.id ?? '');
        if (!id) return { error: 'id が必要です' };
        try {
          const token = localStorage.getItem('done-token') || '';
          const res = await fetch('/scratch/realtime-voice/api/screenshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: targetPathRef.current, token, element_id: id }),
          });
          const data = (await res.json()) as { image?: string; bytes?: number; file?: string; error?: string };
          if (!res.ok || !data.image) return { error: String(data.error || `HTTP ${res.status}`) };
          for (const oldId of lastImageItemIdsRef.current) {
            injectItem({ type: 'conversation.item.delete', item_id: oldId });
          }
          const sectionItemId = `item_img_${Date.now()}`;
          lastImageItemIdsRef.current = [sectionItemId];
          injectItem({
            type: 'conversation.item.create',
            item: { id: sectionItemId, type: 'message', role: 'user', content: [{ type: 'input_image', image_url: data.image }] },
          });
          pushLog('🖼', `要素 ${id} の原寸スクリーンショットをモデルに渡しました (${Math.round((data.bytes || 0) / 1024)}KB)`);
          return { ok: true, note: `要素 ${id} の原寸スクリーンショットを会話に添付しました。細部までこれで確認できます。` };
        } catch (e) {
          return { error: `セクション撮影に失敗: ${String(e).slice(0, 120)}` };
        }
      }

      if (name === 'check_contrast') {
        // WCAG コントラスト比の機械検査。縮小スクショでは見えない「文字の同化」を
        // 決定的に検出する（2026-08-21、エージェントが同化未解消を「解消済み」と誤報告した対策）。
        const win = iframeRef.current?.contentWindow;
        if (!doc || !win) return { error: '対象ページを読み込めていません' };
        // どんなCSS色形式でも読めるパーサ。computed color はデザイントークン由来だと
        // lab()/oklch() 等で返り、rgb() 専用の正規表現では解析失敗＝黙殺されていた
        // （2026-08-22 実証: これがトークン色ページで「0件」と嘘をついた真因）。
        // canvas に1px塗って実RGBA値を読み取る方式なら形式を問わない。
        const canvas = doc.createElement('canvas');
        canvas.width = 1;
        canvas.height = 1;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        const parseRgb = (s: string): [number, number, number, number] | null => {
          if (!s || !ctx) return null;
          ctx.clearRect(0, 0, 1, 1);
          ctx.fillStyle = s;
          ctx.fillRect(0, 0, 1, 1);
          const d = ctx.getImageData(0, 0, 1, 1).data;
          return [d[0], d[1], d[2], d[3] / 255];
        };
        const lum = (c: [number, number, number, number]) => {
          const f = (v: number) => {
            const x = v / 255;
            return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
          };
          return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
        };
        const failures: Array<Record<string, unknown>> = [];
        let checked = 0;
        let skippedImageBg = 0;
        let animatedOut = 0;
        for (const el of Array.from(doc.body.querySelectorAll<HTMLElement>('*'))) {
          const hasDirectText = Array.from(el.childNodes).some(
            (n) => n.nodeType === 3 && (n.textContent ?? '').trim().length > 0,
          );
          if (!hasDirectText) continue;
          const rect = el.getBoundingClientRect();
          if (rect.width < 1 || rect.height < 1) continue; // 畳まれたメニュー等の実表示なし要素
          const cs = win.getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden') continue;
          // スクロール出現アニメーションで opacity:0 の要素もスキップしない。
          // 表示され切った後の色で評価する（skipすると検査が「0件」と嘘をつく。2026-08-22実証: 36要素が黙殺されていた）
          if (parseFloat(cs.opacity || '1') < 0.1) animatedOut += 1;
          const fg = parseRgb(cs.color);
          if (!fg) continue;
          // 背景色: 祖先を遡って最初の不透明背景。途中に背景画像があれば判定不能としてスキップ
          let bg: [number, number, number, number] | null = null;
          let hasImage = false;
          let cur: HTMLElement | null = el;
          while (cur && cur !== doc.body.parentElement) {
            const ccs = win.getComputedStyle(cur);
            if (ccs.backgroundImage && ccs.backgroundImage !== 'none') {
              hasImage = true;
              break;
            }
            const b = parseRgb(ccs.backgroundColor);
            if (b && b[3] > 0.01) {
              bg = b;
              break;
            }
            cur = cur.parentElement;
          }
          if (hasImage) {
            skippedImageBg += 1;
            continue;
          }
          if (!bg) bg = [255, 255, 255, 1];
          checked += 1;
          const l1 = lum(fg);
          const l2 = lum(bg);
          const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
          const fontSize = parseFloat(cs.fontSize) || 16;
          const threshold = fontSize >= 24 ? 3 : 4.5;
          if (ratio < threshold) {
            const text = (el.textContent ?? '').trim().slice(0, 40);
            failures.push({
              id: el.dataset.editId || null,
              where: el.dataset.editId
                ? undefined
                : `${el.tagName.toLowerCase()}${el.className ? `.${String(el.className).split(' ')[0]}` : ''}「${text.slice(0, 20)}」`,
              ratio: Math.round(ratio * 10) / 10,
              required: threshold,
              color: cs.color,
              background: `rgb(${bg[0]},${bg[1]},${bg[2]})`,
              text,
            });
          }
        }
        pushLog('🔧', `check_contrast: ${checked}要素検査 / 問題 ${failures.length}件 / 画像背景スキップ ${skippedImageBg}件 / アニメ未表示込み ${animatedOut}件`);
        return {
          checked,
          failures: failures.slice(0, 30),
          skipped_image_background: skippedImageBg,
          elements_hidden_by_entry_animation: animatedOut,
          note: failures.length
            ? 'failures の要素は文字が背景に同化して読めません。id があるものは set_style、無いものは edit_source で色を修正してください。'
            : 'コントラスト問題は検出されませんでした（画像背景上の文字は検査対象外）。',
        };
      }

      if (name === 'look_at_screen') {
        try {
          const dataUrl = await captureScreenshot();
          if (!dataUrl) return { error: 'スクリーンショットを取得できませんでした' };
          for (const oldId of lastImageItemIdsRef.current) {
            injectItem({ type: 'conversation.item.delete', item_id: oldId });
          }
          const screenItemId = `item_img_${Date.now()}`;
          lastImageItemIdsRef.current = [screenItemId];
          injectItem({
            type: 'conversation.item.create',
            item: { id: screenItemId, type: 'message', role: 'user', content: [{ type: 'input_image', image_url: dataUrl }] },
          });
          pushLog('🖼', `ユーザー画面のキャプチャをモデルに渡しました (${Math.round(dataUrl.length / 1024)}KB)`);
          return { ok: true, note: 'ユーザーの画面（現在映っている範囲）のスクリーンショットを会話に添付しました。' };
        } catch (e) {
          return {
            error: `画面キャプチャに失敗しました（共有が許可されなかった可能性）: ${String(e).slice(0, 120)}`,
          };
        }
      }

      if (name === 'check_dan_status') {
        return {
          running: delegatingRef.current,
          recent_activity: danActivityRef.current.slice(-6),
          note: delegatingRef.current
            ? 'ダンは作業中です。完了すると通知が届きます。'
            : '進行中の委譲作業はありません。',
        };
      }

      if (name === 'run_js') {
        if (!doc) return { error: '対象ページを読み込めていません' };
        const code = String(args.code ?? '');
        try {
          const fn = new Function('document', 'window', code);
          return { ok: true, result: safeStringify(fn(doc, iframeRef.current?.contentWindow)) };
        } catch (e) {
          return { ok: false, error: String(e).slice(0, 500) };
        }
      }

      return { error: `未知のツール: ${name}` };
    },
    [applyStyles, captureScreenshot, dcSend, getIframeDoc, getInspector, injectItem, injectSystemAndRespond, persistOverride, pushLog, scheduleSnapshot],
  );

  // ------------------------------------------------------ connection

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
    speechStoppedAtRef.current = null;
    responseActiveRef.current = false;
    pendingResponseRef.current = false;
    // 再接続時は前セッションの会話アイテムIDを引き継がない
    // （古いIDへの削除要求が item_delete_invalid_item で空振りする。2026-08-22実測）
    lastImageItemIdsRef.current = [];
    toolOutputItemsRef.current = [];
    pendingItemsRef.current = [];
    cooldownUntilRef.current = 0;

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
      pushLog('🔧', `${item.name}(${JSON.stringify(args).slice(0, 160)})${sinceSpeech()}`);
      setCurrentActivity(TOOL_LABELS[item.name] || item.name);
      const result = await executeTool(item.name, args);
      setCurrentActivity(null);
      if ('error' in result) pushLog('⚠', `ツール失敗: ${String(result.error)}`);
      const output = JSON.stringify(result);
      const outputItemId = `item_out_${Date.now()}_${Math.floor(Math.random() * 1e4)}`;
      dcSend({
        type: 'conversation.item.create',
        item: { id: outputItemId, type: 'function_call_output', call_id: item.call_id, output },
      });
      // 会話ダイエット: 直近3件は必ず残し、それより古い大物から削除して
      // 追跡合計を約24k文字以下に保つ（毎応答の再処理コスト＝TPM消費を抑える）
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
        case 'input_audio_buffer.speech_stopped':
          speechStoppedAtRef.current = performance.now();
          break;
        case 'response.created':
          responseActiveRef.current = true;
          responseTickRef.current += 1;
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
        case 'response.output_item.done': {
          const item = msg.item as { type?: string; name?: string; call_id?: string; arguments?: string };
          if (item?.type === 'function_call') void handleFunctionCall(item);
          break;
        }
        case 'response.done': {
          setSpeaking(false);
          responseActiveRef.current = false;
          const response = (msg.response as { output?: unknown[]; status?: string; status_details?: unknown; usage?: Record<string, unknown> }) || {};
          // 概算コスト集計（gpt-realtime-2.1 公表単価: text入$4/出$16、audio入$32/出$64、cached入$0.40 [/1Mトークン]）
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
              (freshText * 4 + cached * 0.4 + (i.audio_tokens || 0) * 32 + (o.text_tokens || 0) * 16 + (o.audio_tokens || 0) * 64) / 1_000_000;
            if (usd > 0) setSessionCost((c) => c + usd);
          }
          // 沈黙の切り分け: 正常完了以外のステータスは必ず可視化する
          if (response.status && response.status !== 'completed') {
            const details = JSON.stringify(response.status_details ?? {});
            pushLog('⚠', `response ${response.status}: ${details.slice(0, 200)}`);
            // レート制限は「待つべき秒数」を読み取り、冷却してから自動再開する
            // （即再要求は制限をさらに食い潰すだけ。2026-08-21 実測の真犯人対応）
            if (details.includes('rate_limit_exceeded')) {
              const m = details.match(/try again in ([\d.]+)s/);
              const waitMs = m ? Math.ceil(parseFloat(m[1]) * 1000) + 800 : 8000;
              cooldownUntilRef.current = performance.now() + waitMs;
              pushLog('⚠', `レート制限: ${(waitMs / 1000).toFixed(1)}秒冷却して自動再開します`);
              setTimeout(() => {
                if (dcRef.current?.readyState === 'open') scheduleResponse();
              }, waitMs + 200);
            }
          }
          flushPendingItems();
          const followups = (response.output || [])
            .map((raw) => raw as { type?: string; name?: string; call_id?: string; arguments?: string })
            .filter((item) => item.type === 'function_call');
          // output_item.done で取りこぼした function_call の保険（通常は dedupe で素通り）
          for (const item of followups) void handleFunctionCall(item);
          if (pendingResponseRef.current) {
            pendingResponseRef.current = false;
            scheduleResponse();
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

      const cfg = { ...configRef.current, surface: 'lp' as const };
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
      pushLog('⚙', `セッション発行 OK: ${cfg.model} / effort=${cfg.effort} / lane=${cfg.lane} / 対象=${targetPathRef.current}`);

      // ---- 委譲ブリッジ（ダンコアの /ws/realtime-delegate）。失敗しても直接編集は使える ----
      const danActivity = (line: string) => {
        danActivityRef.current = [...danActivityRef.current, `${now()} ${line}`].slice(-6);
      };
      const handleDelegateMsg = (data: RtEvent) => {
        switch (data.type) {
          case 'delegate_started':
            delegatingRef.current = true;
            setCurrentActivity('ダンが作業中（委譲）');
            pushLog('📋', `ダンが作業を開始しました（room=${String(data.room_id || '')}）`);
            break;
          case 'reasoning':
            pushLog('⚙', `… ${String(data.text || '').slice(0, 150)}`);
            danActivity(`思考: ${String(data.text || '').slice(0, 60)}`);
            break;
          case 'tool_use':
            pushLog('🔧', `(ダン) ${String(data.name || 'tool')}`);
            danActivity(`ツール実行: ${String(data.name || 'tool')}`);
            break;
          case 'text':
            pushLog('⚙', `(ダン) ${String(data.text || '').slice(0, 150)}`);
            danActivity(`発言: ${String(data.text || '').slice(0, 60)}`);
            break;
          case 'result':
            delegatingRef.current = false;
            setCurrentActivity(null);
            pushLog('✅', 'ダンの作業完了。ページを再読込します');
            setIframeKey((k) => k + 1);
            injectSystemAndRespond(
              `[システム通知] 開発エージェントの作業が完了し、ページを再読込しました。完了報告（全文）:\n${String(data.text || '').slice(0, 6000)}\n\n` +
                'ユーザーに要点を一言で報告してください。報告に【音声側の残作業】が書かれている場合は、' +
                'ユーザーに聞き直さず、そのままあなたのツールで続けて実行し、完了まで進めてください。',
            );
            break;
          case 'error':
            delegatingRef.current = false;
            setCurrentActivity(null);
            pushLog('⚠', `ダン側エラー: ${String(data.message || '')}`);
            injectSystemAndRespond(
              `[システム通知] 開発エージェントでエラーが発生しました: ${String(data.message || '').slice(0, 200)}。ユーザーに伝えてください。`,
            );
            break;
          case 'busy':
            pushLog('⚠', '別の委譲作業が進行中です（完了を待ってから次を頼んでください）');
            break;
        }
      };

      try {
        const token = localStorage.getItem('done-token') || '';
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = await new Promise<WebSocket>((resolve, reject) => {
          const sock = new WebSocket(`${proto}//${window.location.host}/ws/realtime-delegate`);
          const to = setTimeout(() => {
            try {
              sock.close();
            } catch {
              /* noop */
            }
            reject(new Error('timeout'));
          }, 12000);
          sock.onopen = () => sock.send(JSON.stringify({ type: 'auth', token }));
          sock.onmessage = (e) => {
            let data: RtEvent;
            try {
              data = JSON.parse(e.data);
            } catch {
              return;
            }
            if (data.type === 'auth_success') {
              clearTimeout(to);
              resolve(sock);
              return;
            }
            handleDelegateMsg(data);
          };
          sock.onerror = () => {
            clearTimeout(to);
            reject(new Error('ws error'));
          };
        });
        if (!live()) {
          try {
            ws.close();
          } catch {
            /* noop */
          }
          return;
        }
        delegateWsRef.current = ws;
        pushLog('⚙', '実行エンジン（委譲チャンネル）接続 OK');
      } catch {
        pushLog('⚠', '実行エンジンに接続できません（委譲は不可・直接編集は可能）');
      }

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
        lastDcEventAtRef.current = performance.now();
        try {
          handleRtEvent(JSON.parse(e.data));
        } catch {
          /* noop */
        }
      };
      // 沈黙の原因切り分け用: チャンネル断は必ずログに残す（2026-08-21 完全沈黙事象の診断）
      dc.onclose = () => pushLog('⚠', '音声データチャンネルが閉じました（イベント送受信は停止）');
      dc.onerror = (e) => pushLog('⚠', `音声データチャンネルでエラー: ${String((e as ErrorEvent).error || e.type).slice(0, 120)}`);

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
        const st = pc?.connectionState;
        if (st && st !== 'connected' && st !== 'new' && st !== 'connecting') {
          pushLog('⚠', `WebRTC接続状態: ${st}`);
        }
        if (st === 'failed') {
          setError('音声接続が切断されました');
          setStatus('error');
        }
      };

      pcRef.current = pc;
      dcRef.current = dc;
      micRef.current = mic;
      audioRef.current = audioEl;
      setStatus('connected');
      lastDcEventAtRef.current = performance.now();

      // guardian: 保留中の応答要求・注入待ちアイテムの取り残し、および
      // 「応答進行中のままイベント20秒途絶」を検知して自動再駆動する常駐見張り。
      if (guardianTimerRef.current) clearInterval(guardianTimerRef.current);
      guardianTimerRef.current = setInterval(() => {
        if (!dcRef.current || dcRef.current.readyState !== 'open') return;
        if (performance.now() < cooldownUntilRef.current) return; // レート制限の冷却中は動かない
        if (!responseActiveRef.current && (pendingResponseRef.current || pendingItemsRef.current.length > 0)) {
          pushLog('⚠', 'guardian: 保留中の応答要求/注入待ちを再駆動します');
          pendingResponseRef.current = false;
          scheduleResponse();
          return;
        }
        if (responseActiveRef.current && performance.now() - lastDcEventAtRef.current > 20_000) {
          pushLog('⚠', 'guardian: 応答進行中のままイベントが20秒途絶 → 状態をリセットして再要求します');
          responseActiveRef.current = false;
          scheduleResponse();
        }
      }, 4000);

      pushLog('⚙', '接続完了。編集はdraftとして保存され、リロードしても残ります');
    } catch (e) {
      cleanupLocal();
      if (!live()) return;
      setError(e instanceof Error ? e.message : '接続に失敗しました');
      setStatus('error');
    }
  }, [dcSend, disconnect, executeTool, pushLog, scheduleResponse, sinceSpeech]);

  useEffect(() => () => disconnect(), [disconnect]);

  const updateConfig = useCallback(
    (patch: Partial<ExperimentConfig>) => {
      setConfig((prev) => {
        const next = { ...prev, ...patch, surface: 'lp' as const };
        if (dcRef.current?.readyState === 'open') {
          if (patch.model && patch.model !== prev.model) {
            pushLog('⚙', 'モデル変更は再接続が必要です');
          } else {
            dcSend({
              type: 'session.update',
              session: {
                type: 'realtime',
                instructions: buildInstructions(next.lane, next.preamble, 'lp'),
                tools: buildTools(next.lane, 'lp'),
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

  const selStyle: React.CSSProperties = {
    padding: '4px 8px',
    borderRadius: 6,
    border: '1px solid #cbd5e1',
    background: '#fff',
    fontSize: 13,
  };
  const labelStyle: React.CSSProperties = { fontSize: 11, color: '#64748b', display: 'block' };

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#f1f5f9', fontFamily: 'system-ui, sans-serif' }}>
      {/* ---------------- 左: 本物のLP (iframe) ---------------- */}
      <div style={{ flex: '0 0 540px', height: '100vh', background: '#fff', boxShadow: '2px 0 12px rgba(0,0,0,.08)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', gap: 6, padding: 8, borderBottom: '1px solid #e2e8f0' }}>
          <input
            value={targetPath}
            onChange={(e) => setTargetPath(e.target.value)}
            placeholder="/artifacts/test-edit"
            style={{ flex: 1, padding: '6px 10px', borderRadius: 6, border: '1px solid #cbd5e1', fontSize: 13 }}
          />
          <button
            onClick={() => setIframeKey((k) => k + 1)}
            style={{ padding: '6px 14px', borderRadius: 6, border: '1px solid #cbd5e1', background: '#f8fafc', fontSize: 13, cursor: 'pointer' }}
          >
            開く/再読込
          </button>
        </div>
        <iframe
          key={iframeKey}
          ref={iframeRef}
          src={targetPath}
          onLoad={() => scheduleSnapshot('load')}
          style={{ flex: 1, border: 'none', width: '100%' }}
          title="編集対象LP"
        />
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
                <option value="semantic">ボタン方式</option>
                <option value="raw">生JS直書き</option>
                <option value="both">両方</option>
              </select>
            </div>
            <div>
              <label style={labelStyle}>プリアンブル</label>
              <select style={selStyle} value={config.preamble} onChange={(e) => updateConfig({ preamble: e.target.value as PreambleMode })}>
                <option value="intent">意図を宣言</option>
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
            {/* 状態オーブ: 音声で実況させない代わりに、何をしているかを常時視覚表示する */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <style>{`@keyframes rt-pulse { 0%,100% { transform: scale(1); opacity: .9 } 50% { transform: scale(1.25); opacity: 1 } }`}</style>
              <div
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: '50%',
                  transition: 'background .3s',
                  background:
                    status !== 'connected'
                      ? '#cbd5e1'
                      : speaking
                        ? '#16a34a'
                        : currentActivity
                          ? '#f59e0b'
                          : '#2563eb',
                  animation:
                    status === 'connected' && (speaking || currentActivity)
                      ? 'rt-pulse 1.1s ease-in-out infinite'
                      : status === 'connected'
                        ? 'rt-pulse 2.6s ease-in-out infinite'
                        : 'none',
                }}
              />
              <span style={{ fontSize: 13, color: '#334155', minWidth: 160 }}>
                {status !== 'connected'
                  ? status
                  : speaking
                    ? '話しています（割り込みOK）'
                    : currentActivity
                      ? `実行中: ${currentActivity}`
                      : '聞いています'}
              </span>
              {sessionCost > 0 && (
                <span style={{ fontSize: 12, color: '#94a3b8' }} title="このセッションの概算API料金（公表単価×実測トークン）">
                  💰 ${sessionCost.toFixed(2)}（約{Math.round(sessionCost * 150)}円）
                </span>
              )}
            </div>
          </div>
          {error && <p style={{ color: '#dc2626', fontSize: 13, margin: '10px 0 0' }}>{error}</p>}
        </div>

        <div style={{ flex: 1, background: '#0f172a', borderRadius: 12, padding: 16, overflowY: 'auto', fontFamily: 'ui-monospace, monospace', fontSize: 12.5, lineHeight: 1.8 }}>
          {log.length === 0 && (
            <p style={{ color: '#64748b' }}>
              本物のLPを音声で編集します。編集は draft として保存され、リロードしても残り、
              既存の「公開」レールにそのまま乗ります。
              画像も「この背景を夕焼けの街並みの写真にして」のように頼めます（GPT Image 2 生成・20〜60秒）。
            </p>
          )}
          {log.map((e, i) => (
            <div key={i} style={{ color: e.tag === '🎤' ? '#7dd3fc' : e.tag === '🗣' ? '#fde68a' : e.tag === '🔧' ? '#86efac' : e.tag === '💾' ? '#a5b4fc' : e.tag === '🖼' ? '#f9a8d4' : e.tag === '⚠' ? '#fca5a5' : '#94a3b8' }}>
              <span style={{ color: '#475569' }}>{e.time}</span> {e.tag} {e.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
