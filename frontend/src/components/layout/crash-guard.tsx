'use client';

import { Component, Fragment, type ErrorInfo, type ReactNode } from 'react';

// このページを描いたビルドの名前（frontend_prod.py が焼き込む。開発サーバーでは空）。
const BUILD = process.env.NEXT_PUBLIC_DASHBOARD_BUILD || '';
const RELOAD_KEY = 'dan-crash-reload-at';
const RETRY_WINDOW_MS = 15_000;
const MAX_RETRIES = 2;
const RELOAD_GUARD_MS = 60_000;

/** 新しいビルドに入れ替わった後、古い画面が消えた部品を読みに行って失敗した時の例外か。 */
function isChunkError(error: unknown): boolean {
  const e = error as { name?: string; message?: string } | null;
  const text = `${e?.name ?? ''} ${e?.message ?? ''}`;
  return /ChunkLoadError|Loading chunk|Failed to load chunk|dynamically imported module|Importing a module script failed/i.test(text);
}

/**
 * 画面の例外を本体に記録する（.tmp/perf_events.jsonl、event=client-crash）。
 * 本人の画面で何が落ちたかは、これが無いとどこにも残らない（2026-10-17）。
 */
export function reportClientCrash(error: unknown, componentStack: string | null | undefined, action: string): void {
  if (typeof window === 'undefined') return;
  const e = error as { name?: string; message?: string; stack?: string; digest?: string } | null;
  // eslint-disable-next-line no-console
  console.error('[crash-guard]', action, error, componentStack);
  try {
    fetch('/api/v1/chat/perf', {
      method: 'POST',
      credentials: 'include',
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        surface: 'web',
        event: 'client-crash',
        ms: Math.round(performance.now()),
        room_id: null,
        at: new Date().toISOString(),
        ua: navigator.userAgent.slice(0, 160),
        extra: {
          action,
          name: e?.name ?? typeof error,
          message: String(e?.message ?? error).slice(0, 1000),
          digest: e?.digest,
          stack: (e?.stack ?? '').slice(0, 4000),
          component_stack: (componentStack ?? '').slice(0, 4000),
          path: window.location.pathname,
          build: BUILD,
          visibility: document.visibilityState,
        },
      }),
    }).catch(() => undefined);
  } catch {
    /* 記録の失敗で画面を巻き込まない */
  }
}

/** 直近に自動の読み直しをしていなければ、1回だけ読み直す。した直後なら false。 */
function reloadOnce(): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0);
    if (Date.now() - last < RELOAD_GUARD_MS) return false;
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch {
    /* sessionStorage が使えなくても読み直しはする */
  }
  window.location.reload();
  return true;
}

type State = { failed: boolean; stuck: boolean; generation: number };

/**
 * 画面のどこかの部品が描画中に例外を投げると、Next.js は画面全体を
 * 「Application error: a client-side exception has occurred」に差し替え、
 * 本人が読み直すまで戻らなかった（2026-10-17 本人の報告）。
 * ここで受け止めて記録し、部品を組み直して続ける。組み直しても続けて落ちる時は
 * 1回だけ読み直し、それでも落ちる時だけ読み直しのボタンを出す。
 */
export class CrashGuard extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false, stuck: false, generation: 0 };
  private recent: number[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    if (isChunkError(error)) {
      reportClientCrash(error, info.componentStack, 'reload-new-build');
      if (reloadOnce()) return;
    }
    const now = Date.now();
    this.recent = this.recent.filter((t) => now - t < RETRY_WINDOW_MS);
    this.recent.push(now);
    if (this.recent.length <= MAX_RETRIES) {
      reportClientCrash(error, info.componentStack, 'remount');
      if (this.timer) clearTimeout(this.timer);
      this.timer = setTimeout(() => {
        this.timer = null;
        this.setState((s) => ({ failed: false, generation: s.generation + 1 }));
      }, 0);
      return;
    }
    reportClientCrash(error, info.componentStack, 'reload');
    if (!reloadOnce()) this.setState({ stuck: true });
  }

  componentWillUnmount(): void {
    if (this.timer) clearTimeout(this.timer);
  }

  render(): ReactNode {
    if (this.state.stuck) {
      return (
        <div className="flex h-dvh flex-col items-center justify-center gap-4 bg-background p-6 text-center text-sm text-foreground">
          <p>画面の表示でエラーが続いています。内容はダンに記録しました。</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-full border border-border px-4 py-2 hover:bg-muted"
          >
            読み直す
          </button>
        </div>
      );
    }
    if (this.state.failed) return <div className="h-dvh bg-background" />;
    return <Fragment key={this.state.generation}>{this.props.children}</Fragment>;
  }
}
