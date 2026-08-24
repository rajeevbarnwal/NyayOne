import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

type WorkerHandler = (event: Record<string, unknown>) => void;

function bootWorker(
  fetchImpl = vi.fn(async (_request: unknown) => response()),
  cacheKeys = ['nyayone-shell-v1'],
) {
  const source = readFileSync(join(process.cwd(), 'public/sw.js'), 'utf8');
  const handlers = new Map<string, WorkerHandler>();
  const addAll = vi.fn(async () => undefined);
  const put = vi.fn(async (_request: Request, _response: unknown) => undefined);
  const fallback = response();
  const cacheMatch = vi.fn(async (key: unknown) => key === '/index.html' ? fallback : undefined);
  const match = vi.fn(async (key: unknown) => key === '/index.html' ? fallback : undefined);
  const cache = { addAll, put, match: cacheMatch };
  const caches = {
    open: vi.fn(async () => cache),
    keys: vi.fn(async () => cacheKeys),
    delete: vi.fn(async (_key: string) => true),
    match,
  };
  const self = {
    location: { origin: 'https://app.test' },
    addEventListener: (name: string, handler: WorkerHandler) => handlers.set(name, handler),
    skipWaiting: vi.fn(),
    clients: { claim: vi.fn() },
  };
  runInNewContext(source, {
    Request,
    URL,
    Promise,
    caches,
    fetch: fetchImpl,
    self,
  });
  return { handlers, addAll, put, cacheMatch, match, fetchImpl, caches };
}

function response(headers: Record<string, string> = {}) {
  const value = {
    ok: true,
    type: 'basic',
    headers: new Headers(headers),
    clone: vi.fn(() => value),
  };
  return value;
}

async function dispatchFetch(
  worker: ReturnType<typeof bootWorker>,
  request: { url: string; method: string; mode: string; destination?: string },
) {
  let responsePromise: Promise<unknown> | undefined;
  worker.handlers.get('fetch')?.({
    request,
    respondWith: (promise: Promise<unknown>) => { responsePromise = promise; },
  });
  return responsePromise ? responsePromise : undefined;
}

describe('production service-worker privacy boundary', () => {
  it('has no build-time switch that can remove the shipped service worker', () => {
    const registrationSource = readFileSync(join(process.cwd(), 'src/lib/pwa.ts'), 'utf8');
    expect(registrationSource).not.toContain('VITE_DISABLE_SERVICE_WORKER');
    expect(registrationSource).toContain('if (!isProd) return');
    expect(registrationSource).toContain("navigator.serviceWorker.register('/sw.js')");
  });

  it('pre-caches only an exact credential-free public shell file, never a route alias', async () => {
    const worker = bootWorker();
    let pending: Promise<unknown> | undefined;
    worker.handlers.get('install')?.({
      waitUntil: (promise: Promise<unknown>) => { pending = promise; },
    });
    await pending;
    expect(worker.addAll).not.toHaveBeenCalled();
    expect(worker.fetchImpl).toHaveBeenCalledTimes(1);
    const shellRequest = worker.fetchImpl.mock.calls[0]?.[0] as Request;
    expect(shellRequest).toBeInstanceOf(Request);
    expect(new URL(shellRequest.url).pathname).toBe('/index.html');
    expect(shellRequest.credentials).toBe('omit');
    expect(worker.put).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['private cache control', { 'Cache-Control': 'private, max-age=300' }],
    ['no-store cache control', { 'Cache-Control': 'no-store' }],
    ['cookie-varying response', { Vary: 'Cookie' }],
  ])('does not install a %s shell response', async (_label, headers) => {
    const worker = bootWorker(vi.fn(async (_request: unknown) => response(headers)));
    let pending: Promise<unknown> | undefined;
    worker.handlers.get('install')?.({
      waitUntil: (promise: Promise<unknown>) => { pending = promise; },
    });

    await pending;

    expect(worker.fetchImpl).toHaveBeenCalledTimes(1);
    expect(worker.addAll).not.toHaveBeenCalled();
    expect(worker.put).not.toHaveBeenCalled();
  });

  it('retires only owned legacy/current-version caches and preserves unrelated caches', async () => {
    const worker = bootWorker(undefined, [
      'nyayone-shell-v1',
      'nyayone-shell-v0',
      'ls-shell-v1',
      'legalsaathi-shell-v9',
      'another-app-shell-v1',
    ]);
    let pending: Promise<unknown> | undefined;
    worker.handlers.get('activate')?.({
      waitUntil: (promise: Promise<unknown>) => { pending = promise; },
    });
    await pending;
    expect(worker.caches.delete.mock.calls.map(([key]) => key)).toEqual([
      'nyayone-shell-v0',
      'ls-shell-v1',
      'legalsaathi-shell-v9',
    ]);
  });

  it('never writes a private navigation route and uses the shell only as an offline fallback', async () => {
    const online = bootWorker();
    await dispatchFetch(online, {
      url: 'https://app.test/s-18', method: 'GET', mode: 'navigate', destination: 'document',
    });
    expect(online.fetchImpl).toHaveBeenCalledTimes(1);
    expect(online.put).not.toHaveBeenCalled();

    const offline = bootWorker(vi.fn(async (_request: unknown) => { throw new TypeError('offline'); }));
    await expect(dispatchFetch(offline, {
      url: 'https://app.test/s-19', method: 'GET', mode: 'navigate', destination: 'document',
    })).resolves.toBeTruthy();
    expect(offline.cacheMatch).toHaveBeenCalledWith('/index.html');
    expect(offline.match).not.toHaveBeenCalled();
    expect(offline.put).not.toHaveBeenCalled();
  });

  it('never reads an offline shell from an unrelated or retired cache', async () => {
    const worker = bootWorker(vi.fn(async (_request: unknown) => { throw new TypeError('offline'); }));
    worker.match.mockResolvedValue(response());

    await expect(dispatchFetch(worker, {
      url: 'https://app.test/s-19', method: 'GET', mode: 'navigate', destination: 'document',
    })).resolves.toBeTruthy();

    expect(worker.match).not.toHaveBeenCalled();
    expect(worker.cacheMatch).toHaveBeenCalledWith('/index.html');
  });

  it('caches only successful same-origin immutable build assets', async () => {
    const worker = bootWorker();
    const asset = {
      url: 'https://app.test/assets/app.a1b2c3.js', method: 'GET', mode: 'cors', destination: 'script',
    };
    await dispatchFetch(worker, asset);
    expect(worker.put).toHaveBeenCalledTimes(1);
    const cacheKey = worker.put.mock.calls[0]?.[0] as Request;
    expect(cacheKey.url).toBe(asset.url);
    expect(cacheKey.credentials).toBe('omit');

    for (const request of [
      { url: 'https://app.test/api/v1/student/profile', method: 'GET', mode: 'cors' },
      { url: 'https://app.test/assets/app.js?token=forbidden', method: 'GET', mode: 'cors', destination: 'script' },
      { url: 'https://other.test/assets/app.js', method: 'GET', mode: 'cors', destination: 'script' },
      { url: 'https://app.test/s-85', method: 'GET', mode: 'cors', destination: 'document' },
    ]) {
      const isolated = bootWorker();
      await dispatchFetch(isolated, request);
      expect(isolated.put).not.toHaveBeenCalled();
    }
  });

  it('fetches a cache candidate without ambient credentials', async () => {
    const fetchWithoutCredentials = vi.fn(async (request: unknown) => {
      expect(request).toBeInstanceOf(Request);
      expect((request as Request).credentials).toBe('omit');
      return response();
    });
    const worker = bootWorker(fetchWithoutCredentials);

    await dispatchFetch(worker, {
      url: 'https://app.test/assets/app.a1b2c3.js',
      method: 'GET',
      mode: 'cors',
      destination: 'script',
    });

    expect(fetchWithoutCredentials).toHaveBeenCalledTimes(1);
    expect(worker.put).toHaveBeenCalledTimes(1);
  });

  it('never serves an asset match from an unrelated or retired cache', async () => {
    const networkResponse = response();
    const fetchAsset = vi.fn(async (_request: unknown) => networkResponse);
    const worker = bootWorker(fetchAsset);
    worker.match.mockResolvedValue(response());
    worker.cacheMatch.mockResolvedValue(undefined);

    await expect(dispatchFetch(worker, {
      url: 'https://app.test/assets/app.a1b2c3.js',
      method: 'GET',
      mode: 'cors',
      destination: 'script',
    })).resolves.toBe(networkResponse);

    expect(worker.match).not.toHaveBeenCalled();
    expect(worker.cacheMatch).toHaveBeenCalledTimes(1);
    expect(fetchAsset).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['private cache control', { 'Cache-Control': 'private, max-age=300' }],
    ['no-store cache control', { 'Cache-Control': 'no-store' }],
    ['cookie-varying response', { Vary: 'Accept-Encoding, Cookie' }],
    ['authorization-varying response', { Vary: 'Authorization' }],
    ['wildcard-varying response', { Vary: '*' }],
  ])('does not cache a %s', async (_label, headers) => {
    const worker = bootWorker(vi.fn(async (_request: unknown) => response(headers)));

    await dispatchFetch(worker, {
      url: 'https://app.test/assets/app.a1b2c3.js',
      method: 'GET',
      mode: 'cors',
      destination: 'script',
    });

    expect(worker.put).not.toHaveBeenCalled();
  });
});
