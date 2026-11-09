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
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  let path = '';
  try { path = new URL(request.url).pathname; } catch { return; }
  if (request.destination === 'video' || request.destination === 'audio' || request.headers.has('range') || MEDIA_PATH.test(path)) {
    event.stopImmediatePropagation();
  }
});

// 前の版が貯めた動画・音声を消す（1本で数百MB、32本まで残る決まりだった）
self.addEventListener('activate', (event) => {
  event.waitUntil(Promise.all(['static-video-assets', 'static-audio-assets'].map((name) => caches.delete(name))));
});
