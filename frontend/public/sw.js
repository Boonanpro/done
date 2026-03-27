// Service Worker for Push Notifications
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Handle push notifications
self.addEventListener('push', (event) => {
  if (!event.data) return;

  try {
    const data = event.data.json();
    const options = {
      body: data.body || '',
      icon: data.icon || '/icon-192x192.png',
      badge: '/icon-192x192.png',
      data: { url: data.url || '/' },
      vibrate: [200, 100, 200],
      tag: 'collab-message',
      renotify: true,
    };

    event.waitUntil(
      self.registration.showNotification(data.title || 'Done', options).then(() => {
        // Update badge count
        if (navigator.setAppBadge) {
          // Increment badge
          return self.registration.getNotifications().then((notifications) => {
            navigator.setAppBadge(notifications.length + 1);
          });
        }
      })
    );
  } catch (e) {
    console.error('Push event error:', e);
  }
});

// Handle notification click - clear badge
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (navigator.clearAppBadge) {
    navigator.clearAppBadge();
  }

  const url = event.notification.data?.url || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      // Focus existing window if open
      for (const client of clients) {
        if (client.url.includes(self.registration.scope) && 'focus' in client) {
          return client.focus();
        }
      }
      // Open new window
      return self.clients.openWindow(url);
    })
  );
});
