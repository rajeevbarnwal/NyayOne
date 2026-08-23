/* NyayOne public-shell service worker (SAATHI-346 / NYAY-5 / NYAY-18).
   Private route aliases and API traffic are always network-only. Only the
   fixed public shell fallback and same-origin build assets enter CacheStorage. */
const CACHE = 'nyayone-shell-v1';
const OWNED_CACHE_PREFIXES = ['nyayone-shell-', 'ls-shell-', 'legalsaathi-shell-'];
const CACHE_PURGE_BATCH_SIZE = 256;
const SHELL = ['/index.html'];
const PUBLIC_ASSET_DESTINATIONS = new Set(['font', 'image', 'script', 'style']);

function responseIsPublicCacheable(response) {
  if (!response.ok || response.type !== 'basic') return false;
  const cacheControl = response.headers.get('cache-control') || '';
  if (/(?:^|,)\s*(?:private|no-store|no-cache)\b/iu.test(cacheControl)) return false;
  const vary = (response.headers.get('vary') || '')
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  if (vary.some((value) => value === '*' || value === 'cookie' || value === 'authorization')) {
    return false;
  }
  // Browsers normally hide Set-Cookie from script, but reject it if an
  // implementation exposes the header rather than relying on that behavior.
  return !response.headers.has('set-cookie');
}

async function retireOwnedCaches(keys) {
  const retired = keys.filter((key) => key !== CACHE
    && OWNED_CACHE_PREFIXES.some((prefix) => key.startsWith(prefix)));
  for (let index = 0; index < retired.length; index += CACHE_PURGE_BATCH_SIZE) {
    await Promise.all(retired.slice(index, index + CACHE_PURGE_BATCH_SIZE)
      .map((key) => caches.delete(key)));
  }
}

async function installPublicShell() {
  const cache = await caches.open(CACHE);
  for (const shellPath of SHELL) {
    const request = new Request(new URL(shellPath, self.location.origin).href, {
      method: 'GET',
      credentials: 'omit',
      cache: 'no-store',
      mode: 'same-origin',
    });
    const response = await fetch(request);
    if (!responseIsPublicCacheable(response)) continue;
    await cache.put(request, response.clone());
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(installPublicShell().catch(() => undefined));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(retireOwnedCaches)
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
    event.respondWith(fetch(req).catch(async () => {
      const cache = await caches.open(CACHE);
      return cache.match('/index.html');
    }));
    return;
  }

  const isPublicBuildAsset = url.pathname.startsWith('/assets/')
    && url.search === ''
    && url.username === ''
    && url.password === ''
    && PUBLIC_ASSET_DESTINATIONS.has(req.destination)
    && !(req.headers && req.headers.has('authorization'));
  if (!isPublicBuildAsset) return;

  // Fetch the credential-free request itself. Merely using an omit-credentials
  // cache key after fetching `req` would still let a cookie-varying body enter
  // the shared shell cache.
  const cacheKey = new Request(url.href, {
    method: 'GET',
    credentials: 'omit',
    mode: 'same-origin',
  });
  event.respondWith(caches.open(CACHE).then(async (cache) => {
    const hit = await cache.match(cacheKey);
    if (hit) return hit;
    const response = await fetch(cacheKey);
    if (responseIsPublicCacheable(response)) {
      await cache.put(cacheKey, response.clone());
    }
    return response;
  }));
});
