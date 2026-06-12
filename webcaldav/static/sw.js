// WebCalDav Service Worker.
//
// Purpose is narrow: it is the surface through which the page shows reminder
// notifications (registration.showNotification) so the OS routes them to the
// system notification center and they survive the tab losing focus, and it
// handles clicks on those notifications by focusing the WebCalDav tab.
//
// It deliberately does NOT cache assets or intercept fetches — keeping it inert
// avoids stale-asset bugs, and the app needs no offline mode.

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of all) {
      if ('focus' in client) return client.focus();
    }
    if (self.clients.openWindow) return self.clients.openWindow('/');
  })());
});
