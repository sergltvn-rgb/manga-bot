// Safe service worker:
// - activates immediately
// - clears stale caches once
// - does NOT force navigation or unregister (avoids reload loops in Telegram WebView)

self.addEventListener('install', () => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.map((key) => caches.delete(key)));
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    if (event.request.url.includes('/api/')) return;

    // Network-first strategy with optional cache fallback if network is unavailable.
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
