'use client';

import { LIVE_VERSION } from 'dan-live-version';
import { useEffect } from 'react';

import { installLiveGuard } from '@/lib/live-version/guard';

/**
 * この画面が動かしている部品の版を window.__danLiveLoaded に書く（比べる処理は
 * lib/live-version/guard.ts。layout.tsx が HTML に埋め込む）。
 * LIVE_VERSION は部品に焼き込まれているので、古い部品なら古い版のまま残る。
 * HMR で版が届くとこのファイルも読み込み直されるので、版は読み込みのたびに書く
 * （部品の useEffect は HMR で走り直さないことがある）。
 * HTML の埋め込みより前に開いていた画面（HMR でこの部品だけ届いた場合）では、ここで比べる処理を始める。
 */
function markLoaded() {
  if (typeof window === 'undefined' || !LIVE_VERSION) return;
  const w = window as unknown as { __danLiveLoaded?: string };
  if (w.__danLiveLoaded === LIVE_VERSION) return;
  w.__danLiveLoaded = LIVE_VERSION;
  window.dispatchEvent(new Event('dan-live-loaded'));
}

markLoaded();

export function LiveVersionMark() {
  useEffect(() => {
    markLoaded();
    if (LIVE_VERSION) installLiveGuard({ serverVersion: LIVE_VERSION });
  }, []);
  return null;
}
