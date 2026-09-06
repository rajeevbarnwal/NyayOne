// Diagnostic projection only. Every runtime error still fails the producer.
import { readFileSync } from 'node:fs';

const contract = JSON.parse(readFileSync(new URL('./wave1-runtime-diagnostics.json', import.meta.url), 'utf8'));
const templates = new Set(contract.routeTemplates);

export function canonicalRuntimeRoute(raw) {
  let pathname;
  try {
    const url = new URL(raw);
    if (!['http:', 'https:'].includes(url.protocol)) return 'unclassified-route';
    pathname = url.pathname;
  } catch { return 'unclassified-route'; }
  if (templates.has(pathname)) return pathname;
  if (/^\/s-\d{2}$/.test(pathname)) return '/s-{screen}';
  if (pathname.startsWith('/assets/')) return '/assets/{asset}';
  if (pathname.startsWith('/fonts/')) return '/fonts/{font}';
  if (pathname.startsWith('/api/v1/student/privacy/requests/')) return '/api/v1/student/privacy/requests/{request_id}';
  if (/^\/api\/v1\/student\/internships\/[^/]+\/saved$/.test(pathname)) return '/api/v1/student/internships/{listing_id}/saved';
  if (/^\/api\/v1\/internships\/[^/]+$/.test(pathname)) return '/api/v1/internships/{listing_id}';
  return 'unclassified-route';
}

export function runtimeEvent(stage, url, method = 'NONE', status = 0, reason = 'NONE') {
  return {
    stage,
    routeTemplate: canonicalRuntimeRoute(url),
    method: contract.methods.includes(method) ? method : 'OTHER',
    status: Number.isInteger(status) && status >= 400 && status <= 599 ? status : 0,
    reason: contract.reasons.includes(reason) ? reason : 'OTHER',
  };
}

export function createRuntimeEvidence() {
  return { consoleErrors: [], pageErrors: [], failedRequests: [], httpErrors: [], unmatchedApi: [] };
}

export function attachRuntimeEvidence(page, runtime) {
  page.on('console', (message) => {
    if (message.type() === 'error') runtime.consoleErrors.push(runtimeEvent('console-error', message.location().url || page.url()));
  });
  page.on('pageerror', () => runtime.pageErrors.push(runtimeEvent('page-error', page.url())));
  page.on('requestfailed', (request) => {
    runtime.failedRequests.push(runtimeEvent('request-failed', request.url(), request.method(), 0, request.failure()?.errorText));
  });
  page.on('response', (response) => {
    if (response.status() >= 400) runtime.httpErrors.push(runtimeEvent('http-error', response.url(), response.request().method(), response.status()));
  });
}
