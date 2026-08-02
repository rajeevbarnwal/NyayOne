/**
 * D3 — post-timezone browser readiness contract for the Wave 5 real runner.
 *
 * The problem this module owns
 * ----------------------------
 * Saving a new calendar timezone is a mutation. React Query invalidates the
 * calendar-events query, so a NEW `GET /api/v1/calendar/events?...&timezone=…`
 * starts a moment AFTER the PUT response. `page.waitForLoadState('networkidle')`
 * cannot express that: the document already reached networkidle, so the call
 * can resolve before the refetch is even issued. The next `page.goto()` then
 * cancels the in-flight GET, Chromium reports `net::ERR_ABORTED`, and the
 * runtime oracle correctly (but confusingly) fails the run.
 *
 * The contract
 * ------------
 * 1. BEFORE the timezone is changed, register a wait for the exact successful
 *    post-save `GET /api/v1/calendar/events` whose `timezone` query parameter
 *    is the newly saved zone (wire form `timezone=Asia%2FDubai`).
 * 2. Apply the change and await the PUT.
 * 3. Await that GET's response AND its body completion. Once `finished()`
 *    resolves the response can no longer be aborted by a navigation.
 * 4. Only then navigate.
 *
 * Nothing here ignores, whitelists or clears a failure: `ERR_ABORTED` remains
 * a hard failure of the runtime oracle. The fix removes the cause.
 *
 * `legacyNavigateImmediately` reproduces the pre-repair sequence byte for byte
 * for the seeded regression; it is reachable only through an explicit env gate.
 */

export const CALENDAR_EVENTS_PATH = '/api/v1/calendar/events';
export const READY_TIMEOUT_MS = 20_000;

/** The exact API pathname for one opaque calendar event identifier. */
export function calendarEventDetailPath(eventId) {
  if (typeof eventId !== 'string' || !eventId.trim()) {
    throw new Error('calendar event id is required');
  }
  return `${CALENDAR_EVENTS_PATH}/${encodeURIComponent(eventId)}`;
}

/** The exact wire form the SPA emits, e.g. `timezone=Asia%2FDubai`. */
export function encodedTimezoneParam(timezone) {
  return `timezone=${encodeURIComponent(timezone)}`;
}

/**
 * True only for a successful calendar-events GET carrying the given timezone.
 * @param {{url: string, method?: string, status: number}} candidate
 */
export function matchesCalendarEventsQuery(candidate, timezone) {
  let parsed;
  try {
    parsed = new URL(candidate.url);
  } catch {
    return false;
  }
  return parsed.pathname === CALENDAR_EVENTS_PATH
    && (candidate.method ?? 'GET').toUpperCase() === 'GET'
    && parsed.searchParams.get('timezone') === timezone
    && parsed.search.includes(encodedTimezoneParam(timezone))
    && candidate.status === 200;
}

/**
 * True only for a successful GET of the requested event-detail resource.
 * Query-bearing or prefix/suffix matches are rejected so an unrelated request
 * can never satisfy the navigation-readiness contract.
 * @param {{url: string, method?: string, status: number}} candidate
 */
export function matchesCalendarEventDetailQuery(candidate, eventId) {
  let parsed;
  try {
    parsed = new URL(candidate.url);
  } catch {
    return false;
  }
  return parsed.pathname === calendarEventDetailPath(eventId)
    && parsed.search === ''
    && (candidate.method ?? 'GET').toUpperCase() === 'GET'
    && candidate.status === 200;
}

/** Registers the wait. MUST be called BEFORE the mutation that triggers it. */
export function registerCalendarQueryReady(page, timezone, timeout = READY_TIMEOUT_MS) {
  return page.waitForResponse(
    (response) => matchesCalendarEventsQuery(
      {
        url: response.url(),
        method: response.request().method(),
        status: response.status(),
      },
      timezone,
    ),
    { timeout },
  );
}

/** Registers the event-detail wait. MUST be called before the save mutation. */
export function registerCalendarEventDetailReady(page, eventId, timeout = READY_TIMEOUT_MS) {
  return page.waitForResponse(
    (response) => matchesCalendarEventDetailQuery(
      {
        url: response.url(),
        method: response.request().method(),
        status: response.status(),
      },
      eventId,
    ),
    { timeout },
  );
}

async function settleResponse(pending, label) {
  const response = await pending;
  const completionError = await response.finished();
  if (completionError) {
    throw new Error(
      `${label} response did not finish cleanly: ${completionError.message}`,
      { cause: completionError },
    );
  }
  return response;
}

/** Awaits the response AND its body, so a later navigation cannot abort it. */
export async function settleCalendarQuery(pending) {
  return settleResponse(pending, 'calendar-events');
}

/** Awaits the exact detail response and its body before route transition. */
export async function settleCalendarEventDetail(pending) {
  return settleResponse(pending, 'calendar-event detail');
}

/**
 * Change the calendar timezone and return only once the app-owned refetch this
 * mutation triggers has fully completed.
 *
 * @returns {Promise<{save: object, queryReady: object|null}>}
 */
export async function changeTimezoneWithQueryReady({
  page,
  timezone,
  applyChange,
  savePredicate,
  timeout = READY_TIMEOUT_MS,
  legacyNavigateImmediately = false,
}) {
  if (legacyNavigateImmediately) {
    // Pre-repair sequence: the post-save GET is never awaited, so whatever
    // navigates next may abort it. Retained only for the seeded regression.
    const [save] = await Promise.all([
      page.waitForResponse(savePredicate, { timeout }),
      applyChange(),
    ]);
    await page.waitForLoadState('networkidle', { timeout });
    return { save, queryReady: null };
  }
  const pendingQuery = registerCalendarQueryReady(page, timezone, timeout);
  const [save] = await Promise.all([
    page.waitForResponse(savePredicate, { timeout }),
    applyChange(),
  ]);
  const queryReady = await settleCalendarQuery(pendingQuery);
  await page.waitForLoadState('networkidle', { timeout });
  return { save, queryReady };
}

/**
 * Save an existing event and return only after the mutation-triggered detail
 * refetch has fully completed. `legacyNavigateImmediately` exists solely for
 * the seeded regression that proves the previous sequence fails closed.
 *
 * @returns {Promise<{save: object, detailReady: object|null}>}
 */
export async function saveCalendarEventWithDetailReady({
  page,
  eventId,
  applySave,
  savePredicate,
  timeout = READY_TIMEOUT_MS,
  legacyNavigateImmediately = false,
}) {
  if (legacyNavigateImmediately) {
    const [save] = await Promise.all([
      page.waitForResponse(savePredicate, { timeout }),
      applySave(),
    ]);
    await page.waitForLoadState('networkidle', { timeout });
    return { save, detailReady: null };
  }

  const pendingDetail = registerCalendarEventDetailReady(page, eventId, timeout);
  const [save] = await Promise.all([
    page.waitForResponse(savePredicate, { timeout }),
    applySave(),
  ]);
  const [settledSave, detailReady] = await Promise.all([
    settleResponse(Promise.resolve(save), 'calendar-event save'),
    settleCalendarEventDetail(pendingDetail),
  ]);
  await page.waitForLoadState('networkidle', { timeout });
  return { save: settledSave, detailReady };
}

/** The runtime oracle. Kept pure so the seeded regression asserts the real one. */
export function runtimeErrors(state) {
  return {
    consoleErrors: state.consoleErrors,
    pageErrors: state.pageErrors,
    failedRequests: state.failedRequests,
    badResponses: state.badResponses,
  };
}

export function runtimeClean(state) {
  return Object.values(runtimeErrors(state)).every((items) => items.length === 0);
}
