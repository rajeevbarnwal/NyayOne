import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

type WorkerHandler = (event: Record<string, unknown>) => void;

function bootWorker(fetchImpl = vi.fn(async () => response())) {
  const source = readFileSync(join(process.cwd(), 'public/sw.js'), 'utf8');
  const handlers = new Map<string, WorkerHandler>();
  const addAll = vi.fn(async () => undefined);
  const put = vi.fn(async (_request: Request, _response: unknown) => undefined);
  const fallback = response();
  const match = vi.fn(async (key: unknown) => key === '/index.html' ? fallback : undefined);
  const cache = { addAll, put };
  const caches = {
    open: vi.fn(async () => cache),
    keys: vi.fn(async () => ['ls-shell-v1']),
    delete: vi.fn(async () => true),
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
  return { handlers, addAll, put, match, fetchImpl };
}

function response() {
  const value = {
    ok: true,
    type: 'basic',
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

  it('pre-caches only an exact public shell file, never a route alias', async () => {
    const worker = bootWorker();
    let pending: Promise<unknown> | undefined;
    worker.handlers.get('install')?.({
      waitUntil: (promise: Promise<unknown>) => { pending = promise; },
    });
    await pending;
    expect(worker.addAll).toHaveBeenCalledWith(['/index.html']);
  });

  it('never writes a private navigation route and uses the shell only as an offline fallback', async () => {
    const online = bootWorker();
    await dispatchFetch(online, {
      url: 'https://app.test/s-18', method: 'GET', mode: 'navigate', destination: 'document',
    });
    expect(online.fetchImpl).toHaveBeenCalledTimes(1);
    expect(online.put).not.toHaveBeenCalled();

    const offline = bootWorker(vi.fn(async () => { throw new TypeError('offline'); }));
    await expect(dispatchFetch(offline, {
      url: 'https://app.test/s-19', method: 'GET', mode: 'navigate', destination: 'document',
    })).resolves.toBeTruthy();
    expect(offline.match).toHaveBeenCalledWith('/index.html');
    expect(offline.put).not.toHaveBeenCalled();
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
});
