// Service Worker for Push Notifications
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// NOTE: No `fetch` handler is registered on purpose.
// A pass-through `fetch` handler (event.respondWith(fetch(event.request)))
// routes every navigation/asset request through the SW, and returning a
// redirected response to a navigation request makes the browser throw,
// bricking the whole origin until the SW is unregistered. A `fetch` handler
// has not been required for PWA installability since Chrome 89, so this SW
// only handles `push` / `notificationclick`.

// Handle push notifications
self.addEventListener('push', (event) => {
  if (!event.data) return;

  try {
    const data = event.data.json();
    const url = data.url || '/';
    const options = {
      body: data.body || '',
      icon: data.icon || '/icon-192x192.png',
      badge: '/icon-192x192.png',
      data: { url },
      vibrate: [200, 100, 200],
      tag: data.tag || url,
      renotify: true,
    };

    event.waitUntil(
      self.registration.showNotification(data.title || 'Done', options).then(() => {
        if (navigator.setAppBadge) {
          return self.registration.getNotifications().then((notifications) => {
            navigator.setAppBadge(notifications.length);
          });
        }
      })
    );
  } catch (e) {
    console.error('Push event error:', e);
  }
});

async function syncBadgeToVisibleNotifications() {
  if (!navigator.setAppBadge || !navigator.clearAppBadge) return;
  const notifications = await self.registration.getNotifications();
  if (notifications.length > 0) {
    await navigator.setAppBadge(notifications.length);
  } else {
    await navigator.clearAppBadge();
  }
}

// Handle notification click: open the target chat/room and decrement only that notification.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const url = event.notification.data?.url || '/';
  const targetUrl = new URL(url, self.registration.scope).href;

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (clients) => {
      await syncBadgeToVisibleNotifications();
      for (const client of clients) {
        if (client.url.includes(self.registration.scope) && 'focus' in client) {
          if ('navigate' in client) {
            await client.navigate(targetUrl);
          }
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
