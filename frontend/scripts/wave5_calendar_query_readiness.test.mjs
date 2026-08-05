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
  calendarEventDetailPath,
  changeTimezoneWithQueryReady,
  createCalendarEventWithDetailReady,
  createdCalendarEventIdentityMatches,
  encodedTimezoneParam,
  matchesCalendarEventDetailQuery,
  matchesCreatedCalendarEventDetailQuery,
  matchesCalendarEventsQuery,
  runtimeClean,
  runtimeErrors,
  saveCalendarEventWithDetailReady,
} from './lib/wave5_calendar_query_readiness.mjs';

const WEB = 'https://127.0.0.1:1290';
const API = 'https://127.0.0.1:1291';
const TIMEZONE = 'Asia/Dubai';
const EVENT_ID = 'c64c7235-f22f-4bb8-8bed-7ab38d7c44ce';
const REFETCH_MS = 20;

function eventsUrl(timezone) {
  const query = new URLSearchParams();
  query.set('source_types', 'tutoring');
  query.set('timezone', timezone);
  return `${API}/api/v1/calendar/events?${query.toString()}`;
}

function eventDetailUrl(eventId = EVENT_ID) {
  return `${API}${calendarEventDetailPath(eventId)}`;
}

/** Minimal Playwright-shaped page whose network semantics match Chromium's. */
function fakePage({ responseCompletionError = null } = {}) {
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
        return typeof responseCompletionError === 'function'
          ? responseCompletionError(request)
          : responseCompletionError;
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

/** Save one event, then start the exact invalidation refetch that lands later. */
function applyEventSave(page, eventId = EVENT_ID) {
  return async () => {
    const put = page.startRequest(eventDetailUrl(eventId), 'PUT');
    page.completeRequest(put, 200);
    const detail = page.startRequest(eventDetailUrl(eventId), 'GET');
    setTimeout(() => page.completeRequest(detail, 200), REFETCH_MS);
  };
}

/** Create one event, then start its route-owned detail query later. */
function applyEventCreate(page, eventId = EVENT_ID) {
  return async () => {
    const post = page.startRequest(`${API}/api/v1/calendar/events`, 'POST');
    page.completeRequest(post, 201);
    const detail = page.startRequest(eventDetailUrl(eventId), 'GET');
    setTimeout(() => page.completeRequest(detail, 200), REFETCH_MS);
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

async function runEventDetailSequence({ legacyNavigateImmediately }) {
  const page = fakePage();
  const path = calendarEventDetailPath(EVENT_ID);
  const result = await saveCalendarEventWithDetailReady({
    page,
    eventId: EVENT_ID,
    applySave: applyEventSave(page),
    savePredicate: (response) => new URL(response.url()).pathname === path
      && response.request().method() === 'PUT'
      && response.status() === 200,
    timeout: 5_000,
    legacyNavigateImmediately,
  });
  // This models the real runner's immediate post-edit reload.
  await page.goto(`${WEB}/s-91?event=${EVENT_ID}`);
  page.dispose();
  return { page, result };
}

async function runEventCreateSequence({ legacyNavigateImmediately }) {
  const page = fakePage();
  const result = await createCalendarEventWithDetailReady({
    page,
    applyCreate: applyEventCreate(page),
    createPredicate: (response) => response.url() === `${API}/api/v1/calendar/events`
      && response.request().method() === 'POST'
      && response.status() === 201,
    timeout: 5_000,
    legacyNavigateImmediately,
  });
  // This models the real runner's first refresh after create/navigation.
  await page.goto(`${WEB}/s-91?event=${EVENT_ID}`);
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

  it('fails closed when a 200 response body does not finish cleanly', async () => {
    const page = fakePage({
      responseCompletionError: new Error('net::ERR_ABORTED'),
    });
    await expect(changeTimezoneWithQueryReady({
      page,
      timezone: TIMEZONE,
      applyChange: applyTimezoneChange(page),
      savePredicate,
      timeout: 5_000,
      legacyNavigateImmediately: false,
    })).rejects.toThrow('calendar-events response did not finish cleanly: net::ERR_ABORTED');
    page.dispose();
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

describe('S-91 event-detail readiness contract', () => {
  it('the OLD post-create sequence aborts the route-owned event-detail GET', async () => {
    const { page, result } = await runEventCreateSequence({ legacyNavigateImmediately: true });
    expect(result.detailReady).toBeNull();
    expect(runtimeClean(page.state)).toBe(false);
    expect(runtimeErrors(page.state).failedRequests).toEqual([
      `GET ${eventDetailUrl()} net::ERR_ABORTED`,
    ]);
  });

  it('settles the post-create event-detail GET before the first refresh', async () => {
    const { page, result } = await runEventCreateSequence({ legacyNavigateImmediately: false });
    expect(result.create.status()).toBe(201);
    expect(result.create.isFinished()).toBe(true);
    expect(result.detailReady.status()).toBe(200);
    expect(result.detailReady.isFinished()).toBe(true);
    expect(matchesCreatedCalendarEventDetailQuery({
      url: result.detailReady.url(), method: 'GET', status: 200,
    })).toBe(true);
    expect(page.inflightCount()).toBe(0);
    expect(runtimeErrors(page.state).failedRequests).toEqual([]);
    expect(runtimeClean(page.state)).toBe(true);
  });

  it('the OLD immediate-reload sequence aborts the exact event-detail GET', async () => {
    const { page, result } = await runEventDetailSequence({ legacyNavigateImmediately: true });
    expect(result.detailReady).toBeNull();
    expect(runtimeClean(page.state)).toBe(false);
    expect(runtimeErrors(page.state).failedRequests).toEqual([
      `GET ${eventDetailUrl()} net::ERR_ABORTED`,
    ]);
  });

  it('settles the exact event-detail GET body before reload', async () => {
    const { page, result } = await runEventDetailSequence({ legacyNavigateImmediately: false });
    expect(result.save.status()).toBe(200);
    expect(result.detailReady).not.toBeNull();
    expect(result.detailReady.status()).toBe(200);
    expect(result.detailReady.isFinished()).toBe(true);
    expect(page.inflightCount()).toBe(0);
    expect(runtimeErrors(page.state).failedRequests).toEqual([]);
    expect(runtimeClean(page.state)).toBe(true);
  });

  it('fails closed when the event-detail response body is aborted after HTTP 200', async () => {
    const page = fakePage({
      responseCompletionError: (request) => request.method === 'GET'
        ? new Error('net::ERR_ABORTED')
        : null,
    });
    await expect(saveCalendarEventWithDetailReady({
      page,
      eventId: EVENT_ID,
      applySave: applyEventSave(page),
      savePredicate: (response) => response.url() === eventDetailUrl()
        && response.request().method() === 'PUT'
        && response.status() === 200,
      timeout: 5_000,
    })).rejects.toThrow('calendar-event detail response did not finish cleanly: net::ERR_ABORTED');
    page.dispose();
  });

  it('matches only the exact successful event-detail GET', () => {
    const ok = { url: eventDetailUrl(), method: 'GET', status: 200 };
    expect(matchesCalendarEventDetailQuery(ok, EVENT_ID)).toBe(true);
    expect(matchesCalendarEventDetailQuery({ ...ok, url: eventsUrl(TIMEZONE) }, EVENT_ID)).toBe(false);
    expect(matchesCalendarEventDetailQuery({ ...ok, url: eventDetailUrl('wrong-id') }, EVENT_ID)).toBe(false);
    expect(matchesCalendarEventDetailQuery({ ...ok, url: `${eventDetailUrl()}?expand=true` }, EVENT_ID)).toBe(false);
    expect(matchesCalendarEventDetailQuery({ ...ok, method: 'PUT' }, EVENT_ID)).toBe(false);
    expect(matchesCalendarEventDetailQuery({ ...ok, status: 304 }, EVENT_ID)).toBe(false);
    expect(matchesCalendarEventDetailQuery({ ...ok, status: 500 }, EVENT_ID)).toBe(false);
    expect(matchesCalendarEventDetailQuery({ ...ok, url: 'not-a-url' }, EVENT_ID)).toBe(false);
    expect(() => calendarEventDetailPath('')).toThrow('calendar event id is required');
  });

  it('matches only one successful created event-detail resource', () => {
    const ok = { url: eventDetailUrl(), method: 'GET', status: 200 };
    expect(matchesCreatedCalendarEventDetailQuery(ok)).toBe(true);
    expect(matchesCreatedCalendarEventDetailQuery({ ...ok, url: `${eventDetailUrl()}/nested` })).toBe(false);
    expect(matchesCreatedCalendarEventDetailQuery({ ...ok, url: `${eventDetailUrl()}?expand=true` })).toBe(false);
    expect(matchesCreatedCalendarEventDetailQuery({ ...ok, url: eventsUrl(TIMEZONE) })).toBe(false);
    expect(matchesCreatedCalendarEventDetailQuery({ ...ok, method: 'POST' })).toBe(false);
    expect(matchesCreatedCalendarEventDetailQuery({ ...ok, status: 304 })).toBe(false);
    expect(matchesCreatedCalendarEventDetailQuery({ ...ok, url: 'not-a-url' })).toBe(false);
  });

  it('requires the POST body id, SPA route id, and detail id to agree', () => {
    const detail = { url: eventDetailUrl(), method: 'GET', status: 200 };
    expect(createdCalendarEventIdentityMatches({
      createdId: EVENT_ID, routeId: EVENT_ID, detail,
    })).toBe(true);
    expect(createdCalendarEventIdentityMatches({
      createdId: 'wrong-id', routeId: EVENT_ID, detail,
    })).toBe(false);
    expect(createdCalendarEventIdentityMatches({
      createdId: EVENT_ID, routeId: 'wrong-id', detail,
    })).toBe(false);
    expect(createdCalendarEventIdentityMatches({
      createdId: EVENT_ID, routeId: EVENT_ID, detail: { ...detail, url: eventDetailUrl('wrong-id') },
    })).toBe(false);
    expect(createdCalendarEventIdentityMatches({
      createdId: EVENT_ID, routeId: EVENT_ID, detail: { ...detail, status: 500 },
    })).toBe(false);
  });
});
