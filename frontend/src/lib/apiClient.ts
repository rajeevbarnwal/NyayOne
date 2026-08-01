/**
 * Fetch client foundation (SAATHI-346). Adds an X-Request-ID correlation header
 * (matching the backend's header) so a request can be traced end-to-end, and
 * base-URLs against the configured API origin (port 1031).
 */
const API_BASE = (import.meta as { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL
  ?? 'http://localhost:1031';

export const REQUEST_ID_HEADER = 'X-Request-ID';

export function newRequestId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  return 'req-' + Math.random().toString(16).slice(2) + Date.now().toString(16);
}

export interface ApiOptions extends RequestInit {
  requestId?: string;
}

export async function apiFetch(path: string, opts: ApiOptions = {}): Promise<Response> {
  const requestId = opts.requestId ?? newRequestId();
  const headers = new Headers(opts.headers);
  if (!headers.has(REQUEST_ID_HEADER)) headers.set(REQUEST_ID_HEADER, requestId);
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  // The student session is an HttpOnly cookie. Include it for same-site local
  // development and cross-origin API calls explicitly; JavaScript never reads
  // or persists the bearer value.
  return fetch(url, { ...opts, credentials: opts.credentials ?? 'include', headers });
}

export { API_BASE };
