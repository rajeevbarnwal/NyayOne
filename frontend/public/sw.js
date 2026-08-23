/* LegalSaathi public-shell service worker (SAATHI-346 / NYAY-5).
   Private route aliases and API traffic are always network-only. Only the
   fixed public shell fallback and same-origin build assets enter CacheStorage. */
const CACHE = 'ls-shell-v1';
const SHELL = ['/index.html'];
const PUBLIC_ASSET_DESTINATIONS = new Set(['font', 'image', 'script', 'style']);

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
  if (req.method !== 'GET') return;
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  // Route navigations are never cache keys. Network failure may render the
  // public shell, whose live session guard still resolves authority server-side.
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/index.html')));
    return;
  }

  const isPublicBuildAsset = url.pathname.startsWith('/assets/')
    && url.search === ''
    && url.username === ''
    && url.password === ''
    && PUBLIC_ASSET_DESTINATIONS.has(req.destination)
    && !(req.headers && req.headers.has('authorization'));
  if (!isPublicBuildAsset) return;

  event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
    if (res.ok && res.type === 'basic') {
      const cacheKey = new Request(url.href, { method: 'GET', credentials: 'omit' });
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(cacheKey, copy)).catch(() => {});
    }
    return res;
  })));
});
