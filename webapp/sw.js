// Cache reset worker:
// - force-activate
// - delete all old caches
// - unregister itself
// This is needed to recover users stuck with stale Telegram WebView cache.

self.addEventListener('install', () => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.map((key) => caches.delete(key)));
        await self.clients.claim();
        await self.registration.unregister();

        const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const client of clients) {
            try {
                await client.navigate(client.url);
            } catch (_) {}
        }
    })());
});

self.addEventListener('fetch', () => {
    // No-op: let network handle requests after unregister.
});
