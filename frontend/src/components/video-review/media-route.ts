// 家の中では、エディターの映像を家の Mac mini から直接読む（2026-11-18）。
//
// dan.paina.info から開いたエディターは、映像を1回読むたびにインターネット（Cloudflare）を回って
// 家の Mac mini へ来る。家の中にいる時だけ、映像の読み込みを家の中の直通（https://dan-home.paina.info、
// scripts/lan_media_server.py）へ向ける。外にいる時・直通が使えない時は、今までどおり同じ住所から読む。
// 本人が切り替える操作は無い。
//
// - 家の中かどうかは、まずサーバーに聞く（/home-route: 端末のインターネット側の住所が家と同じか）。
//   家だと言われた時だけ直通に挨拶（/lan/ping）し、返事があれば使い始める。外の端末は直通を試さない。
// - Chrome は、公開のページから家の中の機械へ読みに行く時に、最初の1回だけ「許可」を聞く。
//   許可を待つ間は今までの道で読み、許可されたらその時から直通に切り替わる。
// - 直通が途中で切れたら（家を出た・Mac が直通を止めた）、その読み込みは今までの道で読み直し、
//   以後も今までの道に戻す。少し後にもう一度確かめる。
// - 住所の形は変えない（素材の印・取り込みの名前は今までどおり）。読みに行く瞬間だけ住所を差し替える。

type State = 'unknown' | 'home' | 'away';

let state: State = 'unknown';
let base: string | null = null;
let started = false;
let readyResolve: (() => void) | null = null;
const readyPromise = new Promise<void>((r) => { readyResolve = r; });
const listeners = new Set<(home: boolean) => void>();
let retryTimer: number | null = null;

// 直通へ回す住所（ログイン無しで配っている、範囲読みの映像だけ。scripts/lan_media_server.py と同じ）
const ROUTED_PATHS = ['/api/v1/production-assets/media', '/api/v1/video-review/media'];

function setState(next: State, nextBase: string | null) {
  const was = state === 'home';
  state = next;
  base = next === 'home' ? nextBase : null;
  if (readyResolve && next !== 'unknown') { readyResolve(); readyResolve = null; }
  if (was !== (state === 'home')) for (const fn of listeners) fn(state === 'home');
  try { (window as unknown as { __mediaRoute?: unknown }).__mediaRoute = { state, base }; } catch { /* noop */ }
}

function forced(): string | null {
  try { return new URLSearchParams(window.location.search).get('homeroute'); } catch { return null; }
}

async function check(): Promise<void> {
  if (retryTimer !== null) { window.clearTimeout(retryTimer); retryTimer = null; }
  const f = forced();
  if (f === '0') { setState('away', null); return; }
  let want: string | null = null;
  try {
    const res = await fetch('/api/v1/production-assets/home-route', { cache: 'no-store', signal: AbortSignal.timeout(4000) });
    if (res.ok) want = ((await res.json()) as { base?: string | null }).base || null;
  } catch { /* サーバーに聞けなければ今までの道 */ }
  if (!want && f === '1') want = 'https://dan-home.paina.info';
  if (!want) { setState('away', null); return; }
  // 挨拶の返事を待つ。Chrome が「許可」を聞いている間は返事が来ないので、その間は今までの道で読む
  // （待ちを打ち切らない: 打ち切ると許可の問いも消える）。返事が来たらその時から直通にする。
  let settled = false;
  const fallback = window.setTimeout(() => { if (!settled && state === 'unknown') setState('away', null); }, 2500);
  try {
    const res = await fetch(`${want}/lan/ping`, { cache: 'no-store', signal: AbortSignal.timeout(120_000) });
    settled = true;
    if (res.ok) { setState('home', want); return; }
  } catch { /* 家の中の直通に届かない */ }
  finally { window.clearTimeout(fallback); }
  settled = true;
  setState('away', null);
}

function scheduleRecheck(ms: number) {
  if (retryTimer !== null) return;
  retryTimer = window.setTimeout(() => { retryTimer = null; void check(); }, ms);
}

/** 家の中かどうかを確かめ始める（何度呼んでも1回だけ） */
export function startMediaRoute(): void {
  if (started || typeof window === 'undefined') return;
  started = true;
  const h = window.location.hostname;
  // Mac mini の上で直接開いている時は、もう直通と同じ速さ
  if ((h === 'localhost' || h === '127.0.0.1' || h === '[::1]') && forced() !== '1') { setState('away', null); return; }
  void check();
  // 端末の回線が変わった（Wi‑Fi に入った・出た）: 確かめ直す
  window.addEventListener('online', () => scheduleRecheck(1000));
}

/** 家の中かどうかの答えが出るまで待つ（最長2.5秒ほど。答えが出なければ今までの道） */
export function mediaRouteReady(): Promise<void> {
  startMediaRoute();
  return readyPromise;
}

export function homeRouteActive(): boolean { return state === 'home' && !!base; }

export function onMediaRouteChange(fn: (home: boolean) => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** 読みに行く住所: 家の中なら直通、それ以外は渡された住所のまま */
export function routedUrl(url: string): string {
  if (!base || !url) return url;
  if (url.startsWith('blob:') || url.startsWith('data:')) return url;
  let u: URL;
  try { u = new URL(url, window.location.href); } catch { return url; }
  if (u.origin !== window.location.origin) return url;
  if (!ROUTED_PATHS.includes(u.pathname)) return url;
  return base + u.pathname + u.search;
}

/** 直通に届かなかった: 今までの道に戻し、少し後に確かめ直す */
function directFailed() {
  if (state !== 'home') return;
  setState('away', null);
  scheduleRecheck(30_000);
}

/** 映像の範囲読み。家の中なら直通から読み、届かなければ今までの道で読み直す */
export async function mediaFetch(url: string, init?: RequestInit): Promise<Response> {
  startMediaRoute();
  const direct = routedUrl(url);
  if (direct !== url) {
    try {
      return await fetch(direct, init);
    } catch (e) {
      if (init?.signal?.aborted) throw e;
      directFailed();
    }
  }
  return fetch(url, init);
}

/** <video>・<audio> に住所を渡す。直通の時は絵を描いても汚れないよう crossOrigin を付け、
 *  直通で読めなかったら今までの道の住所に差し替える */
export function setMediaElementSrc(el: HTMLMediaElement, url: string): void {
  startMediaRoute();
  const direct = routedUrl(url);
  if (direct !== url) {
    el.crossOrigin = 'anonymous';
    const onError = () => {
      el.removeEventListener('error', onError);
      if (el.src !== direct) return;
      directFailed();
      el.src = url;
    };
    el.addEventListener('error', onError);
  }
  el.src = direct;
}
