// Self-unregistering service worker
// Replaces the old Workbox PWA cache that was breaking dev mode
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // Clear all caches
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.map((name) => caches.delete(name)))
    ).then(() => self.clients.claim())
    .then(() => self.registration.unregister())
  );
});
