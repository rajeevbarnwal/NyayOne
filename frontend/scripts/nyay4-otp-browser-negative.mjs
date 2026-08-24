import { createHash } from 'node:crypto';
import { chromium } from 'playwright';
import {
  containsFlowHandle,
  hasExactOrderedOriginTrace,
  hasExactOtpReload,
  hasExactSingleOrigin,
  inspectOtpViewSnapshot,
  summarizeNyay4Rows,
} from './lib/nyay4-otp-runner-contract.mjs';
import {
  inspectRegistrationStartWire,
  inspectOtpVerificationWire,
} from './lib/nyay5-profile-browser-contract.mjs';

const WEB = process.env.NYAY4_WEB_BASE_URL ?? 'http://127.0.0.1:4174';
const API = process.env.NYAY4_API_BASE_URL ?? 'http://127.0.0.1:1131';
const CAPTURE = process.env.NYAY4_OTP_CAPTURE_URL ?? 'http://127.0.0.1:1099';
const WEB_ORIGIN = new URL(WEB).origin;

const rows = [];
const record = (name, expected, actual, pass) => rows.push({ name, expected, actual, pass });
const safeKeys = [
  'status', 'purpose', 'destination_masked', 'attempts_left',
  'expires_in_seconds', 'resend_in_seconds', 'locked_for_seconds',
  'resend_allowed',
];
const REAUTHENTICATED_BADGE_SELECTOR = '.status.status--ok';
const REAUTHENTICATED_BADGE_LABEL = 'Re-authenticated';

async function waitForReauthenticatedBadge(targetPage) {
  const badges = targetPage.locator(REAUTHENTICATED_BADGE_SELECTOR);
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const matchingIndexes = await badges.evaluateAll((elements, expectedLabel) => (
      elements.flatMap((element, index) => {
        const labelOnly = element.cloneNode(true);
        labelOnly.querySelectorAll('[aria-hidden="true"]').forEach((node) => node.remove());
        return labelOnly.textContent?.trim() === expectedLabel ? [index] : [];
      })
    ), REAUTHENTICATED_BADGE_LABEL);
    if (matchingIndexes.length > 1) {
      throw new Error('NYAY4_REAUTHENTICATED_BADGE_AMBIGUOUS');
    }
    if (matchingIndexes.length === 1
        && await badges.nth(matchingIndexes[0]).isVisible()) return;
    await targetPage.waitForTimeout(50);
  }
  throw new Error('NYAY4_REAUTHENTICATED_BADGE_NOT_VISIBLE');
}

async function readOtpViewSnapshot(targetPage, expectedAttempts, expectedDestinationMasked) {
  const screen = targetPage.locator('[data-screen="S-09"]');
  const cards = screen.locator('.v34-card.v34-kv');
  const ledes = screen.locator('.v34-lede');
  await cards.filter({ hasText: `Tries left ${expectedAttempts}` }).waitFor({ state: 'visible' });
  const [cardCount, rowTexts, ledeCount, ledeTexts] = await Promise.all([
    cards.count(),
    cards.locator(':scope > span').allTextContents(),
    ledes.count(),
    ledes.allTextContents(),
  ]);
  return inspectOtpViewSnapshot(
    { cardCount, rowTexts, ledeCount, ledeText: ledeTexts[0] },
    expectedAttempts,
    expectedDestinationMasked,
  );
}

async function resolveCapturedMutations(captured) {
  return Promise.all(captured.map(async ({ request, ...metadata }) => ({
    ...metadata,
    originExact: await hasExactSingleOrigin(request, WEB_ORIGIN),
  })));
}

async function resetCapture() {
  const response = await fetch(`${CAPTURE}/reset`, { method: 'POST' });
  if (!response.ok) throw new Error(`OTP capture reset failed: ${response.status}`);
}

async function latestOtp(mobile) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const response = await fetch(`${CAPTURE}/latest`);
    const payload = await response.json();
    if (payload.to === mobile && /^\d{6}$/.test(payload.code ?? '')) return payload.code;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('OTP capture did not receive the expected signup code');
}

function privacySafeFailureCode(body) {
  const candidate = body?.detail?.code;
  return typeof candidate === 'string' && /^[a-z][a-z0-9_]{0,63}$/u.test(candidate)
    ? candidate
    : 'untyped';
}

async function fulfillStateFailure(route) {
  await route.fulfill({
    status: 503,
    contentType: 'application/json',
    headers: {
      'Access-Control-Allow-Origin': WEB_ORIGIN,
      'Access-Control-Allow-Credentials': 'true',
    },
    body: JSON.stringify({ detail: { code: 'synthetic_state_unavailable' } }),
  });
}

function safeProjection(body, status, purpose) {
  if (!body
      || body.status !== status
      || body.purpose !== purpose
      || Object.keys(body).sort().join(',') !== [...safeKeys].sort().join(',')
      || typeof body.resend_allowed !== 'boolean'
      || containsFlowHandle(body)) return false;
  const relative = [
    body.attempts_left,
    body.expires_in_seconds,
    body.resend_in_seconds,
    body.locked_for_seconds,
  ];
  if (status === 'pending') {
    if (!['signup', 'login', 'recovery'].includes(purpose)
        || !/^••••••\d{4}$/u.test(body.destination_masked)
        || !relative.every((value) => Number.isSafeInteger(value) && value >= 0)) return false;
    return !body.resend_allowed || (
      body.resend_in_seconds === 0
      && body.locked_for_seconds === 0
      && body.attempts_left > 0
    );
  }
  if (body.destination_masked !== null || !relative.every((value) => value === null) || body.resend_allowed) {
    return false;
  }
  if (status === 'verified') return purpose === 'recovery';
  if (status === 'authenticated') return purpose === 'signup' || purpose === 'login';
  return status === 'unavailable' && purpose === null;
}

function normalizedProjection(body) {
  return Object.fromEntries(Object.entries(body)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => [key, key === 'destination_masked' ? '<masked>' : value]));
}

const nonce = createHash('sha256')
  .update(`${Date.now()}-${process.pid}-${Math.random()}`)
  .digest('hex');
const mobile = `8${nonce.split('').map((value) => Number.parseInt(value, 16) % 10).join('').slice(0, 9)}`;
const unknownMobile = `7${nonce.split('').reverse().map((value) => Number.parseInt(value, 16) % 10).join('').slice(0, 5)}${mobile.slice(-4)}`;
const idempotencyKey = `nyay4-browser-${nonce}`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await context.newPage();
const otpRequests = [];
page.on('request', (request) => {
  const path = new URL(request.url()).pathname;
  if (path.endsWith('/otp/verify') || path.endsWith('/otp/resend')) {
    let body = null;
    try { body = request.postDataJSON(); } catch { /* fail closed below */ }
    const bodyKeys = body && typeof body === 'object' ? Object.keys(body).sort() : [];
    otpRequests.push({
      request,
      method: request.method(),
      path,
      bodyKeys,
      codeOnly: bodyKeys.join(',') === 'code' && /^\d{6}$/.test(body.code ?? ''),
      emptyObject: bodyKeys.length === 0,
      identifierFree: !containsFlowHandle(body),
    });
  }
});

try {
  await resetCapture();
  const registration = await context.request.post(`${API}/api/v1/auth/student/register`, {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
      Origin: WEB_ORIGIN,
    },
    data: {
      first_name: 'Nyay',
      middle_name: null,
      last_name: 'Browser',
      mobile,
      dob: '2004-03-14',
      terms_accepted: true,
      terms_version: 'dpdp-2023.v1',
      privacy_notice_acknowledged: true,
      privacy_notice_version: 'dpdp-2023.v1',
    },
  });
  const registrationBody = await registration.json();
  const registrationAccepted = registration.status() === 202
    && inspectRegistrationStartWire(registrationBody).pass;
  if (!registrationAccepted) {
    throw new Error(
      `NYAY4_SIGNUP_FIXTURE_REJECTED_${registration.status()}_${privacySafeFailureCode(registrationBody)}`,
    );
  }
  const signupStateResponse = await context.request.get(
    `${API}/api/v1/auth/student/otp/state`,
  );
  const signupStateBody = await signupStateResponse.json();
  const signupStateAccepted = signupStateResponse.status() === 200
    && safeProjection(signupStateBody, 'pending', 'signup');
  record(
    'signup-safe-projection',
    'HTTP 202 accepted bootstrap followed by authoritative pending/signup state',
    {
      registrationStatus: registration.status(),
      registrationKeys: Object.keys(registrationBody ?? {}).sort(),
      stateStatus: signupStateResponse.status(),
      stateKeys: Object.keys(signupStateBody ?? {}).sort(),
      purpose: signupStateBody?.purpose,
      relativeMetadataTypes: [
        signupStateBody?.attempts_left,
        signupStateBody?.expires_in_seconds,
        signupStateBody?.resend_in_seconds,
        signupStateBody?.locked_for_seconds,
      ].map((value) => typeof value),
    },
    registrationAccepted && signupStateAccepted,
  );
  if (!signupStateAccepted) {
    throw new Error(`NYAY4_SIGNUP_STATE_REJECTED_${signupStateResponse.status()}`);
  }

  let code = await latestOtp(mobile);
  const initialAttempts = signupStateBody.attempts_left;
  const wrongCode = code === '000000' ? '111111' : '000000';
  const allCookies = await context.cookies();
  const flowCookies = allCookies.filter((cookie) => cookie.name === 'nyayone_otp_flow');
  const cookieInventory = allCookies
    .map((cookie) => ({
      name: cookie.name,
      domain: cookie.domain,
      path: cookie.path,
      httpOnly: cookie.httpOnly,
      secure: cookie.secure,
      sameSite: cookie.sameSite,
      opaque: cookie.value.length >= 32
        && !cookie.value.includes(mobile)
        && !cookie.value.includes(code)
        && !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(cookie.value),
    }));
  const flowCookieInventory = cookieInventory.filter((cookie) => cookie.name === 'nyayone_otp_flow');
  const unexpectedAuthorityCookies = cookieInventory.filter((cookie) => (
    cookie.name !== 'nyayone_otp_flow'
      && /(?:otp|flow|auth|session|token|bearer)/i.test(cookie.name)
  ));
  const apiHost = new URL(API).hostname;
  const localHttp = new URL(API).protocol === 'http:'
    && ['127.0.0.1', 'localhost', '::1'].includes(apiHost);
  record(
    'otp-flow-cookie-security',
    'one host-only opaque HttpOnly SameSite=Strict /api/v1 cookie; Secure false only on local HTTP',
    flowCookieInventory,
    cookieInventory.length === 1
      && flowCookieInventory.length === 1
      && flowCookieInventory[0].domain === apiHost
      && !flowCookieInventory[0].domain.startsWith('.')
      && flowCookieInventory[0].path === '/api/v1'
      && flowCookieInventory[0].httpOnly
      && flowCookieInventory[0].sameSite === 'Strict'
      && flowCookieInventory[0].secure === !localHttp
      && flowCookieInventory[0].opaque
      && unexpectedAuthorityCookies.length === 0,
  );
  record(
    'full-preauth-cookie-inventory',
    'the complete browser inventory is exactly one OTP flow cookie before verification',
    {
      total: cookieInventory.length,
      metadata: cookieInventory.map(({ name, domain, path, httpOnly, secure, sameSite }) => (
        { name, domain, path, httpOnly, secure, sameSite }
      )),
      unexpectedAuthorityCookieNames: unexpectedAuthorityCookies.map((cookie) => cookie.name),
    },
    cookieInventory.length === 1
      && flowCookies.length === 1
      && unexpectedAuthorityCookies.length === 0,
  );

  // Seed forbidden legacy state, then prove the real page bootstrap removes it
  // and restores the authoritative flow solely from the HttpOnly cookie.
  await page.addInitScript(() => {
    localStorage.setItem('legalsaathi.student.profile.v1', '{"legacy":true}');
    localStorage.setItem('ls-auth-student', '{"phase":"otp_entry","challenge":{"code":"planted"}}');
    sessionStorage.setItem('legalsaathi.student.registration.v2', '{"legacy":true}');
  });
  await page.goto(`${WEB}/s-09`, { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Six digit code').waitFor({ state: 'visible' });
  const beforeReload = await readOtpViewSnapshot(
    page,
    initialAttempts,
    signupStateBody.destination_masked,
  );
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByLabel('Six digit code').waitFor({ state: 'visible' });
  const afterReload = await readOtpViewSnapshot(
    page,
    initialAttempts,
    signupStateBody.destination_masked,
  );
  record(
    'reload-server-state',
    'reload retains server attempts/destination and relative countdown without JS handle',
    {
      structureExactBefore: beforeReload.structureExact,
      structureExactAfter: afterReload.structureExact,
      resendRowExactBefore: beforeReload.resendRowExact,
      resendRowExactAfter: afterReload.resendRowExact,
      attemptsMatchBefore: beforeReload.attemptsExact,
      attemptsMatchAfter: afterReload.attemptsExact,
      destinationMatchBefore: beforeReload.destinationExact,
      destinationMatchAfter: afterReload.destinationExact,
      countdownValidBefore: beforeReload.countdownValid,
      countdownValidAfter: afterReload.countdownValid,
      countdownNonIncreasing: Number.isSafeInteger(afterReload.countdownSeconds)
        && Number.isSafeInteger(beforeReload.countdownSeconds)
        && afterReload.countdownSeconds <= beforeReload.countdownSeconds,
    },
    hasExactOtpReload(beforeReload, afterReload),
  );

  // A successful pending snapshot becomes unusable on any later failed state
  // read. Disabled DOM controls must emit no mutation; a subsequent successful
  // poll restores only the freshly returned server projection.
  let failPendingStateReads = false;
  await page.route('**/api/v1/auth/student/otp/state', async (route) => {
    if (failPendingStateReads) await fulfillStateFailure(route);
    else await route.continue();
  });
  await page.getByLabel('Six digit code').fill(wrongCode);
  const pendingMutationsBeforeFailure = otpRequests.length;
  const pendingFailurePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/v1/auth/student/otp/state'
      && response.status() === 503
  ));
  failPendingStateReads = true;
  await pendingFailurePromise;
  await page.getByText('Verification state is unavailable.', { exact: false }).waitFor({ state: 'visible' });
  const verifyButton = page.getByRole('button', { name: 'Verify and continue', exact: true });
  const resendButton = page.getByRole('button', { name: 'Resend Code', exact: true });
  const pendingFailureUi = {
    codeReset: await page.getByLabel('Six digit code').inputValue() === '',
    verifyDisabled: await verifyButton.isDisabled(),
    resendDisabled: await resendButton.isDisabled(),
  };
  await resendButton.evaluate((button) => button.click());
  await verifyButton.evaluate((button) => button.click());
  await page.waitForTimeout(250);
  record(
    'pending-refresh-failure-invalidation',
    'a later GET 503 clears pending state/code, disables verify+resend, and emits no mutation',
    {
      ...pendingFailureUi,
      mutationCountUnchanged: otpRequests.length === pendingMutationsBeforeFailure,
    },
    pendingFailureUi.codeReset
      && pendingFailureUi.verifyDisabled
      && pendingFailureUi.resendDisabled
      && otpRequests.length === pendingMutationsBeforeFailure,
  );

  const pendingRecoveryPromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/v1/auth/student/otp/state'
      && response.status() === 200
  ));
  failPendingStateReads = false;
  const pendingRecoveryResponse = await pendingRecoveryPromise;
  const pendingRecoveryBody = await pendingRecoveryResponse.json();
  await page.getByText('Verification state is unavailable.', { exact: false }).waitFor({ state: 'hidden' });
  await page.locator('.v34-kv').filter({ hasText: `Tries left ${initialAttempts}` }).waitFor();
  await page.getByLabel('Six digit code').fill(wrongCode);
  const pendingVerifyRecovered = !(await verifyButton.isDisabled());
  record(
    'pending-refresh-recovery',
    'a later successful GET restores the strict pending projection and permits code-shaped verify',
    {
      projectionValid: safeProjection(pendingRecoveryBody, 'pending', 'signup'),
      verifyRecovered: pendingVerifyRecovered,
    },
    safeProjection(pendingRecoveryBody, 'pending', 'signup') && pendingVerifyRecovered,
  );

  const wrongResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/otp/verify')
      && response.status() >= 400
  ));
  await verifyButton.click();
  const wrongResponse = await wrongResponsePromise;
  const wrongBody = await wrongResponse.json();
  const wrongState = wrongBody?.detail?.otp_state;
  const wrongOriginExact = await hasExactSingleOrigin(wrongResponse.request(), WEB_ORIGIN);
  record(
    'wrong-code-server-budget',
    'typed error carries the decremented server budget and relative state',
    {
      status: wrongResponse.status(),
      code: wrongBody?.detail?.code,
      attemptsLeft: wrongState?.attempts_left,
      keys: Object.keys(wrongState ?? {}).sort(),
      originExact: wrongOriginExact,
    },
    wrongBody?.detail?.code === 'incorrect_otp'
      && safeProjection(wrongState, 'pending', 'signup')
      && wrongState.attempts_left === initialAttempts - 1
      && wrongOriginExact,
  );

  // Wait for a fresh GET /otp/state to grant resend, then exercise the actual
  // rendered control. No test-side fetch may manufacture this mutation.
  await resendButton.click({ trial: true, timeout: 45_000 });
  await resetCapture();
  const resendResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/otp/resend')
  ));
  await resendButton.click();
  const resendResponse = await resendResponsePromise;
  const resendBody = await resendResponse.json();
  const otpRequestsAfterResend = await resolveCapturedMutations(otpRequests);
  record(
    'real-authoritative-resend',
    'real Resend control receives HTTP 202 and a fresh strict pending projection',
    {
      status: resendResponse.status(),
      projectionValid: safeProjection(resendBody, 'pending', 'signup'),
      requestObserved: otpRequestsAfterResend.some((request) => request.path.endsWith('/otp/resend')),
    },
    resendResponse.status() === 202
      && safeProjection(resendBody, 'pending', 'signup')
      && otpRequestsAfterResend.some((request) => request.path.endsWith('/otp/resend')
        && request.emptyObject && request.identifierFree && request.originExact),
  );
  code = await latestOtp(mobile);
  record(
    'identifier-free-browser-mutations',
    'verify sends code only and resend sends an empty object',
    otpRequestsAfterResend,
    otpRequestsAfterResend.some((request) => request.path.endsWith('/otp/verify')
      && request.codeOnly && request.identifierFree && request.originExact)
      && otpRequestsAfterResend.some((request) => request.path.endsWith('/otp/resend')
        && request.emptyObject && request.identifierFree && request.originExact),
  );

  const successPromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/otp/verify')
      && response.status() === 200
  ));
  await page.getByLabel('Six digit code').fill(code);
  await page.getByRole('button', { name: 'Verify and continue' }).click();
  const successResponse = await successPromise;
  const successBody = await successResponse.json();
  const successOriginExact = await hasExactSingleOrigin(successResponse.request(), WEB_ORIGIN);
  record(
    'successful-cookie-owned-verify',
    'correct code authenticates from the HttpOnly flow without a client handle',
    {
      status: successBody?.status,
      purpose: successBody?.purpose,
      keys: Object.keys(successBody ?? {}).sort(),
      originExact: successOriginExact,
    },
    successBody?.status === 'authenticated'
      && successBody?.purpose === 'signup'
      && inspectOtpVerificationWire(successBody).pass
      && successOriginExact,
  );
  const postAuthCookies = await context.cookies();
  const postAuthAuthorityCookies = postAuthCookies.filter((cookie) => (
    /(?:otp|flow|auth|session|token|bearer)/i.test(cookie.name)
  ));
  record(
    'post-auth-cookie-inventory',
    'exactly one host-only opaque HttpOnly SameSite=Strict /api/v1 session cookie remains',
    {
      total: postAuthCookies.length,
      authorityCookies: postAuthAuthorityCookies.map((cookie) => ({
        name: cookie.name,
        domain: cookie.domain,
        path: cookie.path,
        httpOnly: cookie.httpOnly,
        secure: cookie.secure,
        sameSite: cookie.sameSite,
        opaque: cookie.value.length >= 32
          && !cookie.value.includes(mobile)
          && !cookie.value.includes(code),
      })),
    },
    postAuthCookies.length === 1
      && postAuthAuthorityCookies.length === 1
      && postAuthAuthorityCookies[0].name === 'nyayone_session'
      && postAuthAuthorityCookies[0].domain === apiHost
      && !postAuthAuthorityCookies[0].domain.startsWith('.')
      && postAuthAuthorityCookies[0].path === '/api/v1'
      && postAuthAuthorityCookies[0].httpOnly
      && postAuthAuthorityCookies[0].sameSite === 'Strict'
      && postAuthAuthorityCookies[0].secure === !localHttp
      && postAuthAuthorityCookies[0].value.length >= 32
      && !postAuthAuthorityCookies[0].value.includes(mobile)
      && !postAuthAuthorityCookies[0].value.includes(code)
      && !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(postAuthAuthorityCookies[0].value),
  );
  await context.request.post(`${API}/api/v1/auth/student/logout`, {
    headers: { Origin: WEB_ORIGIN },
    data: {},
  });

  const managed = await page.evaluate(({ rawMobile, rawOtp }) => {
    const local = Object.fromEntries(Object.keys(localStorage).map((key) => [key, localStorage.getItem(key)]));
    const session = Object.fromEntries(Object.keys(sessionStorage).map((key) => [key, sessionStorage.getItem(key)]));
    const serialised = JSON.stringify({ local, session, history: history.state, name: window.name, cookie: document.cookie });
    const visibleCookieNames = document.cookie
      .split(';')
      .map((entry) => entry.trim().split('=', 1)[0])
      .filter(Boolean)
      .sort();
    return {
      localKeys: Object.keys(local).sort(),
      sessionKeys: Object.keys(session).sort(),
      visibleCookieNames,
      flowCookieVisible: visibleCookieNames.includes('nyayone_otp_flow'),
      readableAuthorityCookie: visibleCookieNames.some((name) => /(?:otp|flow|auth|session|token|bearer)/i.test(name)),
      hasRawValue: serialised.includes(rawMobile) || serialised.includes(rawOtp),
      hasFlowMetadata: /(?:registration|login|recovery)(?:_(?:id|token)|(?:Id|Token))|attempts_left|expires_in_seconds|locked_for_seconds|resend_in_seconds/.test(serialised),
      legacyKey: 'legalsaathi.student.registration.v2' in session
        || 'legalsaathi.student.profile.v1' in local
        || 'ls-auth-student' in local,
    };
  }, { rawMobile: mobile, rawOtp: code });
  record(
    'no-browser-flow-persistence',
    'no raw mobile/OTP, flow handle, counter, timestamp or HttpOnly cookie in JS-managed state',
    managed,
    !managed.hasRawValue && !managed.hasFlowMetadata && !managed.legacyKey
      && !managed.flowCookieVisible && !managed.readableAuthorityCookie,
  );

  // Known/decoy starts use separate contexts so their cookie-owned flows do not
  // replace one another. Compare only the public contract, never timing claims.
  await resetCapture();
  const knownContext = await browser.newContext();
  const decoyContext = await browser.newContext();
  const [knownResponse, decoyResponse] = await Promise.all([
    knownContext.request.post(`${API}/api/v1/auth/student/login/otp/start`, {
      headers: { Origin: WEB_ORIGIN }, data: { mobile },
    }),
    decoyContext.request.post(`${API}/api/v1/auth/student/login/otp/start`, {
      headers: { Origin: WEB_ORIGIN }, data: { mobile: unknownMobile },
    }),
  ]);
  const knownBody = await knownResponse.json();
  const decoyBody = await decoyResponse.json();
  record(
    'known-decoy-public-contract',
    'known and same-suffix decoy login starts match every public value after destination normalization',
    {
      knownStatus: knownResponse.status(),
      decoyStatus: decoyResponse.status(),
      knownKeys: Object.keys(knownBody ?? {}).sort(),
      decoyKeys: Object.keys(decoyBody ?? {}).sort(),
      normalizedExactMatch: JSON.stringify(normalizedProjection(knownBody))
        === JSON.stringify(normalizedProjection(decoyBody)),
      sameMaskedSuffix: knownBody?.destination_masked?.slice(-4)
        === decoyBody?.destination_masked?.slice(-4),
    },
    knownResponse.status() === decoyResponse.status()
      && safeProjection(knownBody, 'pending', 'login')
      && safeProjection(decoyBody, 'pending', 'login')
      && Object.keys(knownBody).sort().join(',') === Object.keys(decoyBody).sort().join(',')
      && knownBody.destination_masked.slice(-4) === decoyBody.destination_masked.slice(-4)
      && JSON.stringify(normalizedProjection(knownBody))
        === JSON.stringify(normalizedProjection(decoyBody)),
  );

  // Authenticate the disposable known account, then prove the S-19 recovery
  // proof survives a reload, is consumed by confirmation-only deletion, and
  // cannot be replayed. Values remain memory-only and are never reported.
  const loginCode = await latestOtp(mobile);
  const loginVerifyResponse = await knownContext.request.post(
    `${API}/api/v1/auth/student/login/otp/verify`,
    { headers: { Origin: WEB_ORIGIN }, data: { code: loginCode } },
  );
  const loginVerifyBody = await loginVerifyResponse.json();
  record(
    'disposable-account-login',
    'known account authenticates through identifier-free cookie-owned login verify',
    {
      status: loginVerifyResponse.status(),
      projectionValid: inspectOtpVerificationWire(loginVerifyBody).pass,
    },
    loginVerifyResponse.status() === 200
      && loginVerifyBody?.purpose === 'login'
      && inspectOtpVerificationWire(loginVerifyBody).pass,
  );

  const privacyPage = await knownContext.newPage();
  const deleteRequests = [];
  const privacyMutations = [];
  privacyPage.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() !== 'POST' || ![
      '/api/v1/auth/student/recovery/start',
      '/api/v1/auth/student/recovery/verify',
      '/api/v1/student/privacy/delete',
    ].includes(path)) return;
    privacyMutations.push({ path, request });
    if (path !== '/api/v1/student/privacy/delete') return;
    let body = null;
    try { body = request.postDataJSON(); } catch { /* fail closed below */ }
    const bodyKeys = body && typeof body === 'object' ? Object.keys(body).sort() : [];
    deleteRequests.push({
      request,
      method: request.method(),
      path: new URL(request.url()).pathname,
      bodyKeys,
      confirmationOnly: bodyKeys.join(',') === 'confirmation' && body.confirmation === 'DELETE',
      identifierFree: !containsFlowHandle(body),
    });
  });
  const exposeDataRights = async () => {
    const disclosure = privacyPage.locator('details').filter({ hasText: 'Data rights' });
    if (await disclosure.count()) await disclosure.evaluate((element) => { element.open = true; });
  };

  await privacyPage.goto(`${WEB}/s-19`, { waitUntil: 'domcontentloaded' });
  await privacyPage.locator('[data-screen="S-19"]').waitFor({ state: 'visible' });
  await exposeDataRights();
  await privacyPage.getByRole('button', { name: 'Delete…' }).click();
  await privacyPage.getByLabel('Registered mobile number').fill(mobile);
  await resetCapture();
  const recoveryStartPromise = privacyPage.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/recovery/start'
  ));
  await privacyPage.getByRole('button', { name: 'Send code' }).click();
  const recoveryStartResponse = await recoveryStartPromise;
  const recoveryStartBody = await recoveryStartResponse.json();
  const recoveryCode = await latestOtp(mobile);
  const recoveryVerifyPromise = privacyPage.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/recovery/verify'
  ));
  await privacyPage.getByLabel('One-time code').fill(recoveryCode);
  await privacyPage.getByRole('button', { name: 'Verify code' }).click();
  const recoveryVerifyResponse = await recoveryVerifyPromise;
  const recoveryVerifyBody = await recoveryVerifyResponse.json();
  const recoveryOriginTraceExact = await hasExactOrderedOriginTrace(
    privacyMutations,
    [
      '/api/v1/auth/student/recovery/start',
      '/api/v1/auth/student/recovery/verify',
    ],
    WEB_ORIGIN,
  );
  record(
    'recovery-safe-verified-projection',
    'recovery start is pending and verify returns recovery-only verified state',
    {
      startStatus: recoveryStartResponse.status(),
      startProjectionValid: safeProjection(recoveryStartBody, 'pending', 'recovery'),
      verifyStatus: recoveryVerifyResponse.status(),
      verifyProjectionValid: safeProjection(recoveryVerifyBody, 'verified', 'recovery'),
      browserMutationCount: privacyMutations.length,
      browserOriginsExact: recoveryOriginTraceExact,
    },
    recoveryStartResponse.status() === 202
      && safeProjection(recoveryStartBody, 'pending', 'recovery')
      && recoveryVerifyResponse.status() === 200
      && safeProjection(recoveryVerifyBody, 'verified', 'recovery')
      && recoveryOriginTraceExact,
  );

  await waitForReauthenticatedBadge(privacyPage);
  await privacyPage.getByLabel('Type DELETE to confirm').fill('DELETE');
  let failRecoveryStateReads = false;
  await privacyPage.route('**/api/v1/auth/student/otp/state', async (route) => {
    if (failRecoveryStateReads) await fulfillStateFailure(route);
    else await route.continue();
  });
  const privacyMutationsBeforeFailure = privacyMutations.length;
  const recoveryFailurePromise = privacyPage.waitForResponse((response) => (
    response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/v1/auth/student/otp/state'
      && response.status() === 503
  ));
  failRecoveryStateReads = true;
  await recoveryFailurePromise;
  await privacyPage.getByText('Re-authentication state is unavailable.', { exact: false }).waitFor({ state: 'visible' });
  const recoveryFailureUi = {
    confirmationAbsent: await privacyPage.getByLabel('Type DELETE to confirm').count() === 0,
    deleteAbsent: await privacyPage.getByRole('button', { name: 'Delete my account' }).count() === 0,
    restartVisible: await privacyPage.getByLabel('Registered mobile number').isVisible(),
    restartDisabled: await privacyPage.getByRole('button', { name: 'Send code' }).isDisabled(),
  };
  await privacyPage.evaluate(() => {
    const button = [...document.querySelectorAll('button')]
      .find((candidate) => candidate.textContent?.includes('Delete my account'));
    if (button instanceof HTMLButtonElement) button.click();
  });
  await privacyPage.waitForTimeout(250);
  record(
    'recovery-refresh-failure-invalidation',
    'a later GET 503 clears verified proof UI and emits no deletion mutation',
    {
      ...recoveryFailureUi,
      mutationCountUnchanged: privacyMutations.length === privacyMutationsBeforeFailure,
    },
    recoveryFailureUi.confirmationAbsent
      && recoveryFailureUi.deleteAbsent
      && recoveryFailureUi.restartVisible
      && recoveryFailureUi.restartDisabled
      && privacyMutations.length === privacyMutationsBeforeFailure,
  );

  const recoveryStateRecoveryPromise = privacyPage.waitForResponse((response) => (
    response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/v1/auth/student/otp/state'
      && response.status() === 200
  ));
  failRecoveryStateReads = false;
  const recoveryStateRecoveryResponse = await recoveryStateRecoveryPromise;
  const recoveryStateRecoveryBody = await recoveryStateRecoveryResponse.json();
  await waitForReauthenticatedBadge(privacyPage);
  const recoveryConfirmationRecovered = await privacyPage.getByLabel('Type DELETE to confirm').isVisible();
  record(
    'recovery-refresh-recovery',
    'a later successful GET restores only the fresh strict verified recovery proof',
    {
      projectionValid: safeProjection(recoveryStateRecoveryBody, 'verified', 'recovery'),
      confirmationRecovered: recoveryConfirmationRecovered,
    },
    safeProjection(recoveryStateRecoveryBody, 'verified', 'recovery')
      && recoveryConfirmationRecovered,
  );

  await privacyPage.reload({ waitUntil: 'domcontentloaded' });
  await privacyPage.locator('[data-screen="S-19"]').waitFor({ state: 'visible' });
  await exposeDataRights();
  await privacyPage.getByRole('button', { name: 'Delete…' }).click();
  await waitForReauthenticatedBadge(privacyPage);
  record(
    'recovery-proof-reload',
    'reload restores verified confirmation stage solely through HttpOnly flow state',
    {
      confirmationFieldVisible: await privacyPage.getByLabel('Type DELETE to confirm').isVisible(),
      mobileFieldAbsent: await privacyPage.getByLabel('Registered mobile number').count() === 0,
      otpFieldAbsent: await privacyPage.getByLabel('One-time code').count() === 0,
    },
    await privacyPage.getByLabel('Type DELETE to confirm').isVisible()
      && await privacyPage.getByLabel('Registered mobile number').count() === 0
      && await privacyPage.getByLabel('One-time code').count() === 0,
  );

  await privacyPage.getByLabel('Type DELETE to confirm').fill('DELETE');
  const deletionResponsePromise = privacyPage.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/student/privacy/delete'
  ));
  await privacyPage.getByRole('button', { name: 'Delete my account' }).click();
  const deletionResponse = await deletionResponsePromise;
  const deletionBody = await deletionResponse.json();
  const consumedStateResponse = await knownContext.request.get(
    `${API}/api/v1/auth/student/otp/state`,
  );
  const consumedStateBody = await consumedStateResponse.json();
  const replayResponse = await knownContext.request.post(
    `${API}/api/v1/student/privacy/delete`,
    { headers: { Origin: WEB_ORIGIN }, data: { confirmation: 'DELETE' } },
  );
  const replayBody = await replayResponse.json();
  const resolvedDeleteRequests = await resolveCapturedMutations(deleteRequests);
  const privacyMutationTraceExact = await hasExactOrderedOriginTrace(
    privacyMutations,
    [
      '/api/v1/auth/student/recovery/start',
      '/api/v1/auth/student/recovery/verify',
      '/api/v1/student/privacy/delete',
    ],
    WEB_ORIGIN,
  );
  record(
    'deletion-proof-consumption',
    'S-19 sends confirmation only; proof becomes unavailable and replay is denied generically',
    {
      status: deletionResponse.status(),
      responseKeys: Object.keys(deletionBody ?? {}).sort(),
      requestShapeValid: resolvedDeleteRequests.length === 1
        && resolvedDeleteRequests[0].confirmationOnly
        && resolvedDeleteRequests[0].identifierFree,
      browserMutationCount: privacyMutations.length,
      browserMutationTraceExact: privacyMutationTraceExact,
      consumedStateStatus: consumedStateResponse.status(),
      consumedProjectionValid: safeProjection(consumedStateBody, 'unavailable', null),
      replayStatus: replayResponse.status(),
      replayCode: replayBody?.detail?.code,
    },
    deletionResponse.status() === 202
      && Object.keys(deletionBody ?? {}).sort().join(',') === 'request_id,status'
      && resolvedDeleteRequests.length === 1
      && resolvedDeleteRequests[0].confirmationOnly
      && resolvedDeleteRequests[0].identifierFree
      && resolvedDeleteRequests[0].originExact
      && privacyMutationTraceExact
      && consumedStateResponse.status() === 200
      && safeProjection(consumedStateBody, 'unavailable', null)
      && replayResponse.status() === 401
      && ['reauth_required', 'authentication_required'].includes(replayBody?.detail?.code),
  );

  const recoveryManaged = await privacyPage.evaluate(({ rawMobile, rawOtp }) => {
    const serialised = JSON.stringify({
      local: Object.fromEntries(Object.keys(localStorage).map((key) => [key, localStorage.getItem(key)])),
      session: Object.fromEntries(Object.keys(sessionStorage).map((key) => [key, sessionStorage.getItem(key)])),
      history: history.state,
      name: window.name,
      cookie: document.cookie,
    });
    const cookieNames = document.cookie.split(';').map((entry) => entry.trim().split('=', 1)[0]).filter(Boolean);
    return {
      rawValuePresent: serialised.includes(rawMobile) || serialised.includes(rawOtp),
      authorityMetadataPresent: /(?:registration|login|recovery)(?:_(?:id|token)|(?:Id|Token))|attempts_left|expires_in_seconds|locked_for_seconds|resend_in_seconds/.test(serialised),
      retiredStudentSnapshotPresent: localStorage.getItem('ls-auth-student') !== null,
      readableAuthorityCookie: cookieNames.some((name) => /(?:otp|flow|auth|session|token|bearer)/i.test(name)),
    };
  }, { rawMobile: mobile, rawOtp: recoveryCode });
  record(
    'recovery-browser-storage-privacy',
    'recovery contact/code/proof/counters remain absent from JS-managed state',
    recoveryManaged,
    !recoveryManaged.rawValuePresent
      && !recoveryManaged.authorityMetadataPresent
      && !recoveryManaged.retiredStudentSnapshotPresent
      && !recoveryManaged.readableAuthorityCookie,
  );
  await privacyPage.close();
  await knownContext.close();
  await decoyContext.close();

  // A planted pre-NYAY-4 snapshot cannot recreate authority without a cookie.
  const staleContext = await browser.newContext();
  await staleContext.addInitScript(() => {
    localStorage.setItem('ls-auth-student', JSON.stringify({
      phase: 'otp_entry', attemptsLeft: 3, code: 'planted', registration_id: 'planted',
    }));
  });
  const stalePage = await staleContext.newPage();
  await stalePage.goto(`${WEB}/auth/student`, { waitUntil: 'domcontentloaded' });
  await stalePage.locator('[data-screen="AUTH-FAIL-CLOSED"]').waitFor({ state: 'visible' });
  const retiredAtBoundary = await stalePage.evaluate(() => localStorage.getItem('ls-auth-student') === null);
  const unavailableResponsePromise = stalePage.waitForResponse((response) => (
    response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/v1/auth/student/otp/state'
  ));
  await stalePage.goto(`${WEB}/s-09`, { waitUntil: 'domcontentloaded' });
  const unavailableResponse = await unavailableResponsePromise;
  const unavailableBody = await unavailableResponse.json();
  const staleVerifyDisabled = await stalePage.getByRole('button', { name: 'Verify and continue' }).isDisabled();
  record(
    'stale-student-snapshot-no-cookie',
    'legacy route fails closed, key is retired, and unavailable server state cannot enable verify',
    {
      retiredAtBoundary,
      stateStatus: unavailableResponse.status(),
      unavailableProjectionValid: safeProjection(unavailableBody, 'unavailable', null),
      verifyDisabled: staleVerifyDisabled,
      flowCookies: (await staleContext.cookies(API)).filter((cookie) => cookie.name === 'nyayone_otp_flow').length,
    },
    retiredAtBoundary
      && unavailableResponse.status() === 200
      && safeProjection(unavailableBody, 'unavailable', null)
      && staleVerifyDisabled
      && (await staleContext.cookies(API)).filter((cookie) => cookie.name === 'nyayone_otp_flow').length === 0,
  );
  await staleContext.close();

  // A failed state bootstrap is also non-authoritative: no local fallback may
  // reconstruct a challenge or enable verify.
  const failedContext = await browser.newContext();
  await failedContext.addInitScript(() => {
    localStorage.setItem('ls-auth-student', '{"phase":"otp_entry","code":"planted"}');
  });
  const failedPage = await failedContext.newPage();
  await failedPage.route('**/api/v1/auth/student/otp/state', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      headers: {
        'Access-Control-Allow-Origin': WEB_ORIGIN,
        'Access-Control-Allow-Credentials': 'true',
      },
      body: JSON.stringify({ detail: { code: 'synthetic_state_unavailable' } }),
    });
  });
  await failedPage.goto(`${WEB}/s-09`, { waitUntil: 'domcontentloaded' });
  await failedPage.getByText('Verification state is unavailable.', { exact: false }).waitFor({ state: 'visible' });
  const failedState = {
    retired: await failedPage.evaluate(() => localStorage.getItem('ls-auth-student') === null),
    verifyDisabled: await failedPage.getByRole('button', { name: 'Verify and continue' }).isDisabled(),
  };
  record(
    'failed-state-bootstrap',
    'state transport failure retires legacy storage and leaves verification disabled',
    failedState,
    failedState.retired && failedState.verifyDisabled,
  );
  await failedContext.close();
} finally {
  await context.close();
  await browser.close();
}

const summary = summarizeNyay4Rows(rows);
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
if (summary.failed > 0) process.exitCode = 1;
