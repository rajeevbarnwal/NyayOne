/**
 * D3 seeded regression for the post-timezone browser readiness race.
 *
 * A deterministic fake reproduces exactly the Chromium behaviour the real
 * runner hits:
 *   - the document is already at `networkidle`, so `waitForLoadState`
 *     ('networkidle') resolves immediately;
 *   - saving the timezone triggers a LATE React-Query refetch
 *     `GET /api/v1/calendar/events?...&timezone=Asia%2FDubai`;
 *   - `page.goto()` cancels every in-flight request, which Chromium surfaces
 *     as `net::ERR_ABORTED` on `requestfailed`.
 *
 * With the OLD navigate-immediately sequence the real runtime oracle
 * (`runtimeClean`) FAILS. With the repaired readiness contract it passes, and
 * no failure is ignored, whitelisted, slept through or cleared.
 */
import { describe, expect, it } from 'vitest';

import {
  changeTimezoneWithQueryReady,
  encodedTimezoneParam,
  matchesCalendarEventsQuery,
  runtimeClean,
  runtimeErrors,
} from './lib/wave5_calendar_query_readiness.mjs';

const WEB = 'https://127.0.0.1:1290';
const API = 'https://127.0.0.1:1291';
const TIMEZONE = 'Asia/Dubai';
const REFETCH_MS = 20;

function eventsUrl(timezone) {
  const query = new URLSearchParams();
  query.set('source_types', 'tutoring');
  query.set('timezone', timezone);
  return `${API}/api/v1/calendar/events?${query.toString()}`;
}

/** Minimal Playwright-shaped page whose network semantics match Chromium's. */
function fakePage() {
  const state = { consoleErrors: [], pageErrors: [], failedRequests: [], badResponses: [] };
  const inflight = new Set();
  const listeners = new Set();
  const timers = new Set();

  function emit(response) {
    for (const listener of [...listeners]) listener(response);
  }

  function makeResponse(request, status) {
    let finished = false;
    return {
      url: () => request.url,
      status: () => status,
      request: () => ({ method: () => request.method }),
      // Chromium resolves `finished()` once the body is fully received; from
      // that point a navigation can no longer abort the request.
      finished: async () => {
        finished = true;
        return null;
      },
      isFinished: () => finished,
    };
  }

  const page = {
    startRequest(url, method = 'GET') {
      const request = { url, method };
      inflight.add(request);
      return request;
    },
    completeRequest(request, status = 200) {
      if (!inflight.has(request)) return;
      inflight.delete(request);
      emit(makeResponse(request, status));
    },
    waitForResponse(predicate, options = {}) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(
          () => { listeners.delete(listener); reject(new Error('waitForResponse timeout')); },
          options.timeout ?? 20_000,
        );
        timers.add(timer);
        const listener = (response) => {
          if (!predicate(response)) return;
          clearTimeout(timer);
          listeners.delete(listener);
          resolve(response);
        };
        listeners.add(listener);
      });
    },
    // The defect: the document already reached networkidle, so this resolves
    // without waiting for a query that has not finished yet.
    waitForLoadState: async () => undefined,
    async goto() {
      for (const request of inflight) {
        state.failedRequests.push(`${request.method} ${request.url} net::ERR_ABORTED`);
      }
      inflight.clear();
    },
    dispose() {
      for (const timer of timers) clearTimeout(timer);
    },
    state,
    inflightCount: () => inflight.size,
  };
  return page;
}

/** Save the timezone, then start the invalidation refetch that lands later. */
function applyTimezoneChange(page) {
  return async () => {
    const put = page.startRequest(`${API}/api/v1/calendar/view-preferences`, 'PUT');
    page.completeRequest(put, 200);
    // React Query invalidates synchronously with the mutation success and the
    // refetch response lands a few frames later.
    const refetch = page.startRequest(eventsUrl(TIMEZONE), 'GET');
    setTimeout(() => page.completeRequest(refetch, 200), REFETCH_MS);
  };
}

const savePredicate = (response) => response.url().endsWith('/api/v1/calendar/view-preferences')
  && response.request().method() === 'PUT';

async function runSequence({ legacyNavigateImmediately }) {
  const page = fakePage();
  const result = await changeTimezoneWithQueryReady({
    page,
    timezone: TIMEZONE,
    applyChange: applyTimezoneChange(page),
    savePredicate,
    timeout: 5_000,
    legacyNavigateImmediately,
  });
  // The runner's very next act after the timezone save is a navigation.
  await page.goto(`${WEB}/s-91`);
  page.dispose();
  return { page, result };
}

describe('D3 post-timezone readiness contract', () => {
  it('the OLD navigate-immediately sequence fails the runtime oracle', async () => {
    const { page, result } = await runSequence({ legacyNavigateImmediately: true });
    expect(result.queryReady).toBeNull();
    expect(runtimeClean(page.state)).toBe(false);
    const failures = runtimeErrors(page.state).failedRequests;
    expect(failures).toHaveLength(1);
    expect(failures[0]).toContain('net::ERR_ABORTED');
    expect(failures[0]).toContain('/api/v1/calendar/events');
    expect(failures[0]).toContain(encodedTimezoneParam(TIMEZONE));
  });

  it('the repaired contract settles the post-save query before navigating', async () => {
    const { page, result } = await runSequence({ legacyNavigateImmediately: false });
    expect(result.save.status()).toBe(200);
    expect(result.queryReady).not.toBeNull();
    expect(result.queryReady.status()).toBe(200);
    expect(result.queryReady.isFinished()).toBe(true);
    expect(new URL(result.queryReady.url()).search).toContain(encodedTimezoneParam(TIMEZONE));
    expect(page.inflightCount()).toBe(0);
    // Nothing was whitelisted or cleared: the array was never written to.
    expect(runtimeErrors(page.state).failedRequests).toEqual([]);
    expect(runtimeClean(page.state)).toBe(true);
  });
});

describe('calendar-events query matcher', () => {
  const ok = { url: eventsUrl(TIMEZONE), method: 'GET', status: 200 };

  it('accepts only a successful GET carrying the saved timezone', () => {
    expect(matchesCalendarEventsQuery(ok, TIMEZONE)).toBe(true);
    expect(matchesCalendarEventsQuery({ ...ok, method: 'POST' }, TIMEZONE)).toBe(false);
    expect(matchesCalendarEventsQuery({ ...ok, status: 500 }, TIMEZONE)).toBe(false);
    expect(matchesCalendarEventsQuery({ ...ok, status: 304 }, TIMEZONE)).toBe(false);
    expect(matchesCalendarEventsQuery(ok, 'Asia/Kolkata')).toBe(false);
    expect(matchesCalendarEventsQuery({ ...ok, url: eventsUrl('Asia/Kolkata') }, TIMEZONE)).toBe(false);
    expect(matchesCalendarEventsQuery({ ...ok, url: `${API}/api/v1/calendar/events/abc` }, TIMEZONE)).toBe(false);
    expect(matchesCalendarEventsQuery({ ...ok, url: 'not-a-url' }, TIMEZONE)).toBe(false);
  });

  it('requires the URL-encoded wire form', () => {
    expect(encodedTimezoneParam(TIMEZONE)).toBe('timezone=Asia%2FDubai');
    expect(new URL(ok.url).search).toContain('timezone=Asia%2FDubai');
  });
});
