/**
 * Wave 5 S-90–S-93 REAL target-runtime release harness.
 *
 * Unlike wave5-calendar-e2e.mjs, this runner installs no HTTP routes and owns
 * no mock data.  It requires a separately migrated, isolated database seeded
 * by backend/scripts/seed_wave5_calendar_e2e.py, a real backend, and a real
 * production frontend build.  All lifecycle assertions traverse those HTTP
 * and PostgreSQL boundaries.
 *
 * Mandatory environment:
 *   WAVE5_E2E_ALLOW_REAL=true
 *   WAVE5_E2E_SESSION_TOKEN=<opaque 32+ character token used by the seed>
 *   WAVE5_E2E_SEED_MANIFEST=/absolute/path/to/safe-seed-manifest.json
 *   E2E_WEB_URL=https://127.0.0.1:<frontend-port>
 *   E2E_API_URL=https://127.0.0.1:<backend-port>
 *   E2E_PUBLIC_URL=https://127.0.0.1:<TLS-feed-or-proxy-port>
 *   E2E_OUTPUT_DIR=/absolute/path/to/new/evidence-directory
 *
 * The raw session bearer and one-time calendar feed bearer remain in memory.
 * They are never emitted to stdout, JSON, screenshots, traces or filenames.
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium, request as playwrightRequest } from 'playwright';
import axe from 'axe-core';
import {
  CALENDAR_EVENTS_PATH,
  calendarEventDetailPath,
  changeTimezoneWithQueryReady,
  createCalendarEventWithDetailReady,
  createdCalendarEventIdentityMatches,
  encodedTimezoneParam,
  matchesCalendarEventDetailQuery,
  registerCalendarQueryReady,
  runtimeClean,
  runtimeErrors,
  saveCalendarEventWithDetailReady,
  settleCalendarQuery,
} from './lib/wave5_calendar_query_readiness.mjs';

const REQUIRED = [
  'WAVE5_E2E_SESSION_TOKEN',
  'WAVE5_E2E_SEED_MANIFEST',
  'E2E_WEB_URL',
  'E2E_API_URL',
  'E2E_PUBLIC_URL',
  'E2E_OUTPUT_DIR',
];
for (const name of REQUIRED) {
  if (!process.env[name]?.trim()) throw new Error(`${name} is required`);
}
if (process.env.WAVE5_E2E_ALLOW_REAL !== 'true') {
  throw new Error('WAVE5_E2E_ALLOW_REAL=true is required');
}

const SESSION_TOKEN = process.env.WAVE5_E2E_SESSION_TOKEN;
if (SESSION_TOKEN.length < 32) throw new Error('WAVE5_E2E_SESSION_TOKEN must be at least 32 characters');
const COOKIE_NAME = process.env.WAVE5_E2E_COOKIE_NAME?.trim() || 'legalsaathi_session';
const IGNORE_LOOPBACK_TLS = process.env.WAVE5_E2E_ALLOW_SELF_SIGNED_TLS === 'true';
const WEB = loopbackOrigin('E2E_WEB_URL', process.env.E2E_WEB_URL);
const API = loopbackOrigin('E2E_API_URL', process.env.E2E_API_URL);
const PUBLIC = loopbackOrigin('E2E_PUBLIC_URL', process.env.E2E_PUBLIC_URL);
if (WEB.hostname !== API.hostname || WEB.hostname !== PUBLIC.hostname) {
  throw new Error('all E2E origins must use the same explicit loopback hostname');
}
if ([WEB, API, PUBLIC].some((origin) => origin.protocol !== 'https:')) {
  throw new Error('all E2E origins must be HTTPS so Secure cookies and calendar bearers never cross plaintext transport');
}
if (!path.isAbsolute(process.env.E2E_OUTPUT_DIR) || !path.isAbsolute(process.env.WAVE5_E2E_SEED_MANIFEST)) {
  throw new Error('E2E_OUTPUT_DIR and WAVE5_E2E_SEED_MANIFEST must be absolute paths');
}
const OUT = path.resolve(process.env.E2E_OUTPUT_DIR);
const MANIFEST_PATH = path.resolve(process.env.WAVE5_E2E_SEED_MANIFEST);
const fixture = JSON.parse(await readFile(MANIFEST_PATH, 'utf8'));
for (const key of ['actor_id', 'tutoring_session_id', 'credential_reminder_id', 'tutoring_start_utc', 'timezone']) {
  if (typeof fixture[key] !== 'string' || !fixture[key]) throw new Error(`seed manifest missing ${key}`);
}
if (fixture.session_token !== 'NOT_LOGGED') throw new Error('seed manifest must not contain a session bearer');

/** The timezone S-90 switches to mid-run; the post-save refetch carries it. */
const NEXT_TIMEZONE = 'Asia/Dubai';
/**
 * Seeded D3 regression switch. When set, the runner reproduces the pre-repair
 * "navigate immediately after the timezone PUT" sequence so the oracle can be
 * shown to FAIL on it. It is never set by CI; reverting to the old behaviour is
 * provably this one branch.
 */
const LEGACY_TIMEZONE_NAVIGATION =
  process.env.WAVE5_E2E_INJECT_LEGACY_TIMEZONE_NAVIGATION === 'true';

const WIDTHS = [390, 430, 768, 1024, 1440];
const THEMES = ['light', 'dark'];
const EXPECTED_ASSERTION_ROWS = 305;
const report = {
  evidenceClass: 'real-target-runtime-api-postgresql-browser',
  releaseGate: true,
  startedAt: new Date().toISOString(),
  webOrigin: WEB.origin,
  apiOrigin: API.origin,
  publicOrigin: PUBLIC.origin,
  fixture: { tutoring: true, credentialReminder: true, authenticatedStudent: true },
  tracePolicy: 'omitted: Playwright traces would retain HttpOnly/feed bearer material',
  legacyTimezoneNavigationInjected: LEGACY_TIMEZONE_NAVIGATION,
  rows: [],
  failures: [],
};
let feedUrl;
let feedToken;
let fatalError = null;
let screenshotsCaptured = 0;
const secretValues = new Set([SESSION_TOKEN]);

function loopbackOrigin(name, raw) {
  const url = new URL(raw);
  const loopback = new Set(['127.0.0.1', 'localhost', '[::1]']);
  if (!['http:', 'https:'].includes(url.protocol) || !loopback.has(url.hostname)) {
    throw new Error(`${name} must be an explicit HTTP(S) loopback URL`);
  }
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error(`${name} must contain only scheme, loopback host and port`);
  }
  return url;
}

function sanitize(value) {
  let text = typeof value === 'string' ? value : JSON.stringify(value);
  for (const secret of secretValues) text = text.replaceAll(secret, '[BEARER_REDACTED]');
  return text.replace(/\/public\/calendar-feeds\/[^/?#\s]+\.ics/g, '/public/calendar-feeds/[REDACTED].ics').slice(0, 4000);
}

function registerFeedSecret(rawUrl, rawToken) {
  secretValues.add(rawUrl);
  secretValues.add(rawToken);
}

function acceptFeedUrl(rawUrl) {
  const parsed = new URL(rawUrl);
  loopbackOrigin('created feed URL origin', parsed.origin);
  if (parsed.origin !== PUBLIC.origin) {
    throw new Error('created feed URL must target the explicit E2E_PUBLIC_URL origin');
  }
  const match = parsed.pathname.match(/^\/api\/v1\/public\/calendar-feeds\/([A-Za-z0-9_-]{32,160})\.ics$/);
  if (!match) throw new Error('created feed URL has an invalid designated path');
  registerFeedSecret(rawUrl, match[1]);
  return { url: rawUrl, token: match[1] };
}

function record(name, expected, actual, pass) {
  const row = { name, expected, actual: sanitize(actual), pass: Boolean(pass) };
  report.rows.push(row);
  if (!row.pass) report.failures.push(`${name}: expected ${expected}; actual ${row.actual}`);
}

function assert(name, expected, actual, pass) {
  record(name, expected, actual, pass);
  if (!pass) throw new Error(`${name}: expected ${expected}; actual ${sanitize(actual)}`);
}

function cookieHeader() {
  return `${COOKIE_NAME}=${SESSION_TOKEN}`;
}

async function apiJson(api, method, pathname, options = {}) {
  const response = await api.fetch(pathname, { method, ...options });
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { /* caller checks */ }
  return { response, status: response.status(), body, text };
}

async function installCookie(context) {
  await context.addCookies([{
    name: COOKIE_NAME,
    value: SESSION_TOKEN,
    domain: WEB.hostname,
    path: '/',
    httpOnly: true,
    secure: WEB.protocol === 'https:',
    sameSite: 'Lax',
    expires: Math.floor(Date.now() / 1000) + 4 * 60 * 60,
  }]);
}

function watchRuntime(page) {
  const state = { consoleErrors: [], pageErrors: [], failedRequests: [], badResponses: [], apiResponseOrigins: [] };
  page.on('console', (message) => {
    if (message.type() === 'error') state.consoleErrors.push(sanitize(message.text()));
  });
  page.on('pageerror', (error) => state.pageErrors.push(sanitize(String(error))));
  page.on('requestfailed', (request) => {
    state.failedRequests.push(sanitize(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`));
  });
  page.on('response', (response) => {
    const parsed = new URL(response.url());
    if (parsed.pathname.startsWith('/api/v1/')) state.apiResponseOrigins.push(parsed.origin);
    if (response.status() >= 400) state.badResponses.push(sanitize(`${response.status()} ${response.url()}`));
  });
  return state;
}

async function waitReady(page) {
  const ready = page.locator('main.calv[data-wave5-ready="ready"]');
  await ready.waitFor({ state: 'visible', timeout: 20_000 });
  // The page-level ready attribute covers the primary calendar query. Wait for
  // companion auth/preference queries and mutation invalidations too, so the
  // next intentional route transition never cancels an otherwise healthy GET
  // and misclassifies it as a runtime network failure.
  await page.waitForLoadState('networkidle', { timeout: 20_000 });
  await page.evaluate(async () => {
    if (document.fonts) await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

function localParts(iso, timeZone) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    }).formatToParts(new Date(iso)).filter((item) => item.type !== 'literal').map((item) => [item.type, item.value]),
  );
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` };
}

function dashboardWeekExpectation(timezone, now = new Date()) {
  const today = localParts(now.toISOString(), timezone).date;
  const cursor = new Date(`${today}T12:00:00.000Z`);
  cursor.setUTCDate(cursor.getUTCDate() - ((cursor.getUTCDay() + 6) % 7));
  const labels = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(cursor);
    date.setUTCDate(cursor.getUTCDate() + index);
    return `${date.toLocaleDateString('en-IN', { weekday: 'short', timeZone: 'UTC' }).toUpperCase()} ${date.getUTCDate()}`;
  });
  const weekday = new Intl.DateTimeFormat('en-IN', { weekday: 'long', timeZone: timezone }).format(now);
  return { labels, weekday };
}

async function storageSnapshot(page) {
  return page.evaluate(async () => {
    const indexed = typeof indexedDB.databases === 'function'
      ? (await indexedDB.databases()).map((item) => item.name ?? '') : [];
    const cachesFound = typeof caches !== 'undefined' ? await caches.keys() : [];
    return {
      local: Object.fromEntries(Object.entries(localStorage)),
      session: Object.fromEntries(Object.entries(sessionStorage)),
      indexed,
      caches: cachesFound,
      documentCookie: document.cookie,
      href: location.href,
    };
  });
}

async function geometry(page) {
  return page.locator('main.calv').evaluate((main) => {
    const containers = [document.documentElement, document.body, main].map((node) => ({
      name: node === main ? 'main.calv' : node.tagName.toLowerCase(),
      scrollWidth: node.scrollWidth,
      clientWidth: node.clientWidth,
      overflow: Math.max(0, node.scrollWidth - node.clientWidth),
    }));
    const targetOf = (element) => {
      if (element instanceof HTMLInputElement && ['checkbox', 'radio'].includes(element.type)) {
        return element.closest('label')?.getBoundingClientRect() ?? element.getBoundingClientRect();
      }
      return element.getBoundingClientRect();
    };
    const small = [...main.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])')]
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = targetOf(element);
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
          && (rect.width < 44 || rect.height < 44);
      })
      .map((element) => {
        const rect = targetOf(element);
        return {
          label: element.getAttribute('aria-label') || element.textContent?.trim() || element.tagName,
          width: Number(rect.width.toFixed(2)), height: Number(rect.height.toFixed(2)),
        };
      });
    return {
      containers,
      small,
      documentHeight: document.documentElement.scrollHeight,
      viewportHeight: innerHeight,
    };
  });
}

async function axeResults(page) {
  await page.addScriptTag({ content: axe.source });
  return page.evaluate(async () => globalThis.axe.run('main.calv', {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
  }));
}

async function keyboardProbe(page) {
  await page.locator('body').click({ position: { x: 2, y: 2 } });
  const focused = [];
  for (let index = 0; index < 14; index += 1) {
    await page.keyboard.press('Tab');
    focused.push(await page.evaluate(() => {
      const node = document.activeElement;
      if (!(node instanceof HTMLElement)) return { tag: 'none', label: '', visible: false };
      const rect = node.getBoundingClientRect();
      return {
        tag: node.tagName.toLowerCase(),
        label: node.getAttribute('aria-label') || node.textContent?.trim().slice(0, 80) || '',
        visible: rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden',
      };
    }));
  }
  return focused;
}

async function newBrowserContext(browser, options) {
  const context = await browser.newContext({
    ...options,
    ignoreHTTPSErrors: IGNORE_LOOPBACK_TLS,
    permissions: ['clipboard-read', 'clipboard-write'],
  });
  await installCookie(context);
  return context;
}

await mkdir(OUT, { recursive: false });
const api = await playwrightRequest.newContext({
  baseURL: API.origin,
  ignoreHTTPSErrors: IGNORE_LOOPBACK_TLS,
  extraHTTPHeaders: { Cookie: cookieHeader(), Accept: 'application/json' },
});
const publicApi = await playwrightRequest.newContext({ ignoreHTTPSErrors: IGNORE_LOOPBACK_TLS });
const browser = await chromium.launch({ headless: true });

let personalEventId = null;
let editedTitle = `Calendar QA ${Date.now().toString(36)}`;
try {
  // Real cookie authentication and real source aggregation preflight.
  const session = await apiJson(api, 'GET', '/api/v1/auth/student/session');
  assert('authenticated session', '200 and matching student', session.status,
    session.status === 200 && session.body?.authenticated === true && session.body?.actor?.sub === fixture.actor_id);

  const initial = await apiJson(api, 'GET', '/api/v1/calendar/events?timezone=Asia%2FKolkata');
  const initialTypes = new Set(initial.body?.items?.map((item) => item.source_type) ?? []);
  assert('S-90 real module aggregation', 'tutoring + reminder, no failed adapters',
    { status: initial.status, sourceTypes: [...initialTypes], failedSources: initial.body?.failed_sources },
    initial.status === 200 && initialTypes.has('tutoring') && initialTypes.has('reminder')
      && Array.isArray(initial.body?.failed_sources) && initial.body.failed_sources.length === 0);
  const tutoringCalendarEventId = initial.body?.items?.find((item) => item.source_type === 'tutoring')?.id;
  const credentialCalendarEventId = initial.body?.items?.find((item) =>
    item.source_type === 'reminder' && item.event_kind === null)?.id;
  assert('S-90 tutoring identity', 'materialised calendar event id', tutoringCalendarEventId ?? 'missing',
    Boolean(tutoringCalendarEventId));
  assert('S-90 credential-reminder identity', 'materialised imported reminder event id', credentialCalendarEventId ?? 'missing',
    Boolean(credentialCalendarEventId));
  assert('clean calendar fixture', 'no personal event before lifecycle', initial.body?.items?.filter((item) => item.event_kind).length,
    initial.body?.items?.every((item) => item.event_kind === null));
  const exportsBefore = await apiJson(api, 'GET', '/api/v1/calendar/exports');
  assert('clean export fixture', '0 existing exports', exportsBefore.body?.total,
    exportsBefore.status === 200 && exportsBefore.body?.total === 0);

  // S-91 create -> refresh -> edit against the real API/database.
  const lifecycle = await newBrowserContext(browser, { viewport: { width: 430, height: 844 }, colorScheme: 'light' });
  const page = await lifecycle.newPage();
  const lifecycleRuntime = watchRuntime(page);
  const local = localParts(fixture.tutoring_start_utc, fixture.timezone);
  await page.goto(new URL('/s-91', WEB).href, { waitUntil: 'domcontentloaded' });
  await waitReady(page);
  await page.getByTestId('ev-title').fill(editedTitle);
  await page.getByTestId('ev-date').fill(local.date);
  await page.getByTestId('ev-time').fill(local.time);
  // The route id does not exist until the POST completes. Register a strict
  // successful detail-resource wait before clicking, then settle both response
  // bodies before any reload. A later identity check binds the generic
  // pre-registered GET to the POST response and the actual SPA route.
  const { create: createSave, detailReady: createdDetailReady } =
    await createCalendarEventWithDetailReady({
      page,
      applyCreate: () => page.getByTestId('ev-add').click(),
      createPredicate: (response) => new URL(response.url()).pathname === CALENDAR_EVENTS_PATH
        && response.request().method() === 'POST'
        && response.status() === 201,
    });
  await page.waitForURL((url) => url.pathname === '/s-91' && Boolean(url.searchParams.get('event')), { timeout: 20_000 });
  personalEventId = new URL(page.url()).searchParams.get('event');
  const createdBody = await createSave.json();
  if (createSave.status() !== 201
    || createdBody?.id !== personalEventId
    || !createdDetailReady
    || !createdCalendarEventIdentityMatches({
      createdId: createdBody?.id,
      routeId: personalEventId,
      detail: {
        url: createdDetailReady.url(),
        method: createdDetailReady.request().method(),
        status: createdDetailReady.status(),
      },
    })) {
    throw new Error(
      'post-create readiness contract violated before reload: expected completed '
      + `POST ${CALENDAR_EVENTS_PATH} and matching 200 GET ${calendarEventDetailPath(personalEventId ?? '')}`,
    );
  }
  await page.waitForFunction(
    (eventId) => {
      const region = document.querySelector('main.calv');
      return region instanceof HTMLElement
        && region.dataset.wave5EventId === eventId
        && region.dataset.wave5Ready === 'ready';
    },
    personalEventId,
    { timeout: 20_000 },
  );
  assert('S-91 create navigation', 'opaque event id', personalEventId ?? 'missing', Boolean(personalEventId));
  await waitReady(page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await waitReady(page);
  assert('S-91 refresh persistence', 'created title visible', await page.locator('main.calv').innerText(),
    (await page.locator('main.calv').innerText()).includes(editedTitle));
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  editedTitle = `${editedTitle} edited`;
  await page.getByTestId('ev-title').fill(editedTitle);
  // Saving invalidates the broad calendar query family. Arm the exact event
  // detail GET before the PUT, then settle both response bodies before a
  // reload can cancel the background React Query refetch.
  const eventDetailPath = calendarEventDetailPath(personalEventId);
  const { save: editSave, detailReady: editedDetailReady } = await saveCalendarEventWithDetailReady({
    page,
    eventId: personalEventId,
    applySave: () => page.getByRole('button', { name: 'Save changes', exact: true }).click(),
    savePredicate: (response) => new URL(response.url()).pathname === eventDetailPath
      && response.request().method() === 'PUT'
      && response.status() === 200,
  });
  if (editSave.status() !== 200
    || !editedDetailReady
    || !matchesCalendarEventDetailQuery(
      {
        url: editedDetailReady.url(),
        method: editedDetailReady.request().method(),
        status: editedDetailReady.status(),
      },
      personalEventId,
    )) {
    throw new Error(
      'post-edit readiness contract violated before reload: expected completed '
      + `PUT and GET ${eventDetailPath}`,
    );
  }
  await waitReady(page);
  await page.getByText(editedTitle, { exact: true }).waitFor({ timeout: 20_000 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await waitReady(page);
  assert('S-91 edit persistence', 'edited title after reload', await page.locator('main.calv').innerText(),
    (await page.locator('main.calv').innerText()).includes(editedTitle));

  // S-90 must now show the two imported sources plus the persisted event.
  await page.goto(new URL('/s-90', WEB).href, { waitUntil: 'domcontentloaded' });
  await waitReady(page);
  const monthText = await page.locator('main.calv').innerText();
  assert('S-90 aggregated source rendering', 'tutoring, credential reminder and personal event visible', monthText,
    monthText.includes('Tutoring session') && monthText.includes('Credential renewal reminder') && monthText.includes(editedTitle));

  await page.getByRole('button', { name: 'Filter', exact: true }).click();
  // D3 readiness contract: saving the timezone invalidates the calendar-events
  // query, so a NEW GET carrying timezone=Asia%2FDubai starts AFTER the PUT.
  // networkidle cannot express that (the document is already idle), so the
  // wait is registered BEFORE the change and the GET is settled to completion
  // BEFORE any navigation. See scripts/lib/wave5_calendar_query_readiness.mjs.
  const { save: timezoneSave, queryReady: timezoneQueryReady } = await changeTimezoneWithQueryReady({
    page,
    timezone: NEXT_TIMEZONE,
    applyChange: () => page.locator('#cal-tz').selectOption(NEXT_TIMEZONE),
    savePredicate: (response) => response.url().endsWith('/api/v1/calendar/view-preferences')
      && response.request().method() === 'PUT',
    legacyNavigateImmediately: LEGACY_TIMEZONE_NAVIGATION,
  });
  assert('S-90 timezone UI save', '200', timezoneSave.status(), timezoneSave.status() === 200);
  const savedView = await apiJson(api, 'GET', '/api/v1/calendar/view-preferences');
  assert('S-90 selected timezone persistence', 'Asia/Dubai', savedView.body?.timezone,
    savedView.status === 200 && savedView.body?.timezone === 'Asia/Dubai');
  if (!LEGACY_TIMEZONE_NAVIGATION) {
    // Readiness PRECONDITION, deliberately NOT an assert() row.
    //
    // The assertion count for this journey is a frozen contract at 305, so the
    // repair must not add a 306th row. It does not need to: the guarantee is
    // already structural — changeTimezoneWithQueryReady() awaits the matching
    // response AND response.finished(), so a query that never arrives or never
    // completes makes waitForResponse time out and throws before we get here.
    // This block is the belt to that braces, and it throws rather than
    // recording, so it is strictly fail-closed and count-neutral.
    const settledSearch = new URL(timezoneQueryReady?.url() ?? WEB.origin).search;
    if (!timezoneQueryReady
      || timezoneQueryReady.status() !== 200
      || !settledSearch.includes(encodedTimezoneParam(NEXT_TIMEZONE))) {
      throw new Error(
        'post-timezone readiness contract violated before navigation: expected a completed '
        + `200 GET ${CALENDAR_EVENTS_PATH} carrying ${encodedTimezoneParam(NEXT_TIMEZONE)}, got `
        + `status=${timezoneQueryReady?.status()} search=${settledSearch}`);
    }
  }

  // An imported credential reminder uses the reminder source category but has
  // no personal event_kind.  Its source module, not the calendar, owns edits.
  await page.goto(new URL(`/s-91?event=${encodeURIComponent(credentialCalendarEventId)}`, WEB).href,
    { waitUntil: 'domcontentloaded' });
  await waitReady(page);
  const importedDetail = page.locator('main.calv');
  assert('S-91 imported reminder read-only UI', 'Go to source; no Edit/Delete',
    {
      goToSource: await importedDetail.getByRole('button', { name: 'Go to source', exact: true }).count(),
      edit: await importedDetail.getByRole('button', { name: 'Edit', exact: true }).count(),
      delete: await importedDetail.getByRole('button', { name: 'Delete', exact: true }).count(),
    },
    await importedDetail.getByRole('button', { name: 'Go to source', exact: true }).count() === 1
      && await importedDetail.getByRole('button', { name: 'Edit', exact: true }).count() === 0
      && await importedDetail.getByRole('button', { name: 'Delete', exact: true }).count() === 0);

  // The dashboard week must follow the actual current date, never the old
  // July-2026 design fixture.
  // Arm both application-owned readiness waits before navigation. The weekday
  // labels can render from local dates before React Query finishes either the
  // view-preferences request or the dependent calendar-events request, so a
  // standalone networkidle wait here would repeat the D3 race in a second
  // route.
  const dashboardPreferencesReady = page.waitForResponse(
    (response) => response.url().endsWith('/api/v1/calendar/view-preferences')
      && response.request().method() === 'GET'
      && response.status() === 200,
    { timeout: 20_000 },
  );
  const dashboardEventsReady = registerCalendarQueryReady(
    page,
    savedView.body.timezone,
  );
  await page.goto(new URL('/s-14', WEB).href, { waitUntil: 'domcontentloaded' });
  const [dashboardPreferencesResponse] = await Promise.all([
    dashboardPreferencesReady,
    settleCalendarQuery(dashboardEventsReady),
  ]);
  const dashboardPreferencesCompletionError = await dashboardPreferencesResponse.finished();
  if (dashboardPreferencesCompletionError) {
    throw new Error(
      `dashboard view-preferences response did not finish cleanly: ${dashboardPreferencesCompletionError.message}`,
      { cause: dashboardPreferencesCompletionError },
    );
  }
  const expectedDashboard = dashboardWeekExpectation(savedView.body.timezone);
  const calendarDisclosure = page.locator('details').filter({ hasText: 'Calendar · this week' }).first();
  await calendarDisclosure.locator('summary').click();
  await page.locator('.st-week__dow').first().waitFor({ state: 'visible', timeout: 20_000 });
  const actualWeek = await page.locator('.st-week__dow').allTextContents();
  const eyebrow = (await page.locator('.st-eyebrow').textContent() ?? '').trim();
  const actualDashboard = { labels: actualWeek.map((item) => item.trim()), weekday: eyebrow };
  assert('dashboard dynamic current-week dates', expectedDashboard, actualDashboard,
    JSON.stringify(actualDashboard.labels) === JSON.stringify(expectedDashboard.labels)
      && actualDashboard.weekday.toLocaleLowerCase('en-IN')
        .startsWith(expectedDashboard.weekday.toLocaleLowerCase('en-IN')));

  // S-92 persists the half-open overlap and then exercises both transitions.
  await page.goto(new URL('/s-92', WEB).href, { waitUntil: 'domcontentloaded' });
  await waitReady(page);
  const conflictCard = page.locator('.cal-conflict').filter({ hasText: editedTitle }).first();
  await conflictCard.waitFor({ state: 'visible', timeout: 20_000 });
  const [dismissResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/v1/calendar/conflicts/')
      && response.request().method() === 'PATCH'),
    conflictCard.getByRole('button', { name: 'Dismiss', exact: true }).click(),
  ]);
  assert('S-92 dismiss mutation', '200 and visible dismissed status', dismissResponse.status(),
    dismissResponse.status() === 200);
  // StatusBadge includes an aria-hidden marker in the same text node.  Match
  // the status badge semantically instead of requiring its full textContent to
  // equal the label and thereby confusing the icon with product state.
  await conflictCard.locator('.status').filter({ hasText: 'dismissed' }).waitFor({ timeout: 20_000 });
  const [resolveResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().includes('/api/v1/calendar/conflicts/')
      && response.request().method() === 'PATCH'),
    conflictCard.getByRole('button', { name: 'Mark resolved', exact: true }).click(),
  ]);
  assert('S-92 resolve mutation', '200 and visible resolved status', resolveResponse.status(),
    resolveResponse.status() === 200);
  await conflictCard.locator('.status').filter({ hasText: 'resolved' }).waitFor({ timeout: 20_000 });
  const conflictsAfter = await apiJson(api, 'POST', '/api/v1/calendar/conflicts/check', {
    data: { event_ids: [personalEventId, tutoringCalendarEventId], persist: true },
  });
  const resolved = conflictsAfter.body?.items?.find((item) =>
    item.left_event_id === personalEventId || item.right_event_id === personalEventId);
  assert('S-92 conflict lifecycle', 'dismissed then resolved in PostgreSQL',
    { checkStatus: conflictsAfter.status, total: conflictsAfter.body?.total, finalStatus: resolved?.status },
    conflictsAfter.status === 200 && conflictsAfter.body?.total === 1 && resolved?.status === 'resolved');

  // S-93 reminder persistence through UI then API read-back.
  await page.goto(new URL('/s-93?tab=reminders', WEB).href, { waitUntil: 'domcontentloaded' });
  await waitReady(page);
  const reminderRow = page.getByTestId('cal-reminder-reminder-in_app');
  await reminderRow.getByRole('button', { name: /Configure Reminders in app reminder/i }).click();
  const reminderToggle = reminderRow.getByRole('checkbox', { name: 'Send this reminder' });
  await reminderRow.waitFor({ state: 'visible', timeout: 20_000 });
  const [disabledResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/calendar/reminder-preferences')
      && response.request().method() === 'PUT'),
    reminderToggle.setChecked(false),
  ]);
  const disabledPreferences = await apiJson(api, 'GET', '/api/v1/calendar/reminder-preferences');
  const disabledReminder = disabledPreferences.body?.items?.find((item) =>
    item.source_type === 'reminder' && item.channel === 'in_app');
  const disabledEligibility = await apiJson(api, 'POST', '/api/v1/calendar/reminder-preferences/preview', {
    data: { source_type: 'reminder', channel: 'in_app' },
  });
  assert('S-93 reminder opt-out eligibility', '200 and enabled=false',
    {
      response: disabledResponse.status(), enabled: disabledReminder?.enabled,
      version: disabledReminder?.version, schedulingEligible: disabledEligibility.body?.scheduling_eligible,
      reasonCode: disabledEligibility.body?.reason_code,
    },
    disabledResponse.status() === 200 && disabledEligibility.status === 200
      && disabledReminder?.enabled === false && disabledReminder?.version >= 1
      && disabledEligibility.body?.scheduling_eligible === false
      && disabledEligibility.body?.reason_code === 'disabled');
  await page.waitForFunction(() => {
    const input = document.querySelector('[data-testid="cal-reminder-reminder-in_app"] input[type="checkbox"]');
    return input instanceof HTMLInputElement && !input.checked;
  });

  const [enabledResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/calendar/reminder-preferences')
      && response.request().method() === 'PUT'),
    reminderToggle.setChecked(true),
  ]);
  const enabledPreferences = await apiJson(api, 'GET', '/api/v1/calendar/reminder-preferences');
  const enabledReminder = enabledPreferences.body?.items?.find((item) =>
    item.source_type === 'reminder' && item.channel === 'in_app');
  const enabledEligibility = await apiJson(api, 'POST', '/api/v1/calendar/reminder-preferences/preview', {
    data: { source_type: 'reminder', channel: 'in_app' },
  });
  assert('S-93 reminder re-enable eligibility', '200 and enabled=true',
    {
      response: enabledResponse.status(), enabled: enabledReminder?.enabled,
      version: enabledReminder?.version, schedulingEligible: enabledEligibility.body?.scheduling_eligible,
      reasonCode: enabledEligibility.body?.reason_code,
    },
    enabledResponse.status() === 200 && enabledEligibility.status === 200
      && enabledReminder?.enabled === true && enabledReminder?.version > disabledReminder?.version
      && enabledEligibility.body?.scheduling_eligible === true
      && enabledEligibility.body?.reason_code === 'eligible');
  await page.waitForFunction(() => {
    const input = document.querySelector('[data-testid="cal-reminder-reminder-in_app"] input[type="checkbox"]');
    return input instanceof HTMLInputElement && input.checked;
  });

  const [leadResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith('/api/v1/calendar/reminder-preferences')
      && response.request().method() === 'PUT'),
    reminderRow.getByLabel('Lead time').selectOption('60'),
  ]);
  const remindersAfter = await apiJson(api, 'GET', '/api/v1/calendar/reminder-preferences');
  assert('S-93 reminder persistence', 'reminder source remains eligible with 60-minute lead',
    remindersAfter.body?.items?.map((item) => ({ source: item.source_type, lead: item.lead_minutes, version: item.version })),
    leadResponse.status() === 200 && remindersAfter.status === 200 && remindersAfter.body?.items?.some((item) =>
      item.source_type === 'reminder' && item.channel === 'in_app' && item.enabled === true
        && item.lead_minutes === 60 && item.version > enabledReminder?.version));

  // Create and copy the one-time feed.  The token is retained only in memory.
  await page.goto(new URL('/s-93?tab=export', WEB).href, { waitUntil: 'domcontentloaded' });
  await waitReady(page);
  await page.getByRole('button', { name: 'Create private feed', exact: true }).click();
  await page.getByText('One-time secret ready', { exact: true }).waitFor({ timeout: 20_000 });
  const bodyBeforeCopy = await page.locator('body').innerText();
  await page.getByRole('button', { name: 'Copy private feed URL', exact: true }).click();
  await page.getByText(/one-time URL has been cleared/i).waitFor({ timeout: 20_000 });
  feedUrl = await page.evaluate(() => navigator.clipboard.readText());
  ({ url: feedUrl, token: feedToken } = acceptFeedUrl(feedUrl));
  assert('S-93 feed secret hidden from DOM', 'raw token absent', bodyBeforeCopy.includes(feedToken) ? 'present' : 'absent',
    !bodyBeforeCopy.includes(feedToken));
  const exportList = await apiJson(api, 'GET', '/api/v1/calendar/exports');
  assert('S-93 list is secret-free', 'feed_url absent/null for every item', exportList.body?.items,
    exportList.status === 200 && exportList.body?.items?.every((item) => item.feed_url == null)
      && exportList.body?.items?.some((item) => item.status === 'active' && item.timezone === 'Asia/Dubai'));

  // Rotation is an authenticated server operation.  The second creation must
  // revoke the first bearer atomically and preserve the selected timezone.
  const firstFeedUrl = feedUrl;
  const rotation = await apiJson(api, 'POST', '/api/v1/calendar/exports', {
    headers: { 'Idempotency-Key': `wave5-e2e-rotate-${Date.now()}` },
    data: { timezone: 'Asia/Dubai' },
  });
  if (rotation.status !== 201 || typeof rotation.body?.feed_url !== 'string') {
    throw new Error(`calendar feed rotation failed with status ${rotation.status}`);
  }
  ({ url: feedUrl, token: feedToken } = acceptFeedUrl(rotation.body.feed_url));
  const firstAfterRotation = await publicApi.get(firstFeedUrl);
  const rotatedFeed = await publicApi.get(feedUrl);
  const exportsAfterRotation = await apiJson(api, 'GET', '/api/v1/calendar/exports');
  assert('S-93 feed rotation', 'old bearer 404; new bearer 200; exactly one active Dubai feed',
    {
      oldStatus: firstAfterRotation.status(), newStatus: rotatedFeed.status(),
      active: exportsAfterRotation.body?.items?.filter((item) => item.status === 'active')
        .map((item) => ({ timezone: item.timezone, feedUrl: item.feed_url })),
    },
    firstAfterRotation.status() === 404 && rotatedFeed.status() === 200
      && exportsAfterRotation.body?.items?.filter((item) => item.status === 'active').length === 1
      && exportsAfterRotation.body?.items?.find((item) => item.status === 'active')?.timezone === 'Asia/Dubai'
      && exportsAfterRotation.body?.items?.every((item) => item.feed_url == null));

  const lifecycleStore = await storageSnapshot(page);
  const lifecycleStoreText = JSON.stringify(lifecycleStore);
  assert('browser storage privacy', 'no session/feed bearer in script-visible storage, URL or cookie',
    { keys: { local: Object.keys(lifecycleStore.local), session: Object.keys(lifecycleStore.session), indexed: lifecycleStore.indexed, caches: lifecycleStore.caches }, documentCookie: lifecycleStore.documentCookie ? '[present]' : '[empty]' },
    [...secretValues].every((secret) => !lifecycleStoreText.includes(secret)) && lifecycleStore.documentCookie === '');
  const authCookies = (await lifecycle.cookies()).filter((item) => item.name === COOKIE_NAME);
  assert('session cookie boundary', 'one HttpOnly SameSite=Lax cookie', authCookies.map((item) => ({ httpOnly: item.httpOnly, sameSite: item.sameSite })),
    authCookies.length === 1 && authCookies[0].httpOnly && authCookies[0].sameSite === 'Lax');
  assert('browser API origin contract', 'real API origin or explicit same-origin proxy only', lifecycleRuntime.apiResponseOrigins,
    lifecycleRuntime.apiResponseOrigins.length > 0
      && lifecycleRuntime.apiResponseOrigins.every((origin) => origin === API.origin || origin === WEB.origin));
  record('lifecycle runtime', '0 console/page/network errors', runtimeErrors(lifecycleRuntime), runtimeClean(lifecycleRuntime));
  await lifecycle.close();

  // Final-state viewport/theme evidence (50 real screenshots).
  const states = [
    ['s90-month', '/s-90'],
    ['s91-detail', `/s-91?event=${encodeURIComponent(personalEventId)}`],
    ['s92-conflict', '/s-92'],
    ['s93-reminders', '/s-93?tab=reminders'],
    ['s93-export', '/s-93?tab=export'],
  ];
  for (const [state, route] of states) {
    for (const width of WIDTHS) {
      for (const theme of THEMES) {
        const prefix = `${state}-${width}-${theme}`;
        const context = await newBrowserContext(browser, {
          viewport: { width, height: width <= 430 ? 844 : 900 }, colorScheme: theme,
        });
        await context.addInitScript((mode) => localStorage.setItem('ls-theme', mode), theme);
        const shotPage = await context.newPage();
        const runtime = watchRuntime(shotPage);
        await shotPage.goto(new URL(route, WEB).href, { waitUntil: 'domcontentloaded' });
        await waitReady(shotPage);
        const layout = await geometry(shotPage);
        record(`${prefix} horizontal overflow`, '0px for html/body/main', layout.containers,
          layout.containers.every((item) => item.overflow <= 1));
        record(`${prefix} target size`, 'all enabled targets at least 44x44 CSS px', layout.small,
          layout.small.length === 0);
        if (state === 's93-reminders' && width <= 430) {
          record(`${prefix} meaningful mobile scroll`, 'collapsed reminder list no taller than two viewports',
            { documentHeight: layout.documentHeight, viewportHeight: layout.viewportHeight },
            layout.documentHeight <= layout.viewportHeight * 2);
        }
        const a11y = await axeResults(shotPage);
        record(`${prefix} axe A/AA`, '0 violations', a11y.violations.map((item) => ({ id: item.id, targets: item.nodes.map((node) => node.target) })),
          a11y.violations.length === 0);
        const actualTheme = await shotPage.evaluate(() => document.documentElement.getAttribute('data-theme'));
        record(`${prefix} theme`, theme, actualTheme, actualTheme === theme);
        await shotPage.screenshot({ path: path.join(OUT, `${prefix}.png`), fullPage: true });
        screenshotsCaptured += 1;
        record(`${prefix} runtime`, '0 console/page/network errors', runtimeErrors(runtime), runtimeClean(runtime));
        await context.close();
      }
    }
  }
  assert('real screenshot matrix', '50 screenshots', screenshotsCaptured,
    screenshotsCaptured === WIDTHS.length * THEMES.length * states.length);

  // Keyboard, effective 200% reflow and reduced-motion gates for every state.
  for (const [state, route] of states) {
    const keyboardContext = await newBrowserContext(browser, { viewport: { width: 430, height: 844 } });
    const keyboardPage = await keyboardContext.newPage();
    await keyboardPage.goto(new URL(route, WEB).href, { waitUntil: 'domcontentloaded' });
    await waitReady(keyboardPage);
    const focus = await keyboardProbe(keyboardPage);
    record(`${state} keyboard order`, 'at least 3 unique visible controls', focus,
      focus.filter((item) => item.visible).length >= 3 && new Set(focus.filter((item) => item.visible).map((item) => `${item.tag}:${item.label}`)).size >= 3);
    await keyboardContext.close();

    // A 384 CSS-pixel viewport is the effective viewport created by zooming a
    // 768px desktop viewport to 200%; testing that reflow avoids a CSS-zoom
    // simulation that changes layout semantics.
    const zoomContext = await newBrowserContext(browser, { viewport: { width: 384, height: 900 } });
    const zoomPage = await zoomContext.newPage();
    await zoomPage.goto(new URL(route, WEB).href, { waitUntil: 'domcontentloaded' });
    await waitReady(zoomPage);
    const zoomLayout = await geometry(zoomPage);
    record(`${state} 200% equivalent reflow`, '0px horizontal overflow at 384 CSS px', zoomLayout.containers,
      zoomLayout.containers.every((item) => item.overflow <= 1));
    await zoomContext.close();

    const motionContext = await newBrowserContext(browser, {
      viewport: { width: 430, height: 844 }, reducedMotion: 'reduce',
    });
    const motionPage = await motionContext.newPage();
    await motionPage.goto(new URL(route, WEB).href, { waitUntil: 'domcontentloaded' });
    await waitReady(motionPage);
    const motion = await motionPage.evaluate(() => ({
      media: matchMedia('(prefers-reduced-motion: reduce)').matches,
      activeAnimations: [...document.querySelectorAll('main.calv *')].filter((node) => {
        const style = getComputedStyle(node);
        return style.animationName !== 'none' && style.animationPlayState === 'running'
          && parseFloat(style.animationDuration) > 0.01;
      }).map((node) => ({ tag: node.tagName, className: node.className, animation: getComputedStyle(node).animationName })),
    }));
    record(`${state} reduced motion`, 'media=true and 0 active animations', motion,
      motion.media && motion.activeAnimations.length === 0);
    await motionContext.close();
  }

  // Public feed allowlist and revocation lifecycle.  Never attach the auth
  // cookie to this public bearer request and never log its URL.
  const icsResponse = await publicApi.get(feedUrl);
  const ics = await icsResponse.text();
  const icsHeaders = icsResponse.headers();
  assert('public ICS response', '200 text/calendar, no-store, no-referrer',
    { status: icsResponse.status(), contentType: icsHeaders['content-type'], cacheControl: icsHeaders['cache-control'], referrerPolicy: icsHeaders['referrer-policy'] },
    icsResponse.status() === 200 && icsHeaders['content-type']?.includes('text/calendar')
      && icsHeaders['cache-control'] === 'private, no-store' && icsHeaders['referrer-policy'] === 'no-referrer');
  assert('public ICS allowlist', 'RFC5545 with generic summaries and no direct ids/raw title',
    { begin: ics.includes('BEGIN:VCALENDAR'), tutoring: ics.includes('SUMMARY:Tutoring session'), reminder: ics.includes('SUMMARY:Credential renewal reminder'), personal: ics.includes('SUMMARY:Personal reminder') },
    ics.includes('BEGIN:VCALENDAR') && ics.includes('END:VCALENDAR')
      && ics.includes('SUMMARY:Tutoring session') && ics.includes('SUMMARY:Credential renewal reminder')
      && ics.includes('SUMMARY:Personal reminder') && !ics.includes(fixture.actor_id)
      && !ics.includes(personalEventId) && !ics.includes(editedTitle));

  const revokeContext = await newBrowserContext(browser, { viewport: { width: 430, height: 844 } });
  const revokePage = await revokeContext.newPage();
  await revokePage.goto(new URL('/s-93?tab=export', WEB).href, { waitUntil: 'domcontentloaded' });
  await waitReady(revokePage);
  await revokePage.getByRole('button', { name: 'Revoke feed', exact: true }).click();
  await revokePage.getByText(/feed revoked/i).waitFor({ timeout: 20_000 });
  await revokePage.reload({ waitUntil: 'domcontentloaded' });
  await waitReady(revokePage);
  const revokedStateText = await revokePage.locator('main.calv').innerText();
  assert('S-93 revoked feed recovery UI', 'revoked status and Create private feed action after reload',
    {
      revokedStatus: /revoked/i.test(revokedStateText),
      createAction: await revokePage.getByRole('button', { name: 'Create private feed', exact: true }).count(),
    },
    /revoked/i.test(revokedStateText)
      && await revokePage.getByRole('button', { name: 'Create private feed', exact: true }).count() === 1);
  await revokeContext.close();
  const revokedResponse = await publicApi.get(feedUrl);
  assert('public ICS revocation', '404 after UI revoke', revokedResponse.status(), revokedResponse.status() === 404);

  // Move the personal event beyond the imported tutoring interval, then prove
  // both the persisted conflict projection and the S-92 UI clear after a
  // refresh.  This is stronger than changing a local fixture or merely
  // dismissing the conflict card.
  const eventBeforeMove = await apiJson(api, 'GET', `/api/v1/calendar/events/${encodeURIComponent(personalEventId)}`);
  const shiftedStart = new Date(new Date(eventBeforeMove.body?.starts_at).getTime() + 7 * 24 * 60 * 60 * 1000);
  const shiftedEnd = new Date(new Date(eventBeforeMove.body?.ends_at).getTime() + 7 * 24 * 60 * 60 * 1000);
  const moved = await apiJson(api, 'PUT', `/api/v1/calendar/events/${encodeURIComponent(personalEventId)}`, {
    data: {
      title: eventBeforeMove.body?.title,
      starts_at: shiftedStart.toISOString(),
      ends_at: shiftedEnd.toISOString(),
      timezone: eventBeforeMove.body?.timezone,
      status: eventBeforeMove.body?.status,
      privacy_classification: eventBeforeMove.body?.privacy_classification,
      event_kind: eventBeforeMove.body?.event_kind,
      expected_version: eventBeforeMove.body?.version,
    },
  });
  assert('S-92 move conflicting event', '200 with a later persisted interval',
    { status: moved.status, startsAt: moved.body?.starts_at, version: moved.body?.version },
    eventBeforeMove.status === 200 && moved.status === 200
      && moved.body?.version === eventBeforeMove.body?.version + 1
      && new Date(moved.body?.starts_at).getTime() === shiftedStart.getTime());
  const conflictsCleared = await apiJson(api, 'POST', '/api/v1/calendar/conflicts/check', {
    data: { event_ids: [personalEventId, tutoringCalendarEventId], persist: true },
  });
  assert('S-92 conflict disappears after move', '200 and zero current overlaps',
    { status: conflictsCleared.status, total: conflictsCleared.body?.total },
    conflictsCleared.status === 200 && conflictsCleared.body?.total === 0);
  const clearedContext = await newBrowserContext(browser, { viewport: { width: 430, height: 844 } });
  const clearedPage = await clearedContext.newPage();
  await clearedPage.goto(new URL('/s-92', WEB).href, { waitUntil: 'domcontentloaded' });
  await waitReady(clearedPage);
  const clearedText = await clearedPage.locator('main.calv').innerText();
  assert('S-92 cleared conflict UI', 'No conflicts found after refresh', clearedText,
    /no conflicts found/i.test(clearedText) && !(await clearedPage.locator('.cal-conflict').filter({ hasText: editedTitle }).count()));
  await clearedContext.close();

  // Delete through S-91 and prove the resource disappears after refresh/API.
  const deleteContext = await newBrowserContext(browser, { viewport: { width: 430, height: 844 } });
  const deletePage = await deleteContext.newPage();
  await deletePage.goto(new URL(`/s-91?event=${encodeURIComponent(personalEventId)}`, WEB).href, { waitUntil: 'domcontentloaded' });
  await waitReady(deletePage);
  await deletePage.getByRole('button', { name: 'Delete', exact: true }).click();
  await deletePage.waitForURL((url) => url.pathname === '/s-90', { timeout: 20_000 });
  const deleted = await apiJson(api, 'GET', `/api/v1/calendar/events/${encodeURIComponent(personalEventId)}`);
  assert('S-91 delete persistence', '404 after UI delete', deleted.status, deleted.status === 404);
  await deleteContext.close();
} catch (error) {
  fatalError = sanitize(error instanceof Error ? `${error.name}: ${error.message}` : String(error));
  report.failures.push(`fatal: ${fatalError}`);
} finally {
  await browser.close();
  await api.dispose();
  await publicApi.dispose();
}

report.finishedAt = new Date().toISOString();
report.total = report.rows.length;
report.passed = report.rows.filter((row) => row.pass).length;
if (report.total !== EXPECTED_ASSERTION_ROWS) {
  report.failures.push(
    `assertion-row contract violated: expected ${EXPECTED_ASSERTION_ROWS}, got ${report.total}`,
  );
}
report.failed = report.failures.length;
report.fatalError = fatalError;
report.screenshots = screenshotsCaptured;
const serialized = JSON.stringify(report, null, 2) + '\n';
if ([...secretValues].some((secret) => serialized.includes(secret))) {
  throw new Error('privacy guard refused to write evidence containing a raw bearer');
}
await writeFile(path.join(OUT, 'wave5-calendar-real-e2e.json'), serialized, { flag: 'wx' });
console.log(JSON.stringify({
  evidenceClass: report.evidenceClass,
  total: report.total,
  passed: report.passed,
  failed: report.failed,
  screenshots: report.screenshots,
  secretsWritten: false,
}, null, 2));
if (report.failures.length) process.exit(1);
