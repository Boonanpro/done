'use client';

import { useEffect, useState } from 'react';

// このページを描いたビルドの名前（frontend_prod.py が build 時に焼き込む）。開発サーバーでは空。
const LOADED_BUILD = process.env.NEXT_PUBLIC_DASHBOARD_BUILD || '';
const CHECK_MS = 60_000;

/**
 * ダッシュボード（3000）が新しいビルドに入れ替わったのに、開いたままのタブが入れ替え前の
 * 画面のプログラムを使い続けることがある（2026-10-17: 成果物タブの直しが、再読み込みするまで
 * 本人の画面に出なかった）。入れ替わりを見つけたら、タブが裏にある間に読み直す。前に出て
 * いる時は、入力中の文字を消さないよう勝手には読み直さず、読み直すボタンを出す。
 */
export function NewBuildNotice() {
  const [stale, setStale] = useState(false);

  useEffect(() => {
    if (!LOADED_BUILD) return;
    let found = false;
    const check = async () => {
      if (found) return;
      try {
        const res = await fetch('/dashboard-build', { cache: 'no-store' });
        if (!res.ok) return;
        const { build } = (await res.json()) as { build?: string };
        if (build && build !== LOADED_BUILD) {
          found = true;
          if (document.visibilityState === 'hidden') window.location.reload();
          else setStale(true);
        }
      } catch {
        // 本体の再起動中などは次の確認に任せる
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden' && found) window.location.reload();
      else if (document.visibilityState === 'visible') void check();
    };
    void check();
    const timer = window.setInterval(check, CHECK_MS);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  if (!stale) return null;
  return (
    <button
      onClick={() => window.location.reload()}
      className="fixed bottom-4 left-1/2 z-[60] -translate-x-1/2 rounded-full border border-border bg-background px-4 py-2 text-sm shadow-lg hover:bg-muted"
    >
      新しい版があります — 押すと読み直します
    </button>
  );
}
