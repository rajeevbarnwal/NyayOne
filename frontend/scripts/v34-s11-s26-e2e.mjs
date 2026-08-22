import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import axe from 'axe-core';
import { chromium } from 'playwright';

const base = process.env.V34_BASE_URL ?? 'http://127.0.0.1:4177';
const evidenceDir = resolve(process.env.V34_EVIDENCE_DIR ?? 'test-results/v34-s11-s26');
const screenshotsDir = resolve(evidenceDir, 'screenshots');
await mkdir(screenshotsDir, { recursive: true });

const viewports = [
  { name: 'mobile-390x844', width: 390, height: 844 },
  { name: 'mobile-430x932', width: 430, height: 932 },
  { name: 'tablet-768x1024', width: 768, height: 1024 },
  { name: 'landscape-932x430', width: 932, height: 430 },
  { name: 'tablet-1024x768', width: 1024, height: 768 },
  { name: 'desktop-1440x900', width: 1440, height: 900 },
];
const themes = ['light', 'dark'];
const states = [
  ...Array.from({ length: 16 }, (_, index) => {
    const id = `S-${index + 11}`;
    const path = id === 'S-21' || id === 'S-22' ? `/${id.toLowerCase()}?listing=cam` : `/${id.toLowerCase()}`;
    return { id, path };
  }),
  { id: 'S-17E', path: '/s-17', edit: true },
];
const mobileScrollLimits = {
  'S-11': 111, 'S-12': 0, 'S-13': 22, 'S-14': 0, 'S-15': 463,
  'S-16': 8, 'S-17': 109, 'S-17E': 120, 'S-18': 0, 'S-19': 0,
  'S-20': 172, 'S-21': 205, 'S-22': 282, 'S-23': 18, 'S-24': 0,
  'S-25': 0, 'S-26': 0,
};

const rows = [];
const record = (area, expected, actual, pass, detail = '') => rows.push({ area, expected, actual, pass, detail });
const profile = {
  first_name: 'Aditi', middle_name: 'Rao', last_name: 'Nair',
  college: 'NLSIU', year_of_study: '4', masked_mobile: '******0042',
};
let settings = {
  theme: 'system', language: 'en', notif_email: true, notif_sms: true,
  notif_updates: false, version: 7,
  privacy: [
    { kind: 'analytics', enabled: false },
    { kind: 'marketing', enabled: false },
    { kind: 'share_partners', enabled: false },
  ],
};

const calendarViewPreferences = {
  view_mode: 'week',
  source_types: ['internship'],
  from_date: null,
  to_date: null,
  timezone: 'Asia/Kolkata',
  version: 1,
  updated_at: '2026-08-03T00:00:00Z',
};
const calendarEvents = { items: [], total: 0, failed_sources: [] };
const internshipListings = [
  {
    id: 'cam',
    role: 'Summer Associate, disputes',
    organisation: 'Cyril Amarchand Mangaldas',
    location: 'Mumbai',
    stipend_monthly_paise: 4000000,
    verification_status: 'verified',
    application_deadline: '2027-07-09',
    eligibility: '4th or 5th year · one 1,500-word writing sample',
    tags: ['Disputes', 'Mumbai', '6 weeks'],
    description: 'Research notes for live commercial disputes, first cuts of applications and written submissions, and client conferences with a supervising associate.',
    source: {
      name: 'Cyril Amarchand Mangaldas careers',
      url: 'https://www.cyrilshroff.com/careers/',
      retrieved_at: '2026-06-28T00:00:00Z',
      verified_at: '2026-06-28T00:00:00Z',
    },
  },
  {
    id: 'menon',
    role: 'Judicial research assistant',
    organisation: 'Chambers of Sr. Adv. R. Menon',
    location: 'Delhi High Court',
    stipend_monthly_paise: 1500000,
    verification_status: 'unverified',
    application_deadline: '2027-07-08',
    eligibility: '2nd year or above · rolling selection',
    tags: ['Research', 'Delhi'],
    description: 'Judicial research support with a senior advocate’s chambers at the Delhi High Court.',
    source: {
      name: 'Sample fixture',
      url: null,
      retrieved_at: null,
      verified_at: null,
    },
  },
  {
    id: 'vidhi',
    role: 'Research fellowship, policy',
    organisation: 'Vidhi Centre for Legal Policy',
    location: 'New Delhi',
    stipend_monthly_paise: null,
    verification_status: 'unverified',
    application_deadline: '2027-07-15',
    eligibility: 'All years · certificate on completion',
    tags: ['Policy', 'Research'],
    description: 'Legal-policy research internship; certificate on completion. Unpaid.',
    source: {
      name: 'Sample fixture',
      url: null,
      retrieved_at: null,
      verified_at: null,
    },
  },
];

function createRuntimeEvidence() {
  return {
    consoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    httpErrors: [],
    unmatchedApi: [],
  };
}

function attachRuntimeEvidence(page, runtime) {
  page.on('console', (message) => {
    if (message.type() === 'error') runtime.consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => runtime.pageErrors.push(error.message));
  page.on('requestfailed', (request) => {
    runtime.failedRequests.push(`${request.method()} ${request.url()} :: ${request.failure()?.errorText ?? 'unknown'}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      runtime.httpErrors.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  });
}

async function installApiContract(page, runtime, savedListingIds = new Set(['cam'])) {
  let otpFlow = {
    status: 'unavailable', purpose: null, destination_masked: null,
    attempts_left: null, expires_in_seconds: null, resend_in_seconds: null,
    locked_for_seconds: null, resend_allowed: false,
  };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (status, body) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (url.pathname === '/api/v1/student/profile') {
      if (request.method() === 'PATCH') {
        const body = request.postDataJSON();
        if (body.college) profile.college = body.college;
        if (body.year_of_study) profile.year_of_study = body.year_of_study;
      }
      return json(200, profile);
    }
    if (url.pathname === '/api/v1/auth/student/session') {
      return json(200, {
        authenticated: true,
        actor: {
          sub: 'student-browser-gate',
          roles: ['student'],
          student_profile_id: 'profile-browser-gate',
          student_verification: 'verified',
          is_minor: false,
          consent_state: ['registration'],
        },
      });
    }
    if (url.pathname === '/api/v1/student/settings') {
      if (request.method() === 'PATCH') {
        const body = request.postDataJSON();
        settings = {
          ...settings,
          ...(body.theme === undefined ? {} : { theme: body.theme }),
          ...(body.language === undefined ? {} : { language: body.language }),
          ...(body.notif_email === undefined ? {} : { notif_email: body.notif_email }),
          ...(body.notif_sms === undefined ? {} : { notif_sms: body.notif_sms }),
          ...(body.notif_updates === undefined ? {} : { notif_updates: body.notif_updates }),
          ...(body.privacy === undefined ? {} : { privacy: body.privacy }),
          version: settings.version + 1,
        };
      }
      return json(200, settings);
    }
    if (url.pathname.endsWith('/privacy/export')) return json(202, { request_id: 'export-opaque-001', status: 'pending' });
    if (url.pathname.includes('/privacy/requests/')) {
      return json(200, { request_id: url.pathname.split('/').pop(), kind: 'export', status: 'complete', created_at: '2026-08-01T00:00:00Z' });
    }
    if (url.pathname.endsWith('/privacy/delete')) {
      otpFlow = { ...otpFlow, status: 'unavailable', purpose: null };
      return json(202, { request_id: 'delete-opaque-001', status: 'pending' });
    }
    if (url.pathname === '/api/v1/auth/student/otp/state') return json(200, otpFlow);
    if (url.pathname.endsWith('/recovery/start')) {
      otpFlow = {
        status: 'pending', purpose: 'recovery', destination_masked: '••••••0042',
        attempts_left: 3, expires_in_seconds: 300, resend_in_seconds: 30,
        locked_for_seconds: 0, resend_allowed: false,
      };
      return json(202, otpFlow);
    }
    if (url.pathname.endsWith('/recovery/verify')) {
      otpFlow = {
        status: 'verified', purpose: 'recovery', destination_masked: null,
        attempts_left: null, expires_in_seconds: null, resend_in_seconds: null,
        locked_for_seconds: null, resend_allowed: false,
      };
      return json(200, otpFlow);
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/calendar/view-preferences') {
      return json(200, calendarViewPreferences);
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/calendar/events') {
      return json(200, calendarEvents);
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/internships') {
      return json(200, { items: internshipListings, total: internshipListings.length, page: 1, page_size: 20 });
    }
    if (request.method() === 'GET' && url.pathname === '/api/v1/student/internships/saved') {
      return json(200, { items: internshipListings.filter((listing) => savedListingIds.has(listing.id)) });
    }
    const savedMatch = url.pathname.match(/^\/api\/v1\/student\/internships\/([^/]+)\/saved$/);
    if ((request.method() === 'PUT' || request.method() === 'DELETE') && savedMatch) {
      const listingId = decodeURIComponent(savedMatch[1]);
      const listing = internshipListings.find((candidate) => candidate.id === listingId);
      if (!listing) return json(404, { detail: { code: 'internship_not_found' } });
      if (request.method() === 'PUT') savedListingIds.add(listingId);
      else savedListingIds.delete(listingId);
      return json(200, { saved: request.method() === 'PUT', listing_id: listingId });
    }
    const detailMatch = url.pathname.match(/^\/api\/v1\/internships\/([^/]+)$/);
    if (request.method() === 'GET' && detailMatch) {
      const listingId = decodeURIComponent(detailMatch[1]);
      const listing = internshipListings.find((candidate) => candidate.id === listingId);
      return listing
        ? json(200, listing)
        : json(404, { detail: { code: 'internship_not_found', message: 'This internship listing is unavailable.' } });
    }
    runtime.unmatchedApi.push(`${request.method()} ${url.pathname}${url.search}`);
    return json(501, { detail: { code: 'qa_route_not_stubbed' } });
  });
}

function isCalendarResponse(response, pathname) {
  const url = new URL(response.url());
  return response.request().method() === 'GET' && url.pathname === pathname;
}

function isExactApiResponse(response, method, pathname) {
  const url = new URL(response.url());
  return response.request().method() === method && url.pathname === pathname;
}

async function finishResponse(response) {
  const error = await response.finished();
  return {
    method: response.request().method(),
    path: `${new URL(response.url()).pathname}${new URL(response.url()).search}`,
    status: response.status(),
    finishedError: error?.message ?? null,
  };
}

async function waitForCalendarDashboardReady(page, responsePromises) {
  const responses = await Promise.all(responsePromises);
  const completed = await Promise.all(responses.map(finishResponse));
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return !text.includes('Loading calendar…') && !text.includes('Calendar preview is unavailable.');
  });
  return completed;
}

async function waitForInternshipStateReady(page, responsePromises) {
  const responses = await Promise.all(responsePromises);
  const completed = await Promise.all(responses.map(finishResponse));
  await page.waitForFunction(() => !document.body.innerText.includes('Loading internship'));
  return completed;
}

async function waitForDocumentReady(page) {
  await page.evaluate(async () => {
    if (document.fonts) await document.fonts.ready;
    await new Promise((resolveFrame) => requestAnimationFrame(
      () => requestAnimationFrame(resolveFrame),
    ));
  });
}

function geometryProbe() {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const smallTargets = [...document.querySelectorAll('button,input,select,textarea,a[href]')]
    .filter((element) => visible(element))
    .map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        name: element.getAttribute('aria-label') || element.textContent?.trim() || element.id,
        width: Math.round(rect.width * 10) / 10,
        height: Math.round(rect.height * 10) / 10,
      };
    })
    .filter((target) => target.width < 44 || target.height < 44);
  const content = document.querySelector('.v34c-content');
  const scrollable = [...document.querySelectorAll('*')]
    .filter((element) => {
      if (!visible(element)) return false;
      const style = getComputedStyle(element);
      return /(auto|scroll)/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 1;
    })
    .map((element) => ({
      className: element.className || element.tagName,
      overflow: element.scrollHeight - element.clientHeight,
    }));
  return {
    screen: document.querySelector('[data-screen]')?.getAttribute('data-screen'),
    h1Count: document.querySelectorAll('h1').length,
    bodyOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    contentOverflowX: content ? content.scrollWidth - content.clientWidth : -1,
    contentOverflowY: content ? content.scrollHeight - content.clientHeight : -1,
    smallTargets,
    scrollable,
    legacyShells: document.querySelectorAll('.ls-rail,.ls-topbar,.ls-bnav').length,
  };
}

const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of viewports) {
    for (const theme of themes) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: theme,
      });
      await context.addInitScript(({ themeValue }) => {
        localStorage.setItem('ls-theme', themeValue);
      }, { themeValue: theme });
      const page = await context.newPage();
      const runtime = createRuntimeEvidence();
      attachRuntimeEvidence(page, runtime);
      const contextSavedIds = new Set(['cam']);
      await installApiContract(page, runtime, contextSavedIds);

      for (const state of states) {
        if (state.id === 'S-26') contextSavedIds.clear();
        const calendarResponses = state.id === 'S-14' ? [
          page.waitForResponse((response) => isCalendarResponse(response, '/api/v1/calendar/view-preferences')),
          page.waitForResponse((response) => isCalendarResponse(response, '/api/v1/calendar/events')),
        ] : [];
        const internshipResponses = state.id === 'S-20' ? [
          page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/internships')),
          page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved')),
        ] : state.id === 'S-21' ? [
          page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/internships/cam')),
          page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved')),
        ] : state.id === 'S-22' ? [
          page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/internships/cam')),
        ] : state.id === 'S-25' ? [
          page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved')),
        ] : state.id === 'S-26' ? [
          page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved')),
        ] : [];
        await page.goto(`${base}${state.path}`, { waitUntil: 'domcontentloaded' });
        await page.locator(`[data-screen="${state.id === 'S-17E' ? 'S-17' : state.id}"]`).waitFor({ state: 'visible' });
        if (state.id === 'S-14') {
          const completed = await waitForCalendarDashboardReady(page, calendarResponses);
          record(
            `${state.id}__${viewport.name}__${theme}__calendar-ready`,
            'both exact calendar GETs finish with HTTP 200 before capture',
            completed,
            completed.length === 2 && completed.every((item) => item.status === 200 && item.finishedError === null),
          );
        }
        if (internshipResponses.length > 0) {
          const completed = await waitForInternshipStateReady(page, internshipResponses);
          record(
            `${state.id}__${viewport.name}__${theme}__internship-api-ready`,
            'all exact internship GETs finish with HTTP 200 before capture',
            completed,
            completed.length === internshipResponses.length
              && completed.every((item) => item.status === 200 && item.finishedError === null),
          );
        }
        await waitForDocumentReady(page);
        if (state.edit) {
          const edit = page.getByRole('button', { name: 'Edit college & year' });
          await edit.waitFor({ state: 'visible' });
          await edit.click();
          await page.getByRole('heading', { name: 'Edit college & year' }).waitFor({ state: 'visible' });
        }
        const geometry = await page.evaluate(geometryProbe);
        const prefix = `${state.id}__${viewport.name}__${theme}`;
        const expectedScreen = state.id === 'S-17E' ? 'S-17' : state.id;
        record(`${prefix}__screen`, expectedScreen, geometry.screen, geometry.screen === expectedScreen);
        record(`${prefix}__heading`, 'exactly one h1', geometry.h1Count, geometry.h1Count === 1);
        record(`${prefix}__overflow-x`, '0 horizontal px', { body: geometry.bodyOverflowX, content: geometry.contentOverflowX }, geometry.bodyOverflowX === 0 && geometry.contentOverflowX <= 1);
        record(`${prefix}__targets`, 'all visible controls >=44x44', geometry.smallTargets, geometry.smallTargets.length === 0);
        record(`${prefix}__shell`, '0 legacy shell nodes', geometry.legacyShells, geometry.legacyShells === 0);
        const allowedScrollers = geometry.scrollable.every((item) =>
          String(item.className).includes('v34c-content') || String(item.className).includes('v34c-rail'));
        record(`${prefix}__scroll`, 'only feature content and desktop navigation rail may scroll', geometry.scrollable,
          allowedScrollers && geometry.scrollable.filter((item) => String(item.className).includes('v34c-content')).length <= 1);
        if (viewport.name === 'mobile-390x844' || viewport.name === 'mobile-430x932') {
          const budget = mobileScrollLimits[state.id];
          record(`${prefix}__mobile-scroll-budget`, `<=${budget}px intentional vertical content overflow`, geometry.contentOverflowY,
            geometry.contentOverflowY <= budget);
        }

        if ((viewport.name === 'mobile-390x844' || viewport.name === 'desktop-1440x900')) {
          await page.addScriptTag({ content: axe.source });
          const axeResult = await page.evaluate(async () => {
            const result = await globalThis.axe.run(document, {
              runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
            });
            return result.violations.map((violation) => ({
              id: violation.id,
              impact: violation.impact,
              targets: violation.nodes.slice(0, 3).map((node) => node.target),
            }));
          });
          record(`${prefix}__axe`, '0 WCAG A/AA violations', axeResult, axeResult.length === 0);
        }
        await page.screenshot({ path: resolve(screenshotsDir, `${prefix}.png`), fullPage: false });
      }
      record(`${viewport.name}__${theme}__runtime`, '0 console/page/request/HTTP/unmatched-API errors', runtime,
        runtime.consoleErrors.length === 0
        && runtime.pageErrors.length === 0
        && runtime.failedRequests.length === 0
        && runtime.httpErrors.length === 0
        && runtime.unmatchedApi.length === 0);
      await context.close();
    }
  }

  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const functionalRuntime = createRuntimeEvidence();
  attachRuntimeEvidence(page, functionalRuntime);
  const functionalSavedIds = new Set(['cam']);
  await installApiContract(page, functionalRuntime, functionalSavedIds);

  await page.goto(`${base}/s-13`);
  await waitForDocumentReady(page);
  const resume = page.getByRole('button', { name: 'Continue step 2' });
  await resume.waitFor({ state: 'visible' });
  await Promise.all([
    page.waitForURL((url) => url.pathname === '/s-10' && url.search === '?step=academic'),
    resume.click(),
  ]);
  await waitForDocumentReady(page);
  record('S-13_resume_branch', 'first incomplete step routes to S-10 academic', new URL(page.url()).pathname + new URL(page.url()).search,
    new URL(page.url()).pathname === '/s-10' && new URL(page.url()).search === '?step=academic');

  await page.goto(`${base}/s-15`);
  await waitForDocumentReady(page);
  const email = page.getByLabel('Institutional email');
  const send = page.getByRole('button', { name: 'Send verification link' });
  const institutionalEmailError = 'Enter a valid institutional email of 254 characters or fewer — e.g. aditi.nair@nls.ac.in';
  for (const invalid of [
    { name: 'empty', value: '' },
    { name: 'malformed', value: 'student@nlsiu' },
    { name: 'overlength_255', value: `${'a'.repeat(245)}@nls.ac.in` },
  ]) {
    await email.fill(invalid.value);
    await send.click();
    const alertText = await page.getByRole('alert').allTextContents();
    const sentVisible = await page.getByText('Verification link sent — check your inbox.').isVisible().catch(() => false);
    const errorMatched = alertText.some((text) => text.includes(institutionalEmailError));
    record(
      `S-15_${invalid.name}`,
      'invalid institutional email rejected without a success state',
      { errorMatched, sentVisible },
      errorMatched && !sentVisible,
    );
  }
  await email.fill('student@gmail.com');
  await send.click();
  const consumerErrorVisible = await page.getByText(institutionalEmailError).isVisible();
  record('S-15_consumer_email', 'consumer domain rejected', { errorVisible: consumerErrorVisible }, consumerErrorVisible);
  await email.fill('student@nls.ac.in');
  const academicEmailValue = await email.inputValue();
  record(
    'S-15_academic_email',
    'academic domain clears local validation',
    { accepted: academicEmailValue === 'student@nls.ac.in', valueLength: academicEmailValue.length },
    academicEmailValue === 'student@nls.ac.in',
  );

  const browseResponses = [
    page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/internships')),
    page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved')),
  ];
  await page.goto(`${base}/s-20`);
  const completedBrowseResponses = await waitForInternshipStateReady(page, browseResponses);
  await waitForDocumentReady(page);
  record('S-20_api_ready', 'catalogue and saved-list GETs finish with HTTP 200 before interaction', completedBrowseResponses,
    completedBrowseResponses.length === 2
      && completedBrowseResponses.every((item) => item.status === 200 && item.finishedError === null));
  const search = page.getByRole('searchbox', { name: 'Search internships' });
  await search.fill('not-a-real-placement');
  record('S-20_empty_search', 'truthful no-results state', await page.getByText('No matching listings').isVisible(),
    await page.getByText('No matching listings').isVisible());

  const menonResponses = [
    page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/internships/menon')),
    page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved')),
  ];
  await page.goto(`${base}/s-21?listing=menon`);
  const completedMenonResponses = await waitForInternshipStateReady(page, menonResponses);
  await waitForDocumentReady(page);
  record('S-21_menon_identity', 'stable menon identity renders Judicial research assistant, never CAM fallback', {
    url: page.url(), responses: completedMenonResponses,
  }, await page.getByRole('heading', { name: 'Judicial research assistant' }).isVisible()
    && new URL(page.url()).searchParams.get('listing') === 'menon'
    && completedMenonResponses.every((item) => item.status === 200 && item.finishedError === null));

  const saveMenonResponse = page.waitForResponse((response) => isExactApiResponse(response, 'PUT', '/api/v1/student/internships/menon/saved'));
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const completedSaveMenon = await finishResponse(await saveMenonResponse);
  await page.getByRole('status').filter({ hasText: 'Saved privately to your account.' }).waitFor({ state: 'visible' });
  record('S-21_save_identity', 'PUT saves exactly menon to the account-backed list', completedSaveMenon,
    completedSaveMenon.status === 200 && completedSaveMenon.finishedError === null && functionalSavedIds.has('menon'));

  const savedMenonResponse = page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved'));
  await page.goto(`${base}/s-25`);
  const completedSavedMenon = await waitForInternshipStateReady(page, [savedMenonResponse]);
  await waitForDocumentReady(page);
  const menonSavedRow = page.getByRole('listitem').filter({ hasText: 'Judicial research assistant' });
  record('S-25_saved_identity', 'fresh saved-list GET contains the menon identity', completedSavedMenon,
    await menonSavedRow.isVisible() && completedSavedMenon[0]?.status === 200 && completedSavedMenon[0]?.finishedError === null);
  const removeMenonResponse = page.waitForResponse((response) => isExactApiResponse(response, 'DELETE', '/api/v1/student/internships/menon/saved'));
  await menonSavedRow.getByRole('button', { name: 'Remove' }).click();
  const completedRemoveMenon = await finishResponse(await removeMenonResponse);
  record('S-25_remove_identity', 'DELETE removes exactly menon without changing CAM', completedRemoveMenon,
    completedRemoveMenon.status === 200 && completedRemoveMenon.finishedError === null
      && !functionalSavedIds.has('menon') && functionalSavedIds.has('cam'));

  const vidhiResponses = [
    page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/internships/vidhi')),
    page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved')),
  ];
  await page.goto(`${base}/s-21?listing=vidhi`);
  const completedVidhiResponses = await waitForInternshipStateReady(page, vidhiResponses);
  await waitForDocumentReady(page);
  record('S-21_vidhi_deep_link', 'direct vidhi identity renders Research fellowship, policy after exact GET', completedVidhiResponses,
    await page.getByRole('heading', { name: 'Research fellowship, policy' }).isVisible()
      && completedVidhiResponses.every((item) => item.status === 200 && item.finishedError === null));

  const bareDetailSavedResponse = page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/student/internships/saved'));
  await page.goto(`${base}/s-21`);
  await finishResponse(await bareDetailSavedResponse);
  await waitForDocumentReady(page);
  const missingDetailAlert = page.getByRole('alert').filter({ hasText: 'Listing unavailable' });
  record('S-21_missing_identity', 'truthful unavailable state with no CAM fallback', await page.getByRole('alert').allTextContents(),
    await missingDetailAlert.isVisible()
      && await page.getByRole('heading', { name: 'Summer Associate, disputes' }).count() === 0);

  await page.goto(`${base}/s-22`);
  await waitForDocumentReady(page);
  const missingApplyAlert = page.getByRole('alert').filter({ hasText: 'Listing unavailable' });
  record('S-22_missing_identity', 'truthful unavailable state with no CAM fallback', await page.getByRole('alert').allTextContents(),
    await missingApplyAlert.isVisible()
      && await page.getByText('Cyril Amarchand Mangaldas · Summer Associate, disputes').count() === 0);

  const applyDetailResponse = page.waitForResponse((response) => isExactApiResponse(response, 'GET', '/api/v1/internships/cam'));
  await page.goto(`${base}/s-22?listing=cam`);
  const completedApplyDetail = await waitForInternshipStateReady(page, [applyDetailResponse]);
  await waitForDocumentReady(page);
  record('S-22_cam_identity_ready', 'exact CAM detail GET finishes with HTTP 200 before application testing', completedApplyDetail,
    completedApplyDetail[0]?.status === 200 && completedApplyDetail[0]?.finishedError === null);
  const cover = page.getByLabel('Cover note');
  const continueDocuments = page.getByRole('button', { name: 'Continue to documents' });
  await cover.fill('A'.repeat(49));
  await continueDocuments.click();
  record('S-22_cover_49', '49 chars rejected', await page.getByRole('alert').allTextContents(), await page.getByText('Cover note must be at least 50 characters.').isVisible());
  await cover.fill('A'.repeat(50));
  await continueDocuments.click();
  record('S-22_cover_50', '50 chars accepted', await page.getByRole('heading', { name: 'Documents' }).isVisible(), await page.getByRole('heading', { name: 'Documents' }).isVisible());

  const resumeInput = page.getByLabel('Résumé (PDF)');
  const transcriptInput = page.getByLabel('Transcript (PDF)');
  await resumeInput.setInputFiles({ name: 'resume.txt', mimeType: 'text/plain', buffer: Buffer.from('not a pdf') });
  await transcriptInput.setInputFiles({ name: 'transcript.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(0) });
  await page.getByRole('button', { name: 'Review application' }).click();
  const uploadErrors = await page.getByRole('alert').allTextContents();
  record('S-22_upload_type_empty', 'non-PDF and empty PDF rejected', uploadErrors,
    uploadErrors.some((text) => text.includes('must be a PDF')) && uploadErrors.some((text) => text.includes('file is empty')));
  await resumeInput.setInputFiles({ name: 'resume.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(5 * 1024 * 1024, 1) });
  await transcriptInput.setInputFiles({ name: 'transcript.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(5 * 1024 * 1024 + 1, 1) });
  await page.getByRole('button', { name: 'Review application' }).click();
  record('S-22_upload_5mb_boundary', '5 MB accepted and 5 MB + 1 rejected', await page.getByRole('alert').allTextContents(),
    !(await page.getByText('Resume must be 5 MB or smaller.').isVisible()) && await page.getByText('Transcript must be 5 MB or smaller.').isVisible());

  await page.goto(`${base}/s-19`);
  await waitForDocumentReady(page);
  await page.locator('details.v34c-mobile-disclosure').filter({ hasText: 'Data rights' }).locator('summary').click();
  const deleteToggle = page.getByRole('button', { name: 'Delete…' });
  await deleteToggle.click();
  record('S-19_delete_reauth_gate', 'delete cannot be submitted before re-authentication',
    { deleteButtons: await page.getByRole('button', { name: 'Delete my account' }).count() },
    await page.getByRole('button', { name: 'Delete my account' }).count() === 0);

  const storagePrivacy = await page.evaluate(() => {
    const local = { ...localStorage };
    const session = { ...sessionStorage };
    const serialized = JSON.stringify({ local, session, cookies: document.cookie }).toLowerCase();
    const forbiddenKey = /(?:access[_-]?token|auth[_-]?token|session[_-]?token|onboarding[_-]?(?:token|capability)|authorization|bearer|password|otp|secret)/i;
    const credentialValue = /(?:\bBearer\s+[A-Za-z0-9._~-]{12,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|\b[A-Za-z0-9_-]{48,}\b)/;
    const visibleCookieNames = document.cookie
      .split(';')
      .map((entry) => entry.trim().split('=', 1)[0])
      .filter(Boolean)
      .sort();
    const values = Object.values({ ...local, ...session }).map((value) => String(value ?? ''));
    return {
      localKeys: Object.keys(local).sort(),
      sessionKeys: Object.keys(session).sort(),
      visibleCookieNames,
      privateFixtureLeak: serialized.includes('9876543210')
        || serialized.includes('student@nls.ac.in')
        || serialized.includes('aditi'),
      credentialKeyLeak: [...Object.keys(local), ...Object.keys(session)].some((key) => forbiddenKey.test(key)),
      credentialValueLeak: values.some((value) => credentialValue.test(value)),
      authCookieVisible: visibleCookieNames.some((name) => /(?:session|auth|token|bearer)/i.test(name)),
    };
  });
  record(
    'browser_storage_privacy',
    'no raw mobile, OTP, credentials or private profile values in browser storage',
    storagePrivacy,
    storagePrivacy.privateFixtureLeak === false
      && storagePrivacy.credentialKeyLeak === false
      && storagePrivacy.credentialValueLeak === false
      && storagePrivacy.authCookieVisible === false,
  );
  record('functional_runtime', '0 console/page/request/HTTP/unmatched-API errors', functionalRuntime,
    functionalRuntime.consoleErrors.length === 0
    && functionalRuntime.pageErrors.length === 0
    && functionalRuntime.failedRequests.length === 0
    && functionalRuntime.httpErrors.length === 0
    && functionalRuntime.unmatchedApi.length === 0);
  await context.close();
} finally {
  await browser.close();
}

const summary = {
  total: rows.length,
  passed: rows.filter((row) => row.pass).length,
  failed: rows.filter((row) => !row.pass).length,
  screenshots: (await readdir(screenshotsDir)).filter((name) => name.endsWith('.png')).length,
  rows,
};
await writeFile(resolve(evidenceDir, 'results.json'), `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
await writeFile(resolve(evidenceDir, 'summary.txt'), [
  'LegalSaathi v3.4 S-11-S-26 production integration',
  `total=${summary.total}`,
  `passed=${summary.passed}`,
  `failed=${summary.failed}`,
  `screenshots=${summary.screenshots}`,
].join('\n') + '\n', 'utf8');

const evidenceFiles = [
  'results.json',
  'summary.txt',
  ...(await readdir(screenshotsDir)).sort().map((name) => `screenshots/${name}`),
];
const checksums = [];
for (const relativePath of evidenceFiles) {
  const digest = createHash('sha256').update(await readFile(resolve(evidenceDir, relativePath))).digest('hex');
  checksums.push(`${digest}  ${relativePath}`);
}
await writeFile(resolve(evidenceDir, 'SHA256SUMS.txt'), `${checksums.join('\n')}\n`, 'utf8');
console.log(JSON.stringify({ total: summary.total, passed: summary.passed, failed: summary.failed, screenshots: summary.screenshots, evidenceDir }, null, 2));
if (summary.failed > 0) process.exitCode = 1;
