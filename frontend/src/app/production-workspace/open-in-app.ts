// Android の Chrome でエディターを開いた時は、ダンのアプリの中で開き直す（2026-11-18 本人「スマホのブラウザの上の帯を
// 何も意識しなくても無い状態にしたい」）。Chrome の中では、人が触るまで全画面にできず、端からなぞると全画面が解けるため、
// 帯の無い画面はアプリの中（題・時計・下のボタンの帯を隠した全画面）でしか作れない。
//
// intent:// の住所へ移ると、アプリが入っていればアプリが同じ住所（https://…/production-workspace?…）を受け取って開く
// （mobile/app.json の intentFilters）。入っていなければ Chrome が browser_fallback_url（app=0 を付けた同じ住所）へ戻り、
// そのままブラウザで開く。

const SKIP_PARAM = 'app';

export function appIntentUrl(href: string): string | null {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return null;
  const ua = navigator.userAgent || '';
  if (!/Android/i.test(ua)) return null;
  // アプリの中の画面（react-native-webview）・ほかのアプリの中の画面からは移らない
  if (/; wv\)/.test(ua) || (window as unknown as { ReactNativeWebView?: unknown }).ReactNativeWebView) return null;
  const u = new URL(href);
  if (u.searchParams.get('phone') === '1' || u.searchParams.get(SKIP_PARAM) === '0') return null;
  if (!u.searchParams.get('room_id')) return null;
  if (window.matchMedia?.('(display-mode: standalone)').matches) return null;
  const fallback = new URL(u.toString());
  fallback.searchParams.set(SKIP_PARAM, '0');
  return `intent://${u.host}${u.pathname}${u.search}#Intent;scheme=${u.protocol.replace(':', '')};package=app.done.dan;S.browser_fallback_url=${encodeURIComponent(fallback.toString())};end`;
}
