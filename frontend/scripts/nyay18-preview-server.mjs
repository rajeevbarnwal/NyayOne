import { createReadStream } from 'node:fs';
import { readFile, stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import path from 'node:path';

const HOST = '127.0.0.1';
const HOSTILE_ASSET_PATH = '/assets/nyay18-private-canary.js';
const ARM_SHELL_PATH = '/__nyay18-gate/arm-shell';
const METRICS_PATH = '/__nyay18-gate/metrics';
const PRIVATE_SENTINEL = 'nyay18-private-sink-sentinel';
const PRIVATE_SHELL_SENTINEL = 'nyay18-private-shell-sentinel';

function requiredEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

const rootInput = requiredEnv('NYAY18_PREVIEW_ROOT');
if (!path.isAbsolute(rootInput)) throw new Error('NYAY18_PREVIEW_ROOT must be absolute');
const ROOT = path.resolve(rootInput);
const PORT = Number(requiredEnv('NYAY18_PREVIEW_PORT'));
if (!Number.isSafeInteger(PORT) || PORT < 1 || PORT > 65_535) {
  throw new Error('NYAY18_PREVIEW_PORT must be a valid TCP port');
}

const MIME = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.ico', 'image/x-icon'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.map', 'application/json; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.webmanifest', 'application/manifest+json; charset=utf-8'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
]);

const metrics = {
  hostileAssetCookieHeaders: 0,
  hostileAssetServerRequests: 0,
  hostileShellCookieHeaders: 0,
  hostileShellServerRequests: 0,
};
let hostileShellArmed = false;

function respond(response, status, headers, body, method = 'GET') {
  response.writeHead(status, { 'X-Content-Type-Options': 'nosniff', ...headers });
  if (method === 'HEAD') response.end();
  else response.end(body);
}

function safePathname(rawUrl) {
  const url = new URL(rawUrl ?? '/', `http://${HOST}`);
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    return null;
  }
  if (pathname.includes('\0')) return null;
  return pathname;
}

async function staticFile(pathname) {
  const requested = pathname === '/' ? '/index.html' : pathname;
  const candidate = path.resolve(ROOT, `.${requested}`);
  const relative = path.relative(ROOT, candidate);
  if (relative.startsWith('..') || path.isAbsolute(relative)) return null;
  try {
    const metadata = await stat(candidate);
    if (metadata.isFile()) return candidate;
  } catch {
    // Extensionless application routes use the production SPA entry point.
  }
  if (path.extname(pathname) !== '') return null;
  const fallback = path.resolve(ROOT, 'index.html');
  const fallbackMetadata = await stat(fallback);
  return fallbackMetadata.isFile() ? fallback : null;
}

const server = createServer(async (request, response) => {
  const method = request.method ?? 'GET';
  if (method !== 'GET' && method !== 'HEAD') {
    respond(response, 405, { Allow: 'GET, HEAD' }, 'Method Not Allowed', method);
    return;
  }
  const pathname = safePathname(request.url);
  if (pathname === null) {
    respond(response, 400, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Bad Request', method);
    return;
  }
  if (pathname === METRICS_PATH) {
    respond(response, 200, {
      'Cache-Control': 'no-store',
      'Content-Type': 'application/json; charset=utf-8',
    }, JSON.stringify(metrics), method);
    return;
  }
  if (pathname === ARM_SHELL_PATH) {
    hostileShellArmed = true;
    respond(response, 204, { 'Cache-Control': 'no-store' }, '', method);
    return;
  }
  if (pathname === '/index.html' && hostileShellArmed) {
    hostileShellArmed = false;
    metrics.hostileShellServerRequests += 1;
    if (request.headers.cookie) metrics.hostileShellCookieHeaders += 1;
    try {
      const shell = await readFile(path.resolve(ROOT, 'index.html'), 'utf8');
      respond(response, 200, {
        'Cache-Control': 'private, no-store',
        'Content-Type': 'text/html; charset=utf-8',
        Vary: 'Cookie',
      }, `${shell}\n<!-- ${PRIVATE_SHELL_SENTINEL} -->\n`, method);
    } catch {
      respond(response, 500, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Internal Error', method);
    }
    return;
  }
  if (pathname === HOSTILE_ASSET_PATH) {
    metrics.hostileAssetServerRequests += 1;
    if (request.headers.cookie) metrics.hostileAssetCookieHeaders += 1;
    respond(response, 200, {
      'Cache-Control': 'private, no-store',
      'Content-Type': 'text/javascript; charset=utf-8',
      Vary: 'Cookie',
    }, `globalThis.__nyay18HostileAssetExecuted = true; /* ${PRIVATE_SENTINEL} */`, method);
    return;
  }
  try {
    const filename = await staticFile(pathname);
    if (filename === null) {
      respond(response, 404, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Not Found', method);
      return;
    }
    const extension = path.extname(filename).toLowerCase();
    const cacheHeaders = extension === '.html'
      ? { 'Cache-Control': 'public, max-age=60' }
      : { 'Cache-Control': 'public, max-age=31536000, immutable' };
    response.writeHead(200, {
      ...cacheHeaders,
      'Content-Type': MIME.get(extension) ?? 'application/octet-stream',
      'X-Content-Type-Options': 'nosniff',
    });
    if (method === 'HEAD') response.end();
    else createReadStream(filename).on('error', () => response.destroy()).pipe(response);
  } catch {
    if (!response.headersSent) {
      respond(response, 500, { 'Content-Type': 'text/plain; charset=utf-8' }, 'Internal Error', method);
    } else {
      response.destroy();
    }
  }
});

server.listen(PORT, HOST);
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
