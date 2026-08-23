import { chromium } from 'playwright';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

const base = process.env.QA_BASE_URL ?? 'http://127.0.0.1:1043';
const capture = process.env.QA_OTP_CAPTURE_URL ?? 'http://127.0.0.1:1099';
const evidence = process.env.QA_EVIDENCE_DIR ?? path.resolve('../QA/registration_closure');
const ignoreHTTPSErrors = process.env.QA_ALLOW_SELF_SIGNED_TLS === 'true';
await fs.mkdir(evidence, { recursive: true });

const results = [];
const browserRuntimeErrors = [];
let browserContextSequence = 0;
const record = (name, expected, actual, pass, evidenceFile = null) => {
  results.push({ name, expected, actual, pass, evidence: evidenceFile });
  if (!pass) throw new Error(`${name}: expected ${expected}; actual ${actual}`);
};
const latestOtp = async () => {
  for (let i = 0; i < 30; i += 1) {
    const response = await fetch(`${capture}/latest`);
    const value = await response.json();
    if (/^\d{6}$/.test(value.code ?? '')) return value.code;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('OTP provider did not receive a code');
};
const resetOtp = async () => {
  const response = await fetch(`${capture}/reset`, { method: 'POST' });
  if (!response.ok) throw new Error('OTP capture reset failed');
};
const browser = await chromium.launch({ headless: true });
const qaNonce = createHash('sha256')
  .update(`${Date.now()}-${process.pid}-${Math.random()}`)
  .digest('hex');
const qaLetters = qaNonce.slice(0, 10)
  .split('')
  .map((character) => String.fromCharCode(97 + Number.parseInt(character, 16)))
  .join('');
const qaDigits = qaNonce
  .split('')
  .map((character) => String(Number.parseInt(character, 16) % 10))
  .join('');
const qaDobMonth = String((Number.parseInt(qaNonce.slice(12, 14), 16) % 12) + 1).padStart(2, '0');
const qaDobDay = String((Number.parseInt(qaNonce.slice(14, 16), 16) % 28) + 1).padStart(2, '0');
const qaPii = {
  first: `Qavira${qaLetters.slice(0, 4)}`,
  middle: `Zorena${qaLetters.slice(3, 7)}`,
  last: `Pellorin${qaLetters.slice(6, 10)}`,
  mobile: `8${qaDigits.slice(0, 9)}`,
  dob: `${1998 + (Number.parseInt(qaNonce.slice(10, 12), 16) % 6)}-${qaDobMonth}-${qaDobDay}`,
  email: `nyay2.qa.${qaNonce.slice(0, 12)}@nls.ac.in`,
  enrolment: `KA/${qaDigits.slice(9, 15)}/2023`,
  barEnrolment: `MH/${qaDigits.slice(15, 21)}/2024`,
  pronouns: `Ze ${qaLetters.slice(0, 6)}`,
};

async function fresh(viewport = { width: 1440, height: 1000 }) {
  browserContextSequence += 1;
  const contextLabel = `context-${browserContextSequence}`;
  const context = await browser.newContext({ viewport, ignoreHTTPSErrors });
  const page = await context.newPage();
  const consoleErrors = [];
  const networkErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (error) => browserRuntimeErrors.push(`${contextLabel}: ${error.message}`));
  page.on('response', (r) => { if (r.status() >= 400) networkErrors.push(`${r.status()} ${r.url()}`); });
  return { context, page, consoleErrors, networkErrors };
}

async function fillBase(page, {
  first = 'Aditi', middle = '', last = 'Nair', mobile = '9876543210', dob = '2004-03-14',
  email = 'aditi@nls.ac.in',
} = {}) {
  await page.goto(`${base}/s-08`);
  await page.getByLabel('FIRST NAME').fill(first);
  await page.getByLabel('MIDDLE NAME').fill(middle);
  await page.getByLabel('LAST NAME').fill(last);
  await page.getByLabel('MOBILE NUMBER', { exact: true }).fill(mobile);
  await page.getByLabel('INSTITUTIONAL EMAIL').fill(email);
  await page.getByLabel('DATE OF BIRTH', { exact: true }).fill(dob);
  await page.getByLabel('COLLEGE OR UNIVERSITY').selectOption('NLSIU');
  await page.getByLabel('YEAR OF STUDY').selectOption('3');
  await page.getByRole('checkbox', { name: /enrolled in, or applying to/ }).check();
  await page.getByRole('checkbox', { name: /accept the terms and DPDP/ }).check();
}

// Explicit negative/boundary cases.
for (const [name, values, expected] of [
  ['mobile_9_digits', { mobile: '987654321' }, 'Mobile number must be exactly 10 digits.'],
  ['mobile_11_digits', { mobile: '98765432101' }, 'Mobile number must be exactly 10 digits.'],
  ['mobile_12_digits', { mobile: '987654321012' }, 'Mobile number must be exactly 10 digits.'],
  ['future_dob', { mobile: '9000000001', dob: '2030-01-01' }, 'Enter a valid date of birth that is not in the future.'],
  ['empty_first_name', { mobile: '9000000002', first: '' }, 'Enter your first name.'],
  ['empty_last_name', { mobile: '9000000008', last: '' }, 'Enter your last name.'],
]) {
  const { context, page } = await fresh();
  await fillBase(page, values);
  await page.getByRole('button', { name: 'Send one time code' }).click();
  const text = await page.locator('body').innerText();
  record(name, expected, text.includes(expected), text.includes(expected));
  record(`${name}_blocked`, 'remain /s-08', new URL(page.url()).pathname, new URL(page.url()).pathname === '/s-08');
  await context.close();
}

// Name-character validation must target the correct split field.
{
  const { context, page } = await fresh();
  const outcomes = {};
  const blocked = {};
  for (const field of ['first', 'middle', 'last']) {
    await fillBase(page, { mobile: '9000000003', [field]: '<script>' });
    await page.getByRole('button', { name: 'Send one time code' }).click();
    outcomes[field] = (await page.locator('body').innerText()).includes('contains characters');
    blocked[field] = new URL(page.url()).pathname === '/s-08';
  }
  record('special_name_all_fields', 'first/middle/last reject special characters on the correct field', outcomes,
    Object.values(outcomes).every(Boolean));
  record('special_name_all_fields_blocked', 'every invalid split-name submission remains /s-08', blocked,
    Object.values(blocked).every(Boolean));
  await context.close();
}

// The UI must not silently truncate maximum+1; the domain validator owns the error.
{
  const { context, page } = await fresh();
  const outcomes = {};
  for (const [field, label] of [['first', 'FIRST NAME'], ['middle', 'MIDDLE NAME'], ['last', 'LAST NAME']]) {
    await fillBase(page, { mobile: '9000000004', [field]: 'A'.repeat(61) });
    const attemptedLength = (await page.getByLabel(label).inputValue()).length;
    await page.getByRole('button', { name: 'Send one time code' }).click();
    outcomes[field] = {
      attemptedLength,
      correctError: (await page.locator('body').innerText()).includes('60 characters or fewer'),
      path: new URL(page.url()).pathname,
    };
  }
  record('name_61_chars_all_fields', '61 retained then rejected for first/middle/last; no truncation', outcomes,
    Object.values(outcomes).every((value) => value.attemptedLength === 61 && value.correctError && value.path === '/s-08'));
  await context.close();
}

// Maximum allowed boundary: exactly 60 characters in every split field is accepted.
{
  const { context, page } = await fresh();
  await fillBase(page, { first: 'A'.repeat(60), middle: 'B'.repeat(60), last: 'C'.repeat(60), mobile: '9000000005' });
  await page.getByRole('button', { name: 'Send one time code' }).click();
  await page.waitForURL('**/s-09');
  record('name_60_chars_all_fields', 'exactly 60 first/middle/last accepted and routed to /s-09', new URL(page.url()).pathname,
    new URL(page.url()).pathname === '/s-09');
  await context.close();
}

// Full v3.4 S-08 -> server OTP S-09 -> S-10 backend profile persistence.
{
  const { context, page, consoleErrors, networkErrors } = await fresh();
  const requests = [];
  const protectedRequests = [];
  let registrationPayload = null;
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/auth/student/')) {
      const url = new URL(r.url());
      requests.push(`${r.method()} ${url.pathname}`);
      if (r.url().includes('/api/v1/auth/student/register')) registrationPayload = r.postDataJSON();
      if (
        url.pathname.endsWith('/profile')
        || url.pathname.endsWith('/verification/email/request')
        || url.pathname.endsWith('/verification/status')
      ) {
        protectedRequests.push({
          method: r.method(),
          path: url.pathname,
          origin: url.origin,
          url: url.href,
          body: r.postData() ?? '',
          headerNames: Object.keys(r.headers()),
        });
      }
    }
  });
  await fillBase(page, {
    first: qaPii.first,
    middle: qaPii.middle,
    last: qaPii.last,
    mobile: qaPii.mobile,
    dob: qaPii.dob,
    email: qaPii.email,
  });
  await resetOtp();

  const send = page.getByRole('button', { name: 'Send one time code' });
  const iconContract = await send.evaluate((button) => ({
    aria: button.getAttribute('aria-label'),
    tip: button.getAttribute('data-tip'),
    svg: button.querySelectorAll('svg').length,
  }));
  record('icon_tooltip_contract', 'icon CTA exposes matching accessible name and tooltip text', iconContract,
    iconContract.aria === 'Send one time code' && iconContract.tip === iconContract.aria && iconContract.svg === 1);

  const registrationResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/register'
  ));
  await send.click();
  const registrationResponse = await registrationResponsePromise;
  const registrationResult = await registrationResponse.json();
  record(
    'registration_response_safe_flow_projection',
    'pre-auth response contains relative state and no correlation identifier',
    registrationResult,
    registrationResult?.status === 'pending'
      && registrationResult?.purpose === 'signup'
      && Number.isInteger(registrationResult?.attempts_left)
      && Number.isInteger(registrationResult?.expires_in_seconds)
      && !/(?:registration|login|recovery)(?:_(?:id|token)|(?:Id|Token))/.test(JSON.stringify(registrationResult)),
  );
  await page.waitForURL('**/s-09');
  const otpControl = page.locator('input[aria-label="Six digit code"]');
  await otpControl.waitFor({ state: 'visible' });
  const otpControlCount = await otpControl.count();
  const decorativeSlotCount = await page.locator('.v34-otp > span[aria-hidden="true"]').count();
  record(
    'single_otp_control',
    'one real OTP input and six aria-hidden visual slots',
    { otpControlCount, decorativeSlotCount },
    otpControlCount === 1 && decorativeSlotCount === 6,
  );
  const otp = await latestOtp();
  const incorrectOtp = otp === '000000' ? '111111' : '000000';
  await otpControl.fill(incorrectOtp);
  const incorrectOtpResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/otp/verify'
      && response.status() === 401
  ));
  await page.getByRole('button', { name: 'Verify and continue' }).click();
  const incorrectOtpResponse = await incorrectOtpResponsePromise;
  const incorrectOtpBody = await incorrectOtpResponse.json();
  const expectedIncorrectOtpNetworkError = `401 ${incorrectOtpResponse.url()}`;
  await page.getByRole('alert').filter({ hasText: 'That code could not be verified' }).waitFor();
  const serverAttemptsLeft = incorrectOtpBody?.detail?.otp_state?.attempts_left;
  let displayedAttemptsMatch = false;
  if (Number.isInteger(serverAttemptsLeft)) {
    try {
      await page.locator('.v34-kv')
        .filter({ hasText: `Tries left ${serverAttemptsLeft}` })
        .waitFor({ state: 'visible', timeout: 2_000 });
      displayedAttemptsMatch = true;
    } catch {
      // Kept false for the fail-closed record below.
    }
  }
  const retryContext = {
    path: new URL(page.url()).pathname,
    serverCode: incorrectOtpBody?.detail?.code,
    serverAttemptsLeft,
    displayedAttemptsMatch,
    destinationRetained: (await page.locator('.v34-lede').innerText()).includes(qaPii.mobile.slice(-3)),
    resendControlPresent: await page.locator('.v34-textlink').count() === 1,
  };
  record(
    'incorrect_otp_preserves_retry_context',
    '401 incorrect_otp retains the cookie-owned flow, server attempt count and resend control',
    JSON.stringify(retryContext),
    retryContext.path === '/s-09'
      && retryContext.serverCode === 'incorrect_otp'
      && retryContext.serverAttemptsLeft === 2
      && retryContext.displayedAttemptsMatch
      && retryContext.destinationRetained
      && retryContext.resendControlPresent,
  );
  await otpControl.fill(otp);
  await page.getByRole('button', { name: 'Verify and continue' }).click();
  await page.waitForURL('**/s-10');
  const splitNamePayloadValid = registrationPayload?.first_name === qaPii.first
    && registrationPayload?.middle_name === qaPii.middle
    && registrationPayload?.last_name === qaPii.last
    && registrationPayload?.full_name === undefined;
  record('profile_name_split', 'First/Middle/Last are mapped independently to the API payload',
    {
      valid: splitNamePayloadValid,
      fieldKeys: Object.keys(registrationPayload ?? {}).sort(),
      firstLength: registrationPayload?.first_name?.length ?? 0,
      middleLength: registrationPayload?.middle_name?.length ?? 0,
      lastLength: registrationPayload?.last_name?.length ?? 0,
      legacyFullNamePresent: registrationPayload?.full_name !== undefined,
    },
    splitNamePayloadValid);
  await page.getByLabel('CITY').selectOption('Bengaluru');
  await page.getByLabel('PRONOUNS').fill(qaPii.pronouns);
  await page.getByRole('button', { name: 'Continue to academics' }).click();
  await page.waitForURL('**/s-10?step=academic');

  for (const label of [
    'College / University',
    'Year of study',
    'College enrolment number',
    'Institutional email',
    'Bar enrolment number',
  ]) {
    record(`legacy_field_${label}`, 'present and interactable', label, await page.getByLabel(label).isEnabled());
  }
  await page.getByLabel('College / University').selectOption({ label: 'National Law School of India University (NLSIU)' });
  await page.getByLabel('Year of study').selectOption({ label: '3rd year' });
  await page.getByLabel('College enrolment number').fill(qaPii.enrolment);
  await page.getByLabel('Institutional email').fill(qaPii.email);
  await page.getByLabel('Bar enrolment number').fill(qaPii.barEnrolment);
  // Evidence screenshots must never contain even synthetic raw identity data.
  // Clear the controlled inputs for capture, then restore them for the already
  // asserted server persistence step that follows.
  await page.getByLabel('College / University').selectOption('');
  await page.getByLabel('Year of study').selectOption('');
  await page.getByLabel('College enrolment number').fill('');
  await page.getByLabel('Institutional email').fill('');
  await page.getByLabel('Bar enrolment number').fill('');
  await page.screenshot({ path: path.join(evidence, 's10_academic_fields_v34.png'), fullPage: true });
  await page.getByLabel('College / University').selectOption({ label: 'National Law School of India University (NLSIU)' });
  await page.getByLabel('Year of study').selectOption({ label: '3rd year' });
  await page.getByLabel('College enrolment number').fill(qaPii.enrolment);
  await page.getByLabel('Institutional email').fill(qaPii.email);
  await page.getByLabel('Bar enrolment number').fill(qaPii.barEnrolment);
  await page.getByRole('button', { name: /Save & continue/ }).click();
  await page.waitForURL('**/s-11');

  // Exercise every protected student-owned contract that must derive the
  // registration from the authenticated HttpOnly session. Merely watching
  // for these paths would let a removed request false-green this oracle.
  await page.goto(`${base}/s-15`);
  await page.getByLabel('Institutional email').fill(qaPii.email);
  await page.getByRole('button', { name: 'Send verification link' }).click();
  await page.getByRole('status').filter({ hasText: 'Verification link sent' }).waitFor();
  const emailRequest = protectedRequests.find((request) => (
    request.method === 'POST'
      && request.path === '/api/v1/auth/student/verification/email/request'
  ));
  record(
    'verification_email_backend_observed',
    'POST /verification/email/request reaches the configured API origin',
    { observed: Boolean(emailRequest), origin: emailRequest?.origin ?? null },
    Boolean(emailRequest),
  );
  const statusUrl = new URL('/api/v1/auth/student/verification/status', emailRequest.url).href;
  const statusResult = await page.evaluate(async (url) => {
    const response = await fetch(url, {
      credentials: 'include',
    });
    const contentType = response.headers.get('content-type') ?? '';
    const text = await response.text();
    let body = null;
    try {
      body = JSON.parse(text);
    } catch {
      // An SPA fallback can also return HTTP 200. A non-JSON response must not
      // masquerade as the authenticated backend contract.
    }
    return { status: response.status, contentType, body };
  }, statusUrl);
  record(
    'verification_status_api_success',
    'configured API returns authenticated JSON status for GET /verification/status',
    statusResult,
    statusResult.status === 200
      && /application\/json/i.test(statusResult.contentType)
      && statusResult.body?.status === 'pending'
      && statusResult.body?.method === 'institutional_email',
  );

  const storage = await page.evaluate(async ({ canaries }) => {
    const registrationKey = 'legalsaathi.student.registration.v2';
    const allowedLocalKeys = new Set(['nyayone.theme.v1']);
    const allowedSessionKeys = new Set();
    const forbiddenKey = /(?:access[_-]?token|auth[_-]?token|session[_-]?token|onboarding[_-]?(?:token|capability)|authorization|bearer|password|otp|secret)/i;
    const credentialValue = /(?:\bBearer\s+[A-Za-z0-9._~-]{12,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|\b[A-Za-z0-9_-]{48,}\b)/;
    const local = Object.fromEntries(Object.keys(localStorage).map((key) => [key, localStorage.getItem(key)]));
    const session = Object.fromEntries(Object.keys(sessionStorage).map((key) => [key, sessionStorage.getItem(key)]));
    const cookie = document.cookie;
    const url = location.href;
    const windowName = window.name;
    const historyState = history.state;
    const cacheEntries = [];
    if ('caches' in window) {
      for (const cacheName of await caches.keys()) {
        const cache = await caches.open(cacheName);
        for (const request of await cache.keys()) {
          const response = await cache.match(request);
          let value = '';
          let readable = true;
          if (response) {
            try {
              value = await response.clone().text();
            } catch {
              readable = false;
            }
          }
          cacheEntries.push({ cacheName, requestUrl: request.url, value, readable });
        }
      }
    }
    const serviceWorker = 'serviceWorker' in navigator
      ? {
          controller: navigator.serviceWorker.controller?.scriptURL ?? '',
          registrations: (await navigator.serviceWorker.getRegistrations()).map((entry) => ({
            scope: entry.scope,
            active: entry.active?.scriptURL ?? '',
            waiting: entry.waiting?.scriptURL ?? '',
            installing: entry.installing?.scriptURL ?? '',
          })),
        }
      : { controller: '', registrations: [] };
    const managedSerialized = JSON.stringify({
      local,
      session,
      cookie,
      url,
      windowName,
      historyState,
      cacheMetadata: cacheEntries.map(({ cacheName, requestUrl }) => ({ cacheName, requestUrl })),
      serviceWorker,
    });
    const cachedPayloadSerialized = JSON.stringify(cacheEntries.map(({ value }) => value));
    const serialized = `${managedSerialized}\n${cachedPayloadSerialized}`;
    const browserValues = [
      ...Object.values({ ...local, ...session }),
      cookie,
      url,
      windowName,
      JSON.stringify(historyState),
    ].map((value) => String(value ?? ''));
    const uuid = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i;
    return {
      localKeys: Object.keys(local).sort(),
      sessionKeys: Object.keys(session).sort(),
      cacheEntryCount: cacheEntries.length,
      unreadableCacheEntryCount: cacheEntries.filter((entry) => !entry.readable).length,
      serviceWorkerRegistrationCount: serviceWorker.registrations.length,
      windowNameEmpty: windowName === '',
      historyStateHasCanary: canaries.some((value) => JSON.stringify(historyState).includes(value)),
      piiLeak: canaries.some((value) => serialized.includes(value)),
      unexpectedLocalKeys: Object.keys(local).filter((key) => !allowedLocalKeys.has(key)),
      unexpectedSessionKeys: Object.keys(session).filter((key) => !allowedSessionKeys.has(key)),
      credentialKeyLeak: [...Object.keys(local), ...Object.keys(session)].some((key) => forbiddenKey.test(key)),
      credentialValueLeak: browserValues.some((value) => credentialValue.test(value)),
      registrationCapabilityLeak: registrationKey in local
        || registrationKey in session
        || managedSerialized.includes(registrationKey)
        || uuid.test(managedSerialized),
    };
  }, { canaries: Object.values(qaPii) });
  const allCookies = await context.cookies();
  const allCookiePiiLeak = allCookies.some((cookie) => (
    Object.values(qaPii).some((canary) => cookie.value.includes(canary))
  ));
  const cookieInventory = allCookies.map((cookie) => ({
    name: cookie.name,
    domain: cookie.domain,
    path: cookie.path,
    httpOnly: cookie.httpOnly,
    secure: cookie.secure,
    sameSite: cookie.sameSite,
    valueLength: cookie.value.length,
  }));
  record('no_browser_pii', 'no runtime-unique name/mobile/DOB/academic PII in storage, caches, history, window.name, any cookie or service-worker metadata',
    { ...storage, allCookiePiiLeak },
    storage.piiLeak === false
      && allCookiePiiLeak === false
      && storage.credentialKeyLeak === false
      && storage.credentialValueLeak === false
      && storage.unexpectedLocalKeys.length === 0
      && storage.unexpectedSessionKeys.length === 0
      && storage.unreadableCacheEntryCount === 0
      && storage.windowNameEmpty === true
      && storage.historyStateHasCanary === false);
  record('no_registration_capability_persistence', 'no OTP-flow identifier is exposed to JavaScript storage, caches, history, window.name, URL or service-worker metadata',
    {
      sessionKeys: storage.sessionKeys,
      cacheEntryCount: storage.cacheEntryCount,
      unreadableCacheEntryCount: storage.unreadableCacheEntryCount,
      serviceWorkerRegistrationCount: storage.serviceWorkerRegistrationCount,
      cookieInventory,
      leak: storage.registrationCapabilityLeak,
    },
    storage.registrationCapabilityLeak === false
      && storage.unreadableCacheEntryCount === 0);
  const uuid = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i;
  const protectedActorReferenceLeak = protectedRequests.some((request) => (
    [...new URL(request.url).searchParams.keys()].some((key) => /registration[_-]?id/i.test(key))
      || request.headerNames.some((name) => /registration[_-]?id/i.test(name))
      || /["']registration[_-]?id["']\s*:/i.test(request.body)
      || uuid.test(`${request.url} ${request.body}`)
  ));
  const expectedProtectedCalls = [
    'PATCH /api/v1/auth/student/profile',
    'POST /api/v1/auth/student/verification/email/request',
    'GET /api/v1/auth/student/verification/status',
  ];
  const protectedCallInventory = protectedRequests.map((request) => `${request.method} ${request.path}`);
  const missingProtectedCalls = expectedProtectedCalls.filter((call) => !protectedCallInventory.includes(call));
  const wrongOriginCalls = protectedRequests
    .filter((request) => expectedProtectedCalls.includes(`${request.method} ${request.path}`))
    .filter((request) => request.origin !== emailRequest.origin)
    .map((request) => `${request.method} ${request.path}`);
  record('protected_calls_use_server_actor', 'profile/email/status each execute at the configured API origin without registration_id field, query, header or UUID',
    { protectedActorReferenceLeak, missingProtectedCalls, wrongOriginCalls },
    protectedActorReferenceLeak === false
      && missingProtectedCalls.length === 0
      && wrongOriginCalls.length === 0);
  record('registration_api_called', 'POST /register', requests, requests.some((r) => r.includes('POST /api/v1/auth/student/register')));
  record('otp_api_called', 'POST /otp/verify', requests, requests.some((r) => r.includes('POST /api/v1/auth/student/otp/verify')));
  record('profile_api_called', 'PATCH /profile', requests, requests.some((r) => r.includes('PATCH /api/v1/auth/student/profile')));
  const expectedIncorrectOtpConsoleMessage = 'Failed to load resource: the server responded with a status of 401 (Unauthorized)';
  const expectedIncorrectOtpConsoleCount = consoleErrors.filter(
    (entry) => entry === expectedIncorrectOtpConsoleMessage,
  ).length;
  const unexpectedConsoleErrors = consoleErrors.filter(
    (entry) => entry !== expectedIncorrectOtpConsoleMessage,
  );
  record(
    'console_errors',
    'exactly one Chromium resource message for the asserted incorrect-OTP 401 and no other console errors',
    { expectedIncorrectOtpConsoleCount, unexpectedConsoleErrors },
    expectedIncorrectOtpConsoleCount === 1 && unexpectedConsoleErrors.length === 0,
  );
  const expectedIncorrectOtpErrorCount = networkErrors.filter(
    (entry) => entry === expectedIncorrectOtpNetworkError,
  ).length;
  const unexpectedNetworkErrors = networkErrors.filter(
    (entry) => entry !== expectedIncorrectOtpNetworkError,
  );
  record(
    'network_errors',
    'exactly one expected typed incorrect-OTP 401 and no other HTTP errors',
    { expectedIncorrectOtpErrorCount, unexpectedNetworkErrors },
    expectedIncorrectOtpErrorCount === 1 && unexpectedNetworkErrors.length === 0,
  );
  const file = 's08_s10_full_flow_v34.png';
  await page.getByLabel('Institutional email').fill('');
  await page.screenshot({ path: path.join(evidence, file), fullPage: true });
  await context.close();
}

// v3.4 S-06 recovery is mobile/OTP based and server-authoritative.
{
  const { context, page } = await fresh();
  const calls = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/auth/student/recovery/')) calls.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  await page.goto(`${base}/s-06`);
  await page.getByLabel('MOBILE NUMBER', { exact: true }).fill(qaPii.mobile);
  await resetOtp();
  await page.getByRole('button', { name: 'Send the code' }).click();
  await page.getByText('If an account matches, a six digit recovery code has been sent.').waitFor();
  const recoveryCode = page.getByLabel('6-DIGIT RECOVERY CODE');
  // Prove that the server-owned pending projection has rendered before waiting
  // on the independent provider capture. This preserves the exact oracle while
  // preventing provider scheduling from hiding a transient UI regression.
  await recoveryCode.waitFor({ state: 'visible' });
  await recoveryCode.fill(await latestOtp());
  await page.getByRole('button', { name: 'Verify recovery code' }).click();
  await page.getByText('Recovery verified. You may now sign in again.').waitFor();
  record('recovery_server_start', 'POST /recovery/start', calls,
    calls.some((r) => r.includes('POST /api/v1/auth/student/recovery/start')));
  record('recovery_server_verify', 'POST /recovery/verify', calls,
    calls.some((r) => r.includes('POST /api/v1/auth/student/recovery/verify')));
  record('recovery_server_complete', 'POST /recovery/complete', calls,
    calls.some((r) => r.includes('POST /api/v1/auth/student/recovery/complete')));
  record('recovery_no_email_redirect', 'remain /s-06', new URL(page.url()).pathname,
    new URL(page.url()).pathname === '/s-06');
  await page.getByLabel('MOBILE NUMBER', { exact: true }).fill('');
  // Completion retires the verified recovery flow, so the code control must
  // disappear instead of remaining editable on the acknowledgement state.
  await recoveryCode.waitFor({ state: 'detached' });
  await page.screenshot({ path: path.join(evidence, 's06_recovery_complete_v34.png'), fullPage: true });
  await context.close();
}

// Responsive/theme and icon-tooltip contract matrix.
for (const width of [390, 430, 768, 1024, 1440]) {
  for (const theme of ['light', 'dark']) {
    const { context, page, consoleErrors } = await fresh({ width, height: 1000 });
    await page.addInitScript((value) => localStorage.setItem('nyayone.theme.v1', value), theme);
    await fillBase(page, { mobile: `91${String(width).padStart(8, '0')}`.slice(0, 10) });
    const action = page.getByRole('button', { name: 'Send one time code' });
    const helpButton = page.getByRole('button', { name: 'More information about MOBILE NUMBER' });
    await helpButton.focus();
    const tooltip = page.getByRole('tooltip');
    await tooltip.waitFor({ state: 'visible' });
    const tooltipText = (await tooltip.textContent() ?? '').trim();
    await page.keyboard.press('Escape');
    const tooltipDismissed = await tooltip.isHidden();
    const actionBox = await action.boundingBox();
    const metrics = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      iconActions: [...document.querySelectorAll('.v34-iconbtn')].map((element) => {
        const box = element.getBoundingClientRect();
        return { width: box.width, height: box.height, aria: element.getAttribute('aria-label'), tip: element.getAttribute('data-tip'), svg: element.querySelectorAll('svg').length };
      }),
    }));
    record(`responsive_${width}_${theme}`, `width<=${width}, icon CTA inside viewport and target>=44`,
      { metrics, actionBox },
      metrics.width <= width
      && metrics.iconActions.every((item) => item.width >= 44 && item.height >= 44 && item.aria && item.tip === item.aria && item.svg === 1)
      && tooltipText === 'Exactly 10 digits. The one time code is sent here.' && tooltipDismissed
      && !!actionBox && actionBox.x >= 0 && actionBox.x + actionBox.width <= width
      && consoleErrors.length === 0);
    const file = `s08_v34_${width}_${theme}.png`;
    for (const label of [
      'FIRST NAME',
      'MIDDLE NAME',
      'LAST NAME',
      'MOBILE NUMBER',
      'INSTITUTIONAL EMAIL',
      'DATE OF BIRTH',
    ]) {
      await page.getByLabel(label, { exact: true }).fill('');
    }
    await page.getByLabel('COLLEGE OR UNIVERSITY').selectOption('');
    await page.getByLabel('YEAR OF STUDY').selectOption('');
    await page.screenshot({ path: path.join(evidence, file), fullPage: true });
    await context.close();
  }
}

// Retired /auth/student prototype must fail closed and direct users to the
// canonical server-owned flow without mounting any client-owned OTP controls.
{
  const { context, page } = await fresh();
  const calls = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/auth/student/')) calls.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  await page.goto(`${base}/auth/student`);
  await page.getByRole('heading', { name: 'This legacy sign-in route is unavailable' }).waitFor();
  const secureLink = page.getByRole('link', { name: 'Use secure student sign-in' });
  const sessionDiscoveryOnly = calls.length > 0
    && calls.every((call) => call === 'GET /api/v1/auth/student/session');
  record('auth_student_legacy_route_fail_closed', 'legacy route denies, links only to /s-03 and permits read-only session discovery only',
    { href: await secureLink.getAttribute('href'), calls },
    await secureLink.getAttribute('href') === '/s-03' && sessionDiscoveryOnly);
  record('auth_student_no_client_otp_controls', 'no registration or OTP inputs mount',
    await page.locator('input').count(), await page.locator('input').count() === 0);
  record('no_stub_otp_visible', '429016 absent', await page.locator('body').innerText(),
    !(await page.locator('body').innerText()).includes('429016'));
  await context.close();
}

record('browser_page_errors', 'no uncaught browser exceptions in any registration scenario', browserRuntimeErrors,
  browserRuntimeErrors.length === 0);
await browser.close();
const report = {
  generatedAt: new Date().toISOString(),
  base,
  passed: results.filter((r) => r.pass).length,
  failed: results.filter((r) => !r.pass).length,
  results,
};
await fs.writeFile(path.join(evidence, 'registration_e2e_report.json'), JSON.stringify(report, null, 2));
const manifestFiles = (await fs.readdir(evidence, { withFileTypes: true }))
  .filter((entry) => entry.isFile() && entry.name !== 'SHA256SUMS.txt')
  .map((entry) => entry.name)
  .sort();
const manifest = [];
for (const file of manifestFiles) {
  const digest = createHash('sha256').update(await fs.readFile(path.join(evidence, file))).digest('hex');
  manifest.push(`${digest}  ${file}`);
}
await fs.writeFile(path.join(evidence, 'SHA256SUMS.txt'), `${manifest.join('\n')}\n`, 'utf8');
console.log(JSON.stringify({ passed: report.passed, failed: report.failed, evidence }, null, 2));
