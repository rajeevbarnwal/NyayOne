/* LegalSaathi service worker skeleton (SAATHI-346).
   Cache-first for the app shell/assets; network-only for API calls so data is
   never served stale. Intentionally minimal — a foundation, not a full offline
   strategy. No external/network fetches are added by this worker. */
const CACHE = 'ls-shell-v1';
const SHELL = ['/', '/index.html'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  // Never cache API traffic (freshness matters for legal/exam data).
  if (url.pathname.startsWith('/api/')) return;
  if (req.method !== 'GET') return;
  event.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      return res;
    }).catch(() => caches.match('/index.html')))
  );
});
