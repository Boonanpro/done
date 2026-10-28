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
