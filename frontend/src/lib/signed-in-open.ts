'use client';

import type { MouseEvent } from 'react';
import { useAuthStore } from '@/stores/auth-store';

// ダンの画面（成果物など）を別のタブで開く時、そのタブでもログインしたまま開く
// （10-27 本人「ログイン機能を付けるのは良いが、ログインは僕にやらせないで、ダンから開いた段階で自動的に」）。
// 今の画面のログインで使い捨ての入館証（app/enter/route.ts。スマホのアプリと同じ入口）をもらい、
// 新しいタブはそれで入る。別のブラウザに開かれても入れる。入館証がもらえない時は元の住所をそのまま開く。

const TIMEOUT_MS = 15000;

// ダンの入口の中の道だけを扱う。外のサイトには入館証を渡さない。
function ownPath(href: string): string | null {
  try {
    const url = new URL(href, window.location.href);
    if (url.origin !== window.location.origin || url.pathname.startsWith('/enter')) return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}

async function ticketUrl(to: string): Promise<string | null> {
  let access = localStorage.getItem('done-token') || useAuthStore.getState().token;
  let refresh: string | null = null;
  // 更新用の記録（Cookie）があれば新しい組を作り、新しいタブにも30日もつログインを入れる。
  const pair = await fetch('/api/v1/chat/refresh', {
    method: 'POST', credentials: 'include', signal: AbortSignal.timeout(TIMEOUT_MS),
  }).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (typeof pair?.access_token === 'string' && pair.access_token) {
    access = pair.access_token;
    refresh = typeof pair.refresh_token === 'string' ? pair.refresh_token : null;
    localStorage.setItem('done-token', pair.access_token);
    useAuthStore.getState().setToken(pair.access_token);
  }
  if (!access) return null;
  const result = await fetch('/enter', {
    method: 'POST', signal: AbortSignal.timeout(TIMEOUT_MS),
    headers: { Authorization: `Bearer ${access}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ to, refresh_token: refresh || undefined }),
  }).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (typeof result?.url !== 'string') return null;
  try {
    const hash = new URL(result.url).hash;
    // 入館証はこの入口の Next の中にあるので、今の画面と同じ入口で引き換える。
    return /^#[\w-]{43}$/.test(hash) ? `${window.location.origin}/enter${hash}` : null;
  } catch {
    return null;
  }
}

/** 別のタブで開くリンクの onClick。ダンの画面の住所なら入館証を付けて開く。 */
export function openSignedIn(event: MouseEvent<HTMLAnchorElement>, href: string | null | undefined): void {
  if (!href || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const to = ownPath(href);
  if (!to) return;
  // 押した瞬間にタブを開いておく（待った後に開くとポップアップとして止められる）。開けなければリンクのまま開く。
  const tab = window.open('about:blank', '_blank');
  if (!tab) return;
  event.preventDefault();
  tab.opener = null;
  void ticketUrl(to).then(url => {
    tab.location.replace(url || new URL(to, window.location.href).toString());
  });
}
