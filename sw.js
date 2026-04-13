const CACHE_NAME = 'alya-reader-v1';
const ASSETS_TO_CACHE = [
    './reader.html',
    './reader.css',
    './reader.js',
    './chapters_data.json'
];

// Установка воркера и кеширование статики
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
    self.skipWaiting();
});

// Очистка старых кешей
self.addEventListener('activate', (event) => {
    event.waitUntil(caches.keys().then(keys => Promise.all(
        keys.map(key => (key !== CACHE_NAME ? caches.delete(key) : null))
    )));
    self.clients.claim();
});

// Перехват запросов (Network First, fallback to Cache)
self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
