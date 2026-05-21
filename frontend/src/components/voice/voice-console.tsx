'use client';

/**
 * 音声会話パネル（gpt-realtime-2）— UIコンポーネント本体。
 *
 * 単体ページ `/voice` からも、チャット内フローティングパネルからも使う共通部品。
 *
 * - `roomId` を渡すと CLI セッションキーとして使われ、delegate の進捗・完了報告が
 *   そのチャットに書き戻る（チャット内起動時の必須プロパティ）。未指定なら
 *   localStorage の voice-room を使うスタンドアロン会話。
 * - `onClose` を渡すと右上に閉じるボタンが出る（フローティングパネル用途）。
 * - HTTPS でも localhost でもない URL で開かれた場合は、ブラウザがマイクを許可しないため、
 *   「すぐに開ける secure な URL」（localhost と本番Vercel）のクリック導線を出す。
 *   テキストの説明文だけでは詰まる、というユーザー体験を避けるための救済UI。
 */
import { useEffect, useState } from 'react';
import { X } from 'lucide-react';

import { useRealtimeVoice } from '@/hooks/useRealtimeVoice';

const PROD_HOST = 'https://frontend-mikis-projects-86652663.vercel.app';

interface VoiceConsoleProps {
  /** delegate を紐づける CLI セッションID（チャットの project.room_id を渡す想定）。 */
  roomId?: string;
  /** 起動元チャットのタイトル。OpenAI realtime セッションの指示文に注入されて、
   *  音声AIが「何の文脈で話しているか」を理解できるようにする。 */
  chatTitle?: string;
  /** フローティング/モーダル用途で渡す。指定があれば右上に X ボタンが出る。 */
  onClose?: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  idle: '未接続',
  connecting: '接続中…',
  connected: '接続済み',
  error: 'エラー',
};

type SecureAlt = { label: string; url: string };

/** secure context でない場合、今いる URL を同じパスのまま secure 版に振り替えた候補リスト。 */
function computeSecureAlts(): SecureAlt[] | null {
  if (typeof window === 'undefined') return null;
  if (window.isSecureContext) return null;
  const port = window.location.port ? `:${window.location.port}` : '';
  const path = window.location.pathname + window.location.search;
  const alts: SecureAlt[] = [];
  const isLocalHostname =
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  if (!isLocalHostname) {
    alts.push({
      label: 'このPCで開く（localhost）',
      url: `http://localhost${port}${path}`,
    });
  }
  alts.push({
    label: '本番URL(HTTPS)で開く',
    url: `${PROD_HOST}${path}`,
  });
  return alts;
}

export function VoiceConsole({ roomId, chatTitle, onClose }: VoiceConsoleProps) {
  const [secureAlts, setSecureAlts] = useState<SecureAlt[] | null>(null);

  useEffect(() => {
    setSecureAlts(computeSecureAlts());
  }, []);

  const { status, error, speaking, delegating, transcript, progress, connect, disconnect } =
    useRealtimeVoice({ roomId, chatTitle });

  const isConnected = status === 'connected';
  const isBusy = status === 'connecting';

  // ---------- secure context でなければここで早期 return（救済UI） ----------
  if (secureAlts && secureAlts.length > 0) {
    return (
      <div className="flex flex-col gap-4 p-5 text-neutral-100">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-base font-semibold">音声開発</h2>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-neutral-400 transition hover:bg-neutral-800 hover:text-neutral-100"
              aria-label="閉じる"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <div className="rounded-lg border border-amber-800/50 bg-amber-950/40 p-3 text-sm text-amber-200">
          このURLではブラウザがマイクを許可しません。HTTPS または localhost
          で開く必要があります（ブラウザ仕様）。下のリンクで開き直してください。
        </div>
        <div className="flex flex-col gap-2">
          {secureAlts.map((alt) => (
            <a
              key={alt.url}
              href={alt.url}
              className="block rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 transition hover:border-neutral-500 hover:bg-neutral-800"
            >
              <div className="font-medium">{alt.label}</div>
              <div className="mt-0.5 truncate text-xs text-neutral-400">{alt.url}</div>
            </a>
          ))}
        </div>
      </div>
    );
  }

  // ---------- 通常UI ----------
  const orbState = error
    ? 'error'
    : speaking
      ? 'speaking'
      : isConnected
        ? 'connected'
        : isBusy
          ? 'connecting'
          : 'idle';

  const orbClass = {
    idle: 'bg-neutral-700',
    connecting: 'bg-amber-500 animate-pulse',
    connected: 'bg-emerald-600',
    speaking: 'bg-emerald-400 animate-pulse',
    error: 'bg-red-600',
  }[orbState];

  const orbLabel = speaking
    ? '話し中'
    : delegating
      ? '作業中'
      : isConnected
        ? '聞き取り中'
        : isBusy
          ? '…'
          : '';

  return (
    <div className="flex flex-col gap-4 p-5 text-neutral-100">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">音声開発</h2>
          {chatTitle ? (
            <p className="mt-0.5 truncate text-[11px] text-neutral-500" title={chatTitle}>
              文脈: {chatTitle}
            </p>
          ) : roomId ? (
            <p className="mt-0.5 text-[11px] text-neutral-500">
              このチャットの文脈で会話します
            </p>
          ) : null}
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-neutral-400 transition hover:bg-neutral-800 hover:text-neutral-100"
            aria-label="閉じる"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <button
        type="button"
        onClick={isConnected || isBusy ? disconnect : connect}
        className="flex flex-col items-center gap-2 self-center"
      >
        <span
          className={`flex h-24 w-24 items-center justify-center rounded-full text-xs font-medium shadow-lg transition ${orbClass}`}
        >
          {orbLabel}
        </span>
        <span className="text-xs text-neutral-300">
          {isBusy ? 'タップで中止' : isConnected ? 'タップで終了' : 'タップで会話を開始'}
        </span>
      </button>

      <div className="self-center text-[11px] text-neutral-500">
        状態: {STATUS_LABEL[status] ?? status}
      </div>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {delegating && (
        <div className="rounded-lg border border-amber-800 bg-amber-950/40 px-3 py-1.5 text-xs text-amber-300">
          開発エージェントが作業中です…
        </div>
      )}

      {transcript.length > 0 && (
        <section>
          <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-500">
            会話
          </h3>
          <div className="flex flex-col gap-1.5">
            {transcript.map((turn, i) => (
              <div
                key={i}
                className={turn.role === 'user' ? 'max-w-[85%] self-end' : 'max-w-[85%] self-start'}
              >
                <div
                  className={`rounded-2xl px-2.5 py-1.5 text-xs leading-relaxed ${
                    turn.role === 'user'
                      ? 'bg-neutral-200 text-neutral-900'
                      : 'bg-neutral-800 text-neutral-100'
                  }`}
                >
                  {turn.text}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {progress.length > 0 && (
        <section>
          <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-500">
            開発エンジンの進捗
          </h3>
          <div className="max-h-48 overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-900 p-2 font-mono text-[10px] leading-relaxed text-neutral-300">
            {progress.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap">
                {line}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
