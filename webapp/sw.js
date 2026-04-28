const swUrl = new URL(self.location.href);
const SW_REV = swUrl.searchParams.get('rev') || '20260428-stability-1';
const CACHE_PREFIX = 'alya-reader-runtime';
const RUNTIME_CACHE = `${CACHE_PREFIX}-${SW_REV}`;

self.addEventListener('install', () => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(
            keys
                .filter((key) => key.startsWith(CACHE_PREFIX) && key !== RUNTIME_CACHE)
                .map((key) => caches.delete(key))
        );
        await self.clients.claim();
    })());
});

self.addEventListener('message', (event) => {
    const data = event.data || {};
    if (data.type === 'SKIP_WAITING') {
        self.skipWaiting();
        return;
    }

    if (data.type === 'CACHE_CHAPTER_URLS' && Array.isArray(data.urls)) {
        event.waitUntil((async () => {
            const cache = await caches.open(RUNTIME_CACHE);
            for (const rawUrl of data.urls) {
                const url = String(rawUrl || '').trim();
                if (!/^https?:\/\//i.test(url)) continue;
                // Skip cross-origin hosts without CORS — they only spam console.
                // Allow only same-origin + явно доверенный api.telegra.ph.
                try {
                    const u = new URL(url);
                    const isSameOrigin = u.origin === self.location.origin;
                    const isTelegraphApi = u.hostname === 'api.telegra.ph';
                    if (!isSameOrigin && !isTelegraphApi) continue;
                } catch (e) { continue; }
                try {
                    const response = await fetch(url, { cache: 'no-store' });
                    if (response && response.ok) {
                        await cache.put(url, response.clone());
                    }
                } catch (e) {}
            }
        })());
    }
});

self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    if (event.request.url.includes('/api/')) return;

    event.respondWith((async () => {
        const cache = await caches.open(RUNTIME_CACHE);
        try {
            const response = await fetch(event.request);
            if (response && response.ok) {
                await cache.put(event.request, response.clone());
            }
            return response;
        } catch (e) {
            const cached = await cache.match(event.request);
            if (cached) return cached;
            throw e;
        }
    })());
});
