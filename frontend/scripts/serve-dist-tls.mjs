/** Minimal loopback-only HTTPS server for a previously built Vite SPA.
 *
 * This is test infrastructure, not a production web server.  It exists so the
 * real browser gate exercises a Secure, SameSite cookie without weakening the
 * application to cross-scheme HTTP.  Every path is contained under DIST_DIR;
 * unknown application routes receive index.html for React Router.
 */
import { createServer } from 'node:https';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const HOST = process.env.TLS_SPA_HOST || '127.0.0.1';
const PORT = Number(process.env.TLS_SPA_PORT || '1290');
const DIST = path.resolve(process.env.TLS_SPA_DIST || 'dist');
const CERT = process.env.TLS_SPA_CERT;
const KEY = process.env.TLS_SPA_KEY;
if (HOST !== '127.0.0.1' && HOST !== '::1') throw new Error('TLS SPA server is loopback-only');
if (!Number.isInteger(PORT) || PORT < 1024 || PORT > 65535) throw new Error('invalid TLS_SPA_PORT');
if (!CERT || !KEY || !path.isAbsolute(CERT) || !path.isAbsolute(KEY)) {
  throw new Error('absolute TLS_SPA_CERT and TLS_SPA_KEY paths are required');
}
if (!existsSync(path.join(DIST, 'index.html'))) throw new Error('TLS_SPA_DIST must contain index.html');

const mime = new Map([
  ['.css', 'text/css; charset=utf-8'], ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'], ['.json', 'application/json; charset=utf-8'],
  ['.png', 'image/png'], ['.svg', 'image/svg+xml'], ['.woff2', 'font/woff2'],
  ['.webmanifest', 'application/manifest+json'],
]);

const server = createServer({ cert: await readFile(CERT), key: await readFile(KEY) }, (request, response) => {
  try {
    const requested = decodeURIComponent(new URL(request.url || '/', `https://${HOST}:${PORT}`).pathname);
    const candidate = path.resolve(DIST, `.${requested}`);
    const contained = candidate === DIST || candidate.startsWith(`${DIST}${path.sep}`);
    const file = contained && existsSync(candidate) && statSync(candidate).isFile()
      ? candidate : path.join(DIST, 'index.html');
    response.writeHead(200, {
      'Content-Type': mime.get(path.extname(file)) || 'application/octet-stream',
      'Cache-Control': file.endsWith('index.html') ? 'no-store' : 'public, max-age=31536000, immutable',
      'X-Content-Type-Options': 'nosniff',
    });
    createReadStream(file).pipe(response);
  } catch {
    response.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Bad request');
  }
});

server.listen(PORT, HOST, () => {
  console.log(`TLS SPA fixture listening on https://${HOST}:${PORT}; dist=${DIST}`);
});
