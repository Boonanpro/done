// Source for next-pwa's generated worker. Keep push handling in source control:
// editing public/sw.js loses it on the next build.
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data?.text() }; }
  let url = new URL('/collab', self.location.origin);
  try {
    const candidate = new URL(data.url || '/collab', self.location.origin);
    if (candidate.origin === self.location.origin) url = candidate;
  } catch { /* Use the local chat list for malformed payloads. */ }
  event.waitUntil(self.registration.showNotification(data.title || 'チャット', {
    body: data.body || '新しいメッセージが届きました',
    icon: '/icon-192x192.png',
    badge: '/icon-192x192.png',
    tag: `chat:${url.pathname}`,
    renotify: true,
    vibrate: [200, 100, 200],
    data: { url: url.href },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  let url;
  try { url = new URL(event.notification.data?.url || '/collab', self.location.origin); } catch { return; }
  if (url.origin !== self.location.origin) return;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const existing = windows.find((client) => client.url === url.href);
    if (existing) {
      existing.postMessage({ type: 'collab-notification-open' });
      return existing.focus();
    }
    return self.clients.openWindow(url.href);
  })());
});

// 動画・音声は Service Worker を通さず、ブラウザがそのままネットから読む。next-pwa の決まりは .mp4 を
// 丸ごと Cache Storage に貯め（CacheFirst）、次からは貯めた物を切り出して渡す。数百MBの動画では、
// 貯めた後の再生がネットに取りに行かないまま失敗し、チャットに「メディアを読み込めませんでした」と
// 出ていた（2026-11-09、667MBの特典動画）。ここは workbox の受け口より先に登録されるので、
// 止めると workbox は応答せず、ブラウザが普段どおり Range つきで読む。
const MEDIA_PATH = /\.(?:mp4|m4v|mov|webm|mkv|avi|mp3|m4a|wav|ogg)$/i;
// ダンの問い合わせ（/api/）と、成果物タブが映す開発版の部品（/_live/）も通さない。workbox の決まりは、問い合わせの答えを
// 毎回 Cache Storage に書き（16件で入れ替え）、/_live の部品50個を32個の枠で入れ替え続けていた。その書き込みと消す記録で
// このサイトの端末の置き場所が重くなり、本人の Chrome では開発室が端末の控えを読むだけで15秒待っていた（2026-11-21）。
// どちらもブラウザの普段の控え（Cache-Control・ETag）がそのまま効く
const PASS_PATH = /^\/(?:api|_live)\//;
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  let path = '';
  let host = '';
  try { const u = new URL(request.url); path = u.pathname; host = u.hostname; } catch { return; }
  // 家の中の直通（dan-home.paina.info。media-route.ts）も通さない。Service Worker を通して家の中の機械へ
  // 読みに行くと、すぐに失敗した（ページから直接読む時は Chrome の許可の問いが出る。2026-11-18）
  if (host === 'dan-home.paina.info'
      || request.destination === 'video' || request.destination === 'audio' || request.headers.has('range') || MEDIA_PATH.test(path)
      || (host === self.location.hostname && PASS_PATH.test(path))) {
    event.stopImmediatePropagation();
  }
});

// 前の版が貯めた動画・音声を消す（1本で数百MB、32本まで残る決まりだった）。
// 前の版が貯めた問い合わせの答え（apis）と、/_live の部品を含む js の入れ替え用（static-js-assets）も消す
self.addEventListener('activate', (event) => {
  event.waitUntil(Promise.all(['static-video-assets', 'static-audio-assets', 'apis', 'static-js-assets'].map((name) => caches.delete(name))));
});
