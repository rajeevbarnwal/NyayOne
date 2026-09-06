import { createHash, randomBytes } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { chromium } from 'playwright';
import {
  NYAY5_ASSERTION_INVENTORY,
  inspectAuthBoundaryObservation,
  inspectActorChannel,
  inspectBrowserPersistence,
  inspectBrowserExecutionCoverage,
  inspectConfirmedWriteObservation,
  inspectCrossRealmTransitionObservation,
  inspectCrossUserObservation,
  inspectCrossSectionConflictObservation,
  inspectDenialObservation,
  inspectDialogObservation,
  inspectGeometryObservation,
  inspectLegalNameCorpusObservation,
  inspectNyay5Projection,
  inspectOtpFlowWire,
  inspectOtpVerificationWire,
  inspectPendingSessionObservation,
  inspectPromptRotationObservation,
  inspectRegistrationStartWire,
  inspectStaleConflictObservation,
  inspectStorageSurfaceResults,
  inspectTransitionProtocolTrace,
  inspectTypedFailureMatrix,
  inspectUncertainWriteObservation,
  inspectVerificationObservation,
  scanNyay5Evidence,
  seededNyay5MutantResults,
  summarizeNyay5BrowserFailure,
  summarizeNyay5Rows,
} from './lib/nyay5-profile-browser-contract.mjs';
import {
  armCanonicalReadiness,
  settleCanonicalReadiness,
  waitForRouteDomSettled,
  waitForVisualCensusSettled,
} from './lib/browser-response-readiness.mjs';
import { runSeededHeadingStackVariance } from './lib/nyay26-readiness-variance-fixture.mjs';

const WEB = process.env.NYAY5_WEB_BASE_URL ?? 'http://localhost:1190';
const API = process.env.NYAY5_API_BASE_URL ?? 'http://127.0.0.1:1191';
const CAPTURE = process.env.NYAY5_OTP_CAPTURE_URL ?? 'http://127.0.0.1:1099';
const OUTPUT = process.env.NYAY5_EVIDENCE_PATH
  ?? resolve('../test-results/nyay5-browser/results.json');
const SCREENSHOT_DIR = process.env.NYAY5_SCREENSHOT_DIR
  ?? resolve(dirname(OUTPUT), 'screenshots');
const DENIAL_FIXTURE_PATH = process.env.NYAY5_DENIAL_FIXTURE_PATH ?? '';
const WEB_ORIGIN = new URL(WEB).origin;
const API_ORIGIN = new URL(API).origin;

const observations = new Map(
  NYAY5_ASSERTION_INVENTORY.map((name) => [name, { pass: false, metrics: { executed: false } }]),
);
const browserExecutions = new Map();
const privateValues = new Set();
const requests = [];
const visualScreens = new Map();
const screenshotNames = new Set();
const REVISION_L_VISUAL_SCREEN_IDS = Object.freeze([
  'S-03',
  'S-04',
  'S-05',
  'S-08',
  'S-09',
]);
const REVISION_L_HEADING_STACK = Object.freeze([
  'aptos',
  'calibri',
  'nyayone revision l heading',
  'system-ui',
  'sans-serif',
]);
const LEGACY_CARLITO_HEADING_STACK = Object.freeze([
  'aptos',
  'calibri',
  'carlito',
  'system-ui',
  'sans-serif',
]);
let authWireExact = false;
let registrationA11yExact = false;
let crossRealmTransitionExact = false;
let namespaceRetirementExact = false;
let failureClass = null;
let failureStage = null;
let failureCode = null;

async function createNyay5Context(browser, options = {}) {
  const context = await browser.newContext(options);
  await context.addInitScript(() => {
    const probeKey = Symbol.for('nyay5.browser.privacy-probe.v1');
    if (window[probeKey]) return;

    const initialGlobalKeys = new Set(
      Reflect.ownKeys(window).filter((key) => typeof key === 'string'),
    );
    const privateText = [
      /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/iu,
      /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/iu,
      /(?<!\d)[6-9]\d{9}(?!\d)/u,
      /\b(?:19|20)\d{2}-\d{2}-\d{2}\b/u,
      /(?:^|[?&#])(?:actor|owner|profile|registration|student|user)_?id=/iu,
      /(?:bearer\s+|eyJ)[A-Za-z0-9._~+/-]{12,}/iu,
    ];
    const privateKey = /^(?:access_token|actor_id|authorization|cookie|date_of_birth|dob|email|mobile|otp|password|profile_id|refresh_token|registration_id|session_token|student_profile_id|token|user_id)$/iu;

    const containsPrivate = (candidate) => {
      const seen = new WeakSet();
      let visited = 0;
      const inspect = (value, depth) => {
        visited += 1;
        if (visited > 2048) return true;
        if (typeof value === 'string') return privateText.some((pattern) => pattern.test(value));
        if (value === null || value === undefined
          || ['boolean', 'number', 'bigint', 'symbol', 'function'].includes(typeof value)) {
          return false;
        }
        if (depth >= 5 || typeof value !== 'object' || seen.has(value)) return false;
        if (value instanceof Node || value === window || value === document) return false;
        seen.add(value);
        let keys;
        try {
          keys = Reflect.ownKeys(value).slice(0, 512);
        } catch {
          return true;
        }
        for (const key of keys) {
          if (typeof key !== 'string') continue;
          let descriptor;
          try {
            descriptor = Object.getOwnPropertyDescriptor(value, key);
          } catch {
            return true;
          }
          if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) continue;
          if (privateKey.test(key) && descriptor.value !== null && descriptor.value !== undefined) {
            return true;
          }
          if (inspect(descriptor.value, depth + 1)) return true;
        }
        return false;
      };
      return inspect(candidate, 0);
    };

    const probe = {
      installed: true,
      initialGlobalKeys,
      historyCallsObserved: 0,
      transientHistoryPrivateDetected: false,
      containsPrivate,
    };
    Object.defineProperty(window, probeKey, {
      configurable: false,
      enumerable: false,
      writable: false,
      value: probe,
    });
    for (const method of ['pushState', 'replaceState']) {
      const original = history[method].bind(history);
      history[method] = (state, unused, url) => {
        probe.historyCallsObserved += 1;
        let resolvedUrl = '';
        try {
          resolvedUrl = url === undefined || url === null
            ? location.href : new URL(String(url), location.href).href;
        } catch {
          probe.transientHistoryPrivateDetected = true;
        }
        if (containsPrivate(state) || containsPrivate(resolvedUrl)) {
          probe.transientHistoryPrivateDetected = true;
        }
        return original(state, unused, url);
      };
    }
  });
  return context;
}

async function readPrivateControlFixtures() {
  if (!DENIAL_FIXTURE_PATH) throw new Error('NYAY5_DENIAL_FIXTURE_REQUIRED');
  let parsed;
  try {
    parsed = JSON.parse(await readFile(DENIAL_FIXTURE_PATH, 'utf8'));
  } catch {
    throw new Error('NYAY5_DENIAL_FIXTURE_INVALID');
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)
    || Object.keys(parsed).sort().join(',') !== 'fixtures,m01') {
    throw new Error('NYAY5_DENIAL_FIXTURE_INVALID');
  }
  return parsed;
}

async function readDenialFixtures() {
  const parsed = await readPrivateControlFixtures();
  const states = ['expired', 'revoked', 'deleted', 'wrong_role'];
  if (!parsed?.fixtures || Object.keys(parsed.fixtures).sort().join(',')
    !== [...states].sort().join(',')) {
    throw new Error('NYAY5_DENIAL_FIXTURE_INVALID');
  }
  for (const state of states) {
    if (typeof parsed.fixtures[state]?.token !== 'string'
      || parsed.fixtures[state].token.length < 32) {
      throw new Error('NYAY5_DENIAL_FIXTURE_INVALID');
    }
    rememberPrivate(parsed.fixtures[state].token);
  }
  return parsed.fixtures;
}

async function readM01Fixture() {
  const parsed = await readPrivateControlFixtures();
  const fixture = parsed.m01;
  const sessionIds = fixture?.session_ids;
  if (!fixture || typeof fixture !== 'object' || Array.isArray(fixture)
    || Object.keys(fixture).sort().join(',') !== 'admin_session_token,session_ids'
    || typeof fixture.admin_session_token !== 'string'
    || fixture.admin_session_token.length < 32
    || !Array.isArray(sessionIds)
    || sessionIds.length !== 2
    || new Set(sessionIds).size !== 2
    || !sessionIds.every((value) => (
      typeof value === 'string'
      && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u
        .test(value)
    ))) {
    throw new Error('NYAY5_M01_FIXTURE_INVALID');
  }
  rememberPrivate(fixture.admin_session_token);
  sessionIds.forEach(rememberPrivate);
  return {
    adminSessionToken: fixture.admin_session_token,
    sessionIds: [...sessionIds],
  };
}

async function denialContext(browser, token) {
  const context = await createNyay5Context(browser);
  await context.addCookies([{
    name: 'nyayone_session',
    value: token,
    domain: new URL(API).hostname,
    path: '/',
    httpOnly: true,
    secure: new URL(API).protocol === 'https:',
    sameSite: 'Lax',
  }]);
  return context;
}

function observe(name, pass, metrics = {}) {
  if (!observations.has(name)) throw new Error('NYAY5_UNKNOWN_ASSERTION');
  observations.set(name, { pass: Boolean(pass), metrics: { executed: true, ...metrics } });
}

function recordBrowserExecution(name, pass, evidenceCount, selectorCount = null) {
  const id = `browser:${name}`;
  if (browserExecutions.has(id)
    || !Number.isSafeInteger(evidenceCount) || evidenceCount <= 0
    || (selectorCount !== null
      && (!Number.isSafeInteger(selectorCount) || selectorCount < 0))) {
    throw new Error('NYAY5_BROWSER_EXECUTION_INVALID');
  }
  browserExecutions.set(id, {
    id,
    executed: true,
    skipped: false,
    pass: Boolean(pass),
    evidenceCount,
    selectorCount,
  });
}

function recordObservedBrowserExecution(
  name,
  observationName,
  evidenceCount,
  selectorCount = null,
) {
  const observation = observations.get(observationName);
  if (observation?.metrics?.executed !== true) {
    throw new Error('NYAY5_BROWSER_EXECUTION_OBSERVATION_MISSING');
  }
  recordBrowserExecution(name, observation.pass, evidenceCount, selectorCount);
}

function rememberPrivate(value) {
  if (typeof value === 'string' && value.length > 0) privateValues.add(value);
}

async function captureSafeScreenshot(page, name) {
  if (!/^[a-z0-9-]+$/u.test(name) || screenshotNames.has(name)) {
    throw new Error('NYAY5_SCREENSHOT_INVENTORY_INVALID');
  }
  await mkdir(SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({
    path: resolve(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  });
  screenshotNames.add(name);
}

async function recordVisualContract(page, screenId) {
  await waitForVisualCensusSettled(page, {
    assertion: 'browser:redesigned_heading_stack',
    expectedTheme: 'light',
    requireRevisionLLockup: REVISION_L_VISUAL_SCREEN_IDS.includes(screenId),
    readinessAttempts: 1,
  });
  const screen = page.locator(`[data-screen="${screenId}"]`).first();
  await screen.waitFor({ state: 'visible' });
  await screen.locator('h1:visible,h2:visible').first().waitFor({ state: 'visible' });
  await page.evaluate(() => document.fonts.ready);
  // A Locator.evaluate resolves its ElementHandle in an earlier browser
  // command. React may replace that root before its callback runs, producing
  // a false zero-heading census on a detached node. Select the current root,
  // establish structural readiness and sample in one synchronous callback.
  // Never poll for correct typography/icons: a ready but incorrect product
  // state returns its failed observation immediately and remains a failure.
  const snapshot = await page.waitForFunction((contract) => {
    const node = document.querySelector(`[data-screen="${contract.screenId}"]`);
    const visible = (element) => element.getClientRects().length > 0
      && getComputedStyle(element).visibility !== 'hidden';
    if (!(node instanceof Element) || !node.isConnected || !visible(node)
      || document.documentElement.getAttribute('data-theme') !== 'light'
      || document.fonts.status !== 'loaded') return false;
    const headings = [...node.querySelectorAll('h1,h2')]
      .filter((element) => element.getClientRects().length > 0);
    if (!headings.some(visible)) return false;
    if (contract.revisionLExpected && !node.querySelector('.v321-lockup')) return false;
    const normalizedFamily = (element) => getComputedStyle(element).fontFamily
      .replace(/["']/gu, '')
      .split(',')
      .map((name) => name.trim().toLowerCase());
    const expected = contract.revisionLExpected
      ? contract.revisionLHeadingStack
      : contract.legacyCarlitoHeadingStack;
    const icons = [...node.querySelectorAll('svg')]
      .filter((element) => element.getClientRects().length > 0);
    const exactRevisionLLockup = (icon) => (
      icon.getAttribute('class') === 'v321-lockup'
      && icon.getAttribute('role') === 'img'
      && icon.getAttribute('aria-label') === 'NyayOne — Legal, on the record'
      && !icon.hasAttribute('aria-hidden')
      && icon.tabIndex < 0
    );
    return {
      headingCount: headings.length,
      typographyExact: headings.length > 0 && headings.every((heading) => {
        const family = normalizedFamily(heading);
        return family.length === expected.length
          && family.every((name, index) => name === expected[index]);
      }),
      iconCount: icons.length,
      iconsExact: icons.every((icon) => {
        const isRevisionLLockup = icon.classList.contains('v321-lockup');
        if (isRevisionLLockup) return contract.revisionLExpected && exactRevisionLLockup(icon);
        return icon.getAttribute('aria-hidden') === 'true'
          && icon.tabIndex < 0
          && (!(icon.closest('button,a'))
            || Boolean(icon.closest('button,a')?.getAttribute('aria-label')
              || icon.closest('button,a')?.textContent?.trim()));
      }),
      legacyBrandVisible: /\blegalsaathi\b/iu.test(node.textContent ?? ''),
    };
  }, {
    screenId,
    revisionLExpected: REVISION_L_VISUAL_SCREEN_IDS.includes(screenId),
    revisionLHeadingStack: REVISION_L_HEADING_STACK,
    legacyCarlitoHeadingStack: LEGACY_CARLITO_HEADING_STACK,
  });
  let observation;
  try {
    observation = await snapshot.jsonValue();
  } finally {
    await snapshot.dispose();
  }
  const previous = visualScreens.get(screenId);
  visualScreens.set(screenId, {
    headingCount: Math.max(previous?.headingCount ?? 0, observation.headingCount),
    typographyExact: (previous?.typographyExact ?? true) && observation.typographyExact,
    iconCount: (previous?.iconCount ?? 0) + observation.iconCount,
    iconsExact: (previous?.iconsExact ?? true) && observation.iconsExact,
    legacyBrandVisible: (previous?.legacyBrandVisible ?? false)
      || observation.legacyBrandVisible,
  });
}

async function resetOtp() {
  const response = await fetch(`${CAPTURE}/reset`, { method: 'POST' });
  if (!response.ok) throw new Error('NYAY5_CAPTURE_RESET_FAILED');
}

async function latestOtp(mobile) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await fetch(`${CAPTURE}/latest`);
    if (response.ok) {
      const body = await response.json();
      if (body?.to === mobile && /^\d{6}$/u.test(body?.code ?? '')) {
        rememberPrivate(body.code);
        return body.code;
      }
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
  }
  throw new Error('NYAY5_CAPTURE_CODE_UNAVAILABLE');
}

async function loginStudent(context, mobile) {
  await resetOtp();
  const started = await context.request.post(
    `${API}/api/v1/auth/student/login/otp/start`,
    { headers: { Origin: WEB_ORIGIN }, data: { mobile } },
  );
  const code = await latestOtp(mobile);
  const verified = await context.request.post(
    `${API}/api/v1/auth/student/login/otp/verify`,
    { headers: { Origin: WEB_ORIGIN }, data: { code } },
  );
  const startedBody = started.ok() ? await started.json() : null;
  const verifiedBody = verified.ok() ? await verified.json() : null;
  // The authenticated session is origin-wide under NYAY-8. Query the exact API
  // probe and still require the cookie's root/Lax attributes independently.
  const cookies = await context.cookies(`${API}/api/v1/auth/student/session`);
  const session = await context.request.get(`${API}/api/v1/auth/student/session`);
  const body = session.ok() ? await session.json() : null;
  for (const cookie of cookies) rememberPrivate(cookie.value);
  if (body?.actor?.sub) rememberPrivate(body.actor.sub);
  if (body?.actor?.student_profile_id) rememberPrivate(body.actor.student_profile_id);
  const cookieExact = cookies.some((cookie) => (
    cookie.httpOnly && cookie.value && cookie.path === '/' && cookie.sameSite === 'Lax'
  ));
  let loginFailure = null;
  if (started.status() !== 202) loginFailure = 'NYAY5_LOGIN_START_FAILED';
  else if (!inspectOtpFlowWire(startedBody).pass) loginFailure = 'NYAY5_LOGIN_START_WIRE_FAILED';
  else if (verified.status() !== 200) loginFailure = 'NYAY5_LOGIN_VERIFY_FAILED';
  else if (!inspectOtpVerificationWire(verifiedBody).pass) {
    loginFailure = 'NYAY5_LOGIN_VERIFY_WIRE_FAILED';
  }
  else if (session.status() !== 200 || body?.authenticated !== true) {
    loginFailure = 'NYAY5_LOGIN_SESSION_FAILED';
  } else if (!body?.actor?.roles?.includes('student')) loginFailure = 'NYAY5_LOGIN_ROLE_FAILED';
  else if (!cookieExact) loginFailure = 'NYAY5_LOGIN_COOKIE_FAILED';
  return {
    pass: loginFailure === null,
    code: loginFailure,
    actor: body?.actor ?? null,
  };
}

async function loginStudentThroughUi(page, mobile) {
  const { startResponse } = await prepareStudentLoginOtp(page, mobile);
  failureStage = 'student_login_verify_submit';
  const verifyResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/login/otp/verify'
  ));
  const verifiedSessionResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === 'GET'
      && url.origin === API_ORIGIN
      && url.pathname === '/api/v1/auth/student/session'
      && url.search === ''
      && url.hash === '';
  });
  await page.getByRole('button', { name: 'Verify and continue', exact: true }).click();
  const [verifyResponse, verifiedSessionResponse] = await Promise.all([
    verifyResponsePromise,
    verifiedSessionResponsePromise,
  ]);
  const verifiedSessionFinishedError = await verifiedSessionResponse.finished();
  return {
    startResponse,
    verifyResponse,
    verifiedSessionResponse,
    verifiedSessionFinishedError,
  };
}

async function prepareStudentLoginOtp(page, mobile) {
  failureStage = 'student_login_otp_reset';
  await resetOtp();
  // The isolated service intentionally keeps a one-second OTP resend floor.
  // Wait past it so this probe exercises the auth-transition barrier rather
  // than a rate-limit decoy from the immediately preceding account setup.
  failureStage = 'student_login_resend_floor';
  await page.waitForTimeout(1_100);
  failureStage = 'student_login_entry_navigation';
  if (new URL(page.url()).pathname !== '/s-03') {
    await page.goto(`${WEB}/s-03`, { waitUntil: 'domcontentloaded' });
  }
  failureStage = 'student_login_entry_action';
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.waitForURL(/\/s-04$/u);
  await page.locator('#v34-login-mobile').fill(mobile);
  failureStage = 'student_login_start_submit';
  const otpRouteReadiness = armCanonicalReadiness(page, {
    apiOrigin: API_ORIGIN,
    requirements: [{ kind: 'otpState' }],
    stage: 'student_login_pending',
  });
  const startResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/login/otp/start'
  ));
  await page.getByRole('button', { name: 'Send one time code', exact: true }).click();
  const settledReadiness = settleCanonicalReadiness(otpRouteReadiness);
  const startResponse = await startResponsePromise;
  if (startResponse.status() !== 202) {
    throw new Error(`NYAY5_STUDENT_LOGIN_START_REJECTED_${startResponse.status()}`);
  }
  failureStage = 'student_login_pending_navigation';
  await waitForRouteDomSettled(page, '/s-05', {
    settledReadiness,
    selector: '[data-screen="S-05"]',
  });
  failureStage = 'student_login_pending_authority';
  const stateResponse = await page.context().request.get(
    `${API}/api/v1/auth/student/otp/state`,
    { headers: { Origin: WEB_ORIGIN } },
  );
  const stateBody = stateResponse.status() === 200 ? await stateResponse.json() : null;
  const authorityCookies = await page.context().cookies(
    `${API}/api/v1/auth/student/otp/state`,
  );
  const flowCookies = authorityCookies.filter((cookie) => cookie.name === 'nyayone_otp_flow');
  const sessionCookies = authorityCookies.filter((cookie) => cookie.name === 'nyayone_session');
  if (stateResponse.status() !== 200
      || stateBody?.status !== 'pending'
      || stateBody?.purpose !== 'login'
      || flowCookies.length !== 1
      || !flowCookies[0].httpOnly
      || sessionCookies.length !== 0) {
    throw new Error('NYAY5_STUDENT_LOGIN_PENDING_AUTHORITY_INVALID');
  }
  failureStage = 'student_login_otp_capture';
  const code = await latestOtp(mobile);
  failureStage = 'student_login_otp_controls';
  await page.getByLabel('Six digit code').waitFor({ state: 'visible' });
  await page.getByLabel('Six digit code').fill(code);
  return { startResponse };
}

async function installTransitionMessageProbe(context) {
  await context.addInitScript(() => {
    const native = globalThis.BroadcastChannel;
    if (typeof native !== 'function') return;
    const probeKey = Symbol.for('nyay5.auth-transition-probe.v1');
    const trace = [];
    let sequence = 0;
    const record = (direction, value) => {
      if (value && typeof value === 'object') {
        sequence += 1;
        trace.push({ direction, sequence, message: structuredClone(value) });
      }
    };
    Object.defineProperty(globalThis, probeKey, {
      configurable: false,
      enumerable: false,
      value: { trace },
      writable: false,
    });
    class ProbedBroadcastChannel extends native {
      constructor(name) {
        super(name);
        if (name === 'nyayone.student.auth-transition.v2') {
          this.addEventListener('message', (event) => record('receive', event.data));
        }
      }

      postMessage(value) {
        if (this.name === 'nyayone.student.auth-transition.v2') record('send', value);
        return super.postMessage(value);
      }
    }
    Object.defineProperty(globalThis, 'BroadcastChannel', {
      configurable: true,
      value: ProbedBroadcastChannel,
      writable: true,
    });
  });
}

async function transitionTrace(page) {
  return page.evaluate(() => (
    globalThis[Symbol.for('nyay5.auth-transition-probe.v1')]?.trace ?? []
  ));
}

async function provisionStudent(
  browser,
  { dob = '2000-03-01', firstName = 'Nyaay', signupSessionOnly = false } = {},
) {
  const priorFailureStage = failureStage;
  const fixtureLabel = firstName.replace(/[^a-z0-9]+/giu, '_').toLowerCase();
  const context = await createNyay5Context(browser, { viewport: { width: 390, height: 844 } });
  const nonce = createHash('sha256').update(randomBytes(32)).digest('hex');
  const mobile = `8${[...nonce].map((value) => Number.parseInt(value, 16) % 10).join('').slice(0, 9)}`;
  const idempotencyKey = `nyay5-browser-${nonce}`;
  rememberPrivate(mobile);
  rememberPrivate(idempotencyKey);
  failureStage = `student_provision_${fixtureLabel}_registration`;
  await resetOtp();
  const registration = await context.request.post(`${API}/api/v1/auth/student/register`, {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
      Origin: WEB_ORIGIN,
    },
    data: {
      first_name: firstName,
      middle_name: null,
      last_name: 'Boundary',
      mobile,
      dob,
      terms_accepted: true,
      terms_version: 'dpdp-2023.v1',
      privacy_notice_acknowledged: true,
      privacy_notice_version: 'dpdp-2023.v1',
    },
  });
  failureStage = `student_provision_${fixtureLabel}_signup_otp`;
  const code = await latestOtp(mobile);
  const verified = await context.request.post(`${API}/api/v1/auth/student/otp/verify`, {
    headers: { Origin: WEB_ORIGIN },
    data: { code },
  });
  const registrationBody = registration.ok() ? await registration.json() : null;
  const verifiedBody = verified.ok() ? await verified.json() : null;
  if (
    registration.status() !== 202
    || !inspectRegistrationStartWire(registrationBody).pass
    || verified.status() !== 200
    || !inspectOtpVerificationWire(verifiedBody).pass
  ) {
    await context.close();
    throw new Error('NYAY5_STUDENT_PROVISION_FAILED');
  }
  if (signupSessionOnly) {
    const session = await context.request.get(`${API}/api/v1/auth/student/session`);
    const body = session.ok() ? await session.json() : null;
    if (
      session.status() !== 200
      || body?.authenticated !== true
      || !body?.actor?.roles?.includes('student')
    ) {
      await context.close();
      throw new Error('NYAY5_SIGNUP_SESSION_PROVISION_FAILED');
    }
    if (body.actor.sub) rememberPrivate(body.actor.sub);
    if (body.actor.student_profile_id) rememberPrivate(body.actor.student_profile_id);
    failureStage = priorFailureStage;
    return { context, mobile, sessionActor: body.actor };
  }
  const loggedOut = await context.request.post(`${API}/api/v1/auth/student/logout`, {
    headers: { Origin: WEB_ORIGIN }, data: {},
  });
  // Signup verification and the immediately following login target the same
  // identity. Honor the server's real one-second resend floor before resetting
  // the capture fixture, otherwise the enumeration-neutral 202 may correctly
  // suppress delivery and create a false missing-code failure.
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 1_100));
  failureStage = `student_provision_${fixtureLabel}_login_otp`;
  const login = await loginStudent(context, mobile);
  if (
    loggedOut.status() !== 200
    || !login.pass
  ) {
    await context.close();
    throw new Error(login.code ?? 'NYAY5_AUTHENTICATED_SESSION_PROVISION_FAILED');
  }
  failureStage = priorFailureStage;
  return { context, mobile, sessionActor: login.actor };
}

async function authWireAndPasswordlessProbe(browser) {
  const context = await createNyay5Context(browser, { viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const nonce = createHash('sha256').update(randomBytes(32)).digest('hex');
  const mobile = `7${[...nonce].map((value) => Number.parseInt(value, 16) % 10).join('').slice(0, 9)}`;
  rememberPrivate(mobile);
  const authRequests = [];
  let gatewayExact = false;
  let s08FieldsExact;
  let s08ConsentControlsExact;
  let uncheckedConsentDenied;
  let otpInputExact;
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.origin !== API_ORIGIN || !url.pathname.startsWith('/api/v1/auth/student/')) return;
    authRequests.push({ path: url.pathname, body: request.postData() ?? '' });
  });
  const passwordlessSurface = async (path) => {
    await page.goto(`${WEB}${path}`, { waitUntil: 'domcontentloaded' });
    const screenId = `S-${path.slice(3).padStart(2, '0')}`;
    await recordVisualContract(page, screenId);
    if (path === '/s-03') {
      const signIn = page.getByRole('button', { name: 'Sign in', exact: true });
      const register = page.getByRole('button', { name: 'Register as a student', exact: true });
      const selectorsExact = await signIn.count() === 1 && await register.count() === 1;
      await captureSafeScreenshot(page, 's03-gateway-public');
      await signIn.click();
      await page.waitForURL(/\/s-04$/u);
      const signInDestination = new URL(page.url()).pathname === '/s-04';
      await page.goto(`${WEB}/s-03`, { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: 'Register as a student', exact: true }).click();
      await page.waitForURL(/\/s-08$/u);
      const registerDestination = new URL(page.url()).pathname === '/s-08';
      gatewayExact = selectorsExact && signInDestination && registerDestination;
      await page.goto(`${WEB}/s-03`, { waitUntil: 'domcontentloaded' });
    }
    const bodyText = await page.locator('body').innerText();
    return await page.locator('input[type="password"]').count() === 0
      && await page.getByRole('button', { name: /password|use a one time code/iu }).count() === 0
      && !/(?:enter|use|forgot|reset|create)\s+(?:a\s+)?password/iu.test(bodyText);
  };
  const passwordless = [];
  passwordless.push(await passwordlessSurface('/s-03'));
  passwordless.push(await passwordlessSurface('/s-04'));
  passwordless.push(await passwordlessSurface('/s-06'));

  await resetOtp();
  await page.goto(`${WEB}/s-08`, { waitUntil: 'domcontentloaded' });
  await recordVisualContract(page, 'S-08');
  const registrationRequestsBeforeEmptySubmit = authRequests.filter((request) => (
    request.path === '/api/v1/auth/student/register'
  )).length;
  await page.getByRole('button', { name: 'Send one time code' }).click();
  const emptySummary = page.locator('#s08-error-summary');
  await emptySummary.waitFor();
  const emptySummaryExact = await emptySummary.getAttribute('role') === 'alert'
    && await emptySummary.evaluate((node) => document.activeElement === node);
  const linkedErrorsExact = await emptySummary.locator('a').evaluateAll((links) => (
    links.length === 6 && links.every((link) => {
      const href = link.getAttribute('href');
      if (!href?.startsWith('#')) return false;
      const control = document.querySelector(href);
      if (!(control instanceof HTMLElement)) return false;
      const describedBy = control.getAttribute('aria-describedby');
      return control.getAttribute('required') !== null
        && control.getAttribute('aria-required') === 'true'
        && typeof describedBy === 'string'
        && describedBy.length > 0
        && document.getElementById(describedBy)?.getAttribute('role') === 'alert';
    })
  ));
  const registrationRequestsAfterEmptySubmit = authRequests.filter((request) => (
    request.path === '/api/v1/auth/student/register'
  )).length;
  registrationA11yExact = emptySummaryExact
    && linkedErrorsExact
    && registrationRequestsAfterEmptySubmit === registrationRequestsBeforeEmptySubmit;
  await captureSafeScreenshot(page, 's08-empty-validation-public');
  await page.locator('#v34-first').fill('Wire');
  await page.locator('#v34-last').fill('Boundary');
  await page.locator('#v34-mobile').fill(mobile);
  await page.locator('#v34-dob').fill('2000-01-01');
  const requiredFieldIds = [
    'v34-first', 'v34-middle', 'v34-last', 'v34-mobile', 'v34-dob',
  ];
  s08FieldsExact = (await Promise.all(requiredFieldIds.map((id) => (
    page.locator(`#${id}`).count()
  )))).every((count) => count === 1)
    && await page.locator('input[type="email"],#profile-academic-email').count() === 0;
  const terms = page.locator('#v34-terms');
  const privacy = page.locator('#v34-privacy');
  s08ConsentControlsExact = await terms.count() === 1
    && await privacy.count() === 1
    && await terms.isChecked() === false
    && await privacy.isChecked() === false
    && await terms.getAttribute('required') !== null
    && await privacy.getAttribute('required') !== null
    && await page.locator('label[for="v34-terms"]').getByText('I accept the Terms.').count() === 1
    && await page.locator('label[for="v34-privacy"]')
      .getByText('I acknowledge the Privacy Notice.').count() === 1;
  await terms.check();
  const beforeUncheckedConsent = authRequests.filter((request) => (
    request.path === '/api/v1/auth/student/register'
  )).length;
  await page.getByRole('button', { name: 'Send one time code' }).click();
  await page.locator('#v34-privacy-error').waitFor();
  const afterUncheckedConsent = authRequests.filter((request) => (
    request.path === '/api/v1/auth/student/register'
  )).length;
  uncheckedConsentDenied = beforeUncheckedConsent === afterUncheckedConsent
    && await privacy.getAttribute('aria-invalid') === 'true';
  await privacy.check();
  const signupOtpRouteReadiness = armCanonicalReadiness(page, {
    apiOrigin: API_ORIGIN,
    requirements: [{ kind: 'otpState' }],
    stage: 'signup_pending',
  });
  const signupStarted = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/register'
  ));
  await page.getByRole('button', { name: 'Send one time code' }).click();
  const signupSettledReadiness = settleCanonicalReadiness(signupOtpRouteReadiness);
  const signupStartResponse = await signupStarted;
  const signupStartBody = signupStartResponse.ok() ? await signupStartResponse.json() : null;
  await waitForRouteDomSettled(page, '/s-09', {
    settledReadiness: signupSettledReadiness,
    selector: '[data-screen="S-09"]',
  });
  await recordVisualContract(page, 'S-09');
  const signupScreenExact = await page.locator('[data-screen="S-09"]').count() === 1
    && await page.locator('[data-screen="S-05"]').count() === 0;
  const signupStateResponse = await context.request.get(`${API}/api/v1/auth/student/otp/state`);
  const signupStateBody = signupStateResponse.ok() ? await signupStateResponse.json() : null;
  const signupOtpInput = page.getByLabel('Six digit code');
  const blankSignupDisabled = await page.getByRole('button', { name: 'Verify and continue' })
    .isDisabled();
  await signupOtpInput.evaluate((input) => {
    const clipboardData = new DataTransfer();
    clipboardData.setData('text', '12a34 56');
    input.dispatchEvent(new ClipboardEvent('paste', {
      bubbles: true,
      cancelable: true,
      clipboardData,
    }));
  });
  await page.waitForFunction(() => (
    document.querySelector('input[aria-label="Six digit code"]')?.value === '123456'
  ));
  const pastedAndCorrected = await signupOtpInput.inputValue() === '123456';
  const otpAttributesExact = await signupOtpInput.getAttribute('inputmode') === 'numeric'
    && await signupOtpInput.getAttribute('autocomplete') === 'one-time-code'
    && await signupOtpInput.getAttribute('maxlength') === '6';
  await signupOtpInput.fill('');
  otpInputExact = blankSignupDisabled && pastedAndCorrected && otpAttributesExact;
  const signupCode = await latestOtp(mobile);
  const signupVerified = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/otp/verify'
  ));
  await page.getByLabel('Six digit code').fill(signupCode);
  await page.getByRole('button', { name: 'Verify and continue' }).click();
  const signupVerifyResponse = await signupVerified;
  const signupVerifyBody = signupVerifyResponse.ok() ? await signupVerifyResponse.json() : null;
  await page.waitForURL(/\/s-07$/u);
  const signupLanding = new URL(page.url()).pathname;
  const signupCookies = await context.cookies(`${API}/api/v1/auth/student/session`);
  const signupCookieExact = signupCookies.some((cookie) => (
    cookie.httpOnly && cookie.value && cookie.path === '/' && cookie.sameSite === 'Lax'
  ));
  signupCookies.forEach((cookie) => rememberPrivate(cookie.value));

  const loggedOut = await context.request.post(`${API}/api/v1/auth/student/logout`, {
    headers: { Origin: WEB_ORIGIN }, data: {},
  });
  await resetOtp();
  await page.goto(`${WEB}/s-04`, { waitUntil: 'domcontentloaded' });
  await recordVisualContract(page, 'S-04');
  await page.locator('#v34-login-mobile').fill(mobile);
  const loginOtpRouteReadiness = armCanonicalReadiness(page, {
    apiOrigin: API_ORIGIN,
    requirements: [{ kind: 'otpState' }],
    stage: 'login_pending',
  });
  const loginStarted = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/login/otp/start'
  ));
  await page.getByRole('button', { name: 'Send one time code' }).click();
  const loginSettledReadiness = settleCanonicalReadiness(loginOtpRouteReadiness);
  const loginStartResponse = await loginStarted;
  const loginStartBody = loginStartResponse.ok() ? await loginStartResponse.json() : null;
  await waitForRouteDomSettled(page, '/s-05', {
    settledReadiness: loginSettledReadiness,
    selector: '[data-screen="S-05"]',
  });
  await recordVisualContract(page, 'S-05');
  const loginScreenExact = await page.locator('[data-screen="S-05"]').count() === 1
    && await page.locator('[data-screen="S-09"]').count() === 0;
  const loginChallengeText = await page.locator('body').innerText();
  passwordless.push(await page.locator('input[type="password"]').count() === 0
    && await page.getByRole('button', { name: /password|use a one time code/iu }).count() === 0
    && !/(?:enter|use|forgot|reset|create)\s+(?:a\s+)?password/iu.test(loginChallengeText));
  const loginStateResponse = await context.request.get(`${API}/api/v1/auth/student/otp/state`);
  const loginStateBody = loginStateResponse.ok() ? await loginStateResponse.json() : null;
  const loginCode = await latestOtp(mobile);
  const loginVerified = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/login/otp/verify'
  ));
  await page.getByLabel('Six digit code').fill(loginCode);
  await page.getByRole('button', { name: 'Verify and continue' }).click();
  const loginVerifyResponse = await loginVerified;
  const loginVerifyBody = loginVerifyResponse.ok() ? await loginVerifyResponse.json() : null;
  await page.waitForURL(/\/s-07$/u);
  await recordVisualContract(page, 'S-07');
  const loginLanding = new URL(page.url()).pathname;
  const loginCookies = await context.cookies(`${API}/api/v1/auth/student/session`);
  const loginCookieExact = loginCookies.some((cookie) => (
    cookie.httpOnly && cookie.value && cookie.path === '/' && cookie.sameSite === 'Lax'
  ));
  loginCookies.forEach((cookie) => rememberPrivate(cookie.value));

  const flowWires = [signupStartBody, signupStateBody, loginStartBody, loginStateBody];
  const verificationWires = [signupVerifyBody, loginVerifyBody];
  const landingExact = signupLanding === '/s-07' && loginLanding === '/s-07';
  authWireExact = gatewayExact && registrationA11yExact && landingExact
    && inspectAuthBoundaryObservation({
    registrationStartStatus: signupStartResponse.status(),
    loginStartStatus: loginStartResponse.status(),
    registrationStartWire: signupStartBody,
    otpFlowWires: flowWires.slice(1),
    verificationWires,
    signupScreenExact,
    loginScreenExact,
    signupLanding,
    loginLanding,
    signupCookieExact,
    loginCookieExact,
    logoutStatus: loggedOut.status(),
    passwordlessSurfaces: passwordless,
    authRequests,
  }).pass;
  recordBrowserExecution('s03_gateway_actions', gatewayExact, 2, 2);
  recordBrowserExecution('passwordless_surfaces', passwordless.every(Boolean), 4, 4);
  recordBrowserExecution('otp_input_accessibility', otpInputExact, 3, 1);
  recordBrowserExecution('otp_exact_success_navigation', landingExact, 2, 2);
  recordBrowserExecution('auth_route_mapping', signupScreenExact && loginScreenExact, 2, 2);
  recordBrowserExecution('signup_session_atomic_wire', authWireExact, 6, null);
  recordBrowserExecution('s08_field_contract', s08FieldsExact, 6, 6);
  recordBrowserExecution(
    's08_separate_consent_controls',
    s08ConsentControlsExact && uncheckedConsentDenied,
    2,
    2,
  );
  await recordStorage(page, 'auth');
  await context.close();
}

async function unsupportedTransitionContext(browser, initScript) {
  const context = await createNyay5Context(browser, { viewport: { width: 390, height: 844 } });
  await context.addInitScript(initScript);
  const page = await context.newPage();
  let privateRequests = 0;
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/v1/auth/student/session'
      || pathname.startsWith('/api/v1/student/')) privateRequests += 1;
  });
  await page.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
  const unavailable = page.getByTestId('student-session-unavailable');
  await unavailable.waitFor({ state: 'visible' });
  const result = {
    unavailable: await unavailable.count() === 1,
    privateRequests,
  };
  await context.close();
  return result;
}

async function inaccessibleStorageTransitionContext(browser, mobile) {
  return transitionCleanupFailureProbe(browser, mobile, 'local-cleanup');
}

async function transitionCleanupFailureProbe(browser, mobile, mode) {
  failureStage = `cross_realm_${mode}_setup`;
  const context = await createNyay5Context(browser, { viewport: { width: 390, height: 844 } });
  const peer = mode === 'peer-nack' ? await context.newPage() : null;
  const initiator = await context.newPage();
  if (peer) {
    const sessionReady = peer.waitForResponse((response) => (
      response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/v1/auth/student/session'
    ));
    await peer.goto(`${WEB}/s-03`, { waitUntil: 'domcontentloaded' });
    await sessionReady;
    await peer.evaluate(() => {
      sessionStorage.setItem('legalsaathi.student.registration.v2',
        'synthetic-peer-cleanup-denial-canary');
      Storage.prototype.removeItem = () => { throw new Error('synthetic_cleanup_denied'); };
    });
  }

  failureStage = `cross_realm_${mode}_otp`;
  await prepareStudentLoginOtp(initiator, mobile);
  if (mode === 'local-cleanup') {
    await initiator.evaluate(() => {
      localStorage.setItem('legalsaathi.student.profile.v1',
        'synthetic-cleanup-denial-canary');
      Storage.prototype.removeItem = () => { throw new Error('synthetic_storage_unavailable'); };
    });
  }
  const beforeCookies = await context.cookies(`${API}/api/v1/auth/student/session`);
  let verifyRequests = 0;
  initiator.on('request', (request) => {
    if (request.method() === 'POST'
      && new URL(request.url()).pathname === '/api/v1/auth/student/login/otp/verify') {
      verifyRequests += 1;
    }
  });
  await initiator.getByRole('button', { name: 'Verify and continue', exact: true }).click();
  failureStage = `cross_realm_${mode}_failure_ui`;
  await initiator.waitForURL(/\/s-03$/u);
  const failedOtpControlsAbsent = await initiator.getByLabel('Six digit code').count() === 0
    && await initiator
      .getByRole('button', { name: 'Verify and continue', exact: true }).count() === 0;
  if (!failedOtpControlsAbsent) {
    throw new Error('NYAY5_FAILED_TRANSITION_OTP_CONTROLS_PRESENT');
  }
  const evidencePage = peer ?? initiator;
  await evidencePage.evaluate(() => {
    history.pushState({}, '', '/s-10?section=personal');
    dispatchEvent(new PopStateEvent('popstate'));
  });
  const unavailable = evidencePage.getByTestId('student-session-unavailable');
  await unavailable.waitFor({ state: 'visible' });
  const afterCookies = await context.cookies(`${API}/api/v1/auth/student/session`);
  const cookieUnchanged = JSON.stringify(beforeCookies.map(({ name, value }) => ({ name, value })))
    === JSON.stringify(afterCookies.map(({ name, value }) => ({ name, value })));
  const result = {
    unavailable: await unavailable.count() === 1,
    verifyRequests,
    cookieUnchanged,
  };
  await context.close();
  return result;
}

async function crossRealmAuthTransitionProbe(browser) {
  failureStage = 'cross_realm_m01_fixture';
  const m01Fixture = await readM01Fixture();
  failureStage = 'cross_realm_provision_actor_a';
  const actorA = await provisionStudent(browser, { firstName: 'BarrierA' });
  failureStage = 'cross_realm_provision_actor_b';
  const actorB = await provisionStudent(browser, { firstName: 'BarrierB' });
  const actorALogout = await actorA.context.request.post(`${API}/api/v1/auth/student/logout`, {
    headers: { Origin: WEB_ORIGIN }, data: {},
  });
  const actorBLogout = await actorB.context.request.post(`${API}/api/v1/auth/student/logout`, {
    headers: { Origin: WEB_ORIGIN }, data: {},
  });
  const actorAMobile = actorA.mobile;
  const actorBMobile = actorB.mobile;
  await actorA.context.close();
  await actorB.context.close();
  if (actorALogout.status() !== 200 || actorBLogout.status() !== 200) {
    throw new Error('NYAY5_BARRIER_ACTOR_SETUP_FAILED');
  }

  const context = await denialContext(browser, m01Fixture.adminSessionToken);
  await installTransitionMessageProbe(context);
  const holder = await context.newPage();
  const initiator = await context.newPage();
  const postStartAttacker = await context.newPage();
  trackActorBoundary(holder);
  trackActorBoundary(initiator);
  trackActorBoundary(postStartAttacker);

  failureStage = 'cross_realm_m01_holder_mount';
  await holder.goto(`${WEB}/mentor/sessions`, { waitUntil: 'domcontentloaded' });
  const holderCompletionControls = holder.locator('[data-action="record-completion"]');
  await holderCompletionControls.first().waitFor({ state: 'visible' });
  const m01HolderCompletionControls = await holderCompletionControls.count();
  failureStage = 'cross_realm_m01_attacker_mount';
  await postStartAttacker.goto(`${WEB}/mentor/sessions`, { waitUntil: 'domcontentloaded' });
  const attackerCompletionControls = postStartAttacker.locator(
    '[data-action="record-completion"]',
  );
  await attackerCompletionControls.first().waitFor({ state: 'visible' });
  const m01AttackerCompletionControls = await attackerCompletionControls.count();

  const [m01FirstTarget, m01SecondTarget] = m01Fixture.sessionIds;
  const holderTargetAction = holder.locator('article').filter({ hasText: m01FirstTarget })
    .locator('[data-action="record-completion"]');
  if (await holderTargetAction.count() !== 1) throw new Error('NYAY5_M01_FIRST_TARGET_MISSING');
  let m01CompletionRequests = 0;
  let m01PostStartSecondTargetRequests = 0;
  for (const page of [holder, postStartAttacker]) {
    page.on('request', (request) => {
      const pathname = new URL(request.url()).pathname;
      if (request.method() === 'POST'
        && /^\/api\/v1\/tutoring\/sessions\/[0-9a-f-]+\/complete$/u.test(pathname)) {
        m01CompletionRequests += 1;
      }
      if (page === postStartAttacker && request.method() === 'POST'
        && pathname === `/api/v1/tutoring/sessions/${m01SecondTarget}/complete`) {
        m01PostStartSecondTargetRequests += 1;
      }
    });
  }
  await postStartAttacker.evaluate((sessionId) => {
    const probe = { listenerFired: false, controlFound: false, clickInvoked: false };
    Object.defineProperty(globalThis, Symbol.for('nyay5.m01-post-start-attempt.v1'), {
      configurable: false, value: probe, writable: false,
    });
    addEventListener('nyayone:student-auth-transition-started', () => {
      probe.listenerFired = true;
      const row = [...document.querySelectorAll('article')].find(
        (candidate) => candidate.textContent?.includes(sessionId),
      );
      const control = row?.querySelector('[data-action="record-completion"]');
      probe.controlFound = Boolean(control);
      if (control) {
        probe.clickInvoked = true;
        control.click();
      }
    }, { once: true });
  }, m01SecondTarget);

  let releaseM01Response;
  let markM01ServerSettled;
  const m01ResponseReleased = new Promise((resolveRelease) => {
    releaseM01Response = resolveRelease;
  });
  const m01ServerSettled = new Promise((resolveSettled) => {
    markM01ServerSettled = resolveSettled;
  });
  const m01CompleteRoute = `**/api/v1/tutoring/sessions/${m01FirstTarget}/complete`;
  await holder.route(m01CompleteRoute, async (route) => {
    const response = await route.fetch();
    markM01ServerSettled(response.status());
    await m01ResponseReleased;
    await route.fulfill({ response });
  }, { times: 1 });
  failureStage = 'cross_realm_m01_server_settle';
  await holderTargetAction.click();
  const m01ServerSettledStatus = await m01ServerSettled;
  if (m01ServerSettledStatus !== 200) throw new Error('NYAY5_M01_HOLDER_WRITE_FAILED');

  failureStage = 'cross_realm_m01_prepare_student_login';
  // The administrator write has already settled on the server. Retire only its
  // browser credential so the real login-start endpoint can issue the pending
  // flow that S-05 now requires; verification below remains the production
  // Web-Locks-controlled cookie transition under test.
  await context.clearCookies({ name: 'nyayone_session' });
  await prepareStudentLoginOtp(initiator, actorAMobile);
  let m01VerifyRequests = 0;
  initiator.on('request', (request) => {
    if (request.method() === 'POST'
      && new URL(request.url()).pathname === '/api/v1/auth/student/login/otp/verify') {
      m01VerifyRequests += 1;
    }
  });
  const m01VerifyResponsePromise = initiator.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/login/otp/verify'
  ));
  failureStage = 'cross_realm_m01_start_student_verify';
  await initiator.getByRole('button', { name: 'Verify and continue', exact: true }).click();
  await holder.getByRole('heading', { name: 'Administrator access required', exact: true })
    .waitFor({ state: 'visible' });
  await postStartAttacker
    .getByRole('heading', { name: 'Administrator access required', exact: true })
    .waitFor({ state: 'visible' });
  const m01PrivateControlsAfterTransitionStart =
    await holder.locator('[data-action="record-completion"]').count()
    + await postStartAttacker.locator('[data-action="record-completion"]').count();
  const m01PrivateUiUnmounted = m01PrivateControlsAfterTransitionStart === 0
    && await holder.getByRole('heading', { name: 'Record completion', exact: true }).count() === 0
    && await postStartAttacker
      .getByRole('heading', { name: 'Record completion', exact: true }).count() === 0;
  const m01PostStartAttempt = await postStartAttacker.evaluate(() => (
    globalThis[Symbol.for('nyay5.m01-post-start-attempt.v1')]
  ));
  const m01PostStartAttemptObserved = m01PostStartAttempt?.listenerFired === true
    && (m01PostStartAttempt.controlFound === false
      || m01PostStartAttempt.clickInvoked === true);
  const m01VerifyRequestsBeforeResponseRelease = m01VerifyRequests;

  failureStage = 'cross_realm_m01_release_response';
  releaseM01Response();
  const m01VerifyResponse = await m01VerifyResponsePromise;
  if (m01VerifyResponse.status() !== 200) throw new Error('NYAY5_M01_VERIFY_FAILED');
  await initiator.waitForURL(/\/s-07$/u);
  const m01VerifyRequestsAtCompletion = m01VerifyRequests;
  await holder.unroute(m01CompleteRoute);
  await holder.waitForTimeout(100);
  const m01TransitionProtocolTrace = {
    initiator: await transitionTrace(initiator),
    peers: [await transitionTrace(holder), await transitionTrace(postStartAttacker)],
    lateRealm: [],
  };

  failureStage = 'cross_realm_m01_authoritative_state';
  const m01Verifier = await denialContext(browser, m01Fixture.adminSessionToken);
  const m01FirstResponse = await m01Verifier.request.get(
    `${API}/api/v1/tutoring/sessions/${m01FirstTarget}`,
  );
  const m01SecondResponse = await m01Verifier.request.get(
    `${API}/api/v1/tutoring/sessions/${m01SecondTarget}`,
  );
  const m01FirstBody = m01FirstResponse.ok() ? await m01FirstResponse.json() : null;
  const m01SecondBody = m01SecondResponse.ok() ? await m01SecondResponse.json() : null;
  const m01FirstTargetCompleted = m01FirstResponse.status() === 200
    && m01FirstBody?.status === 'completed'
    && m01FirstBody?.version === 2;
  const m01FirstTargetAttendanceRecorded = m01FirstBody?.attendance_state === 'recorded';
  const m01CommitExactlyOnce = m01CompletionRequests === 1
    && m01FirstTargetCompleted
    && m01FirstTargetAttendanceRecorded
    && m01FirstBody?.version === 2
    && m01FirstBody?.attendance_version === 1;
  const m01SecondTargetUntouched = m01SecondResponse.status() === 200
    && m01SecondBody?.status === 'confirmed'
    && m01SecondBody?.version === 1
    && m01SecondBody?.attendance_state === null
    && m01SecondBody?.attendance_version === null;
  await m01Verifier.close();

  failureStage = 'cross_realm_holder_mount';
  await holder.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
  await holder.locator('#profile-personal-city').waitFor();
  await fillPersonal(holder, { city: 'Barrier City' });
  await postStartAttacker.goto(`${WEB}/s-10?section=personal`, {
    waitUntil: 'domcontentloaded',
  });
  await postStartAttacker.locator('#profile-personal-city').waitFor();
  await fillPersonal(postStartAttacker, { city: 'Must Not Dispatch' });
  let postStartOldActorMutationRequests = 0;
  postStartAttacker.on('request', (request) => {
    if (request.method() === 'PATCH'
      && new URL(request.url()).pathname === '/api/v1/student/profile/personal') {
      postStartOldActorMutationRequests += 1;
    }
  });
  await postStartAttacker.evaluate(() => {
    const probe = { listenerFired: false, controlFound: false, clickInvoked: false };
    Object.defineProperty(globalThis, Symbol.for('nyay5.profile-post-start-attempt.v1'), {
      configurable: false, value: probe, writable: false,
    });
    addEventListener('nyayone:student-auth-transition-started', () => {
      probe.listenerFired = true;
      const save = [...document.querySelectorAll('button')].find(
        (button) => button.textContent?.trim() === 'Save & continue',
      );
      probe.controlFound = Boolean(save);
      if (save) {
        probe.clickInvoked = true;
        save.click();
      }
    }, { once: true });
  });

  let releaseHeldResponse;
  let markServerSettled;
  const heldResponseReleased = new Promise((resolveRelease) => {
    releaseHeldResponse = resolveRelease;
  });
  const serverSettled = new Promise((resolveSettled) => { markServerSettled = resolveSettled; });
  let oldActorPatchCount = 0;
  holder.on('request', (request) => {
    if (request.method() === 'PATCH'
      && new URL(request.url()).pathname === '/api/v1/student/profile/personal') {
      oldActorPatchCount += 1;
    }
  });
  await holder.route('**/api/v1/student/profile/personal', async (route) => {
    const response = await route.fetch();
    markServerSettled(response.status());
    await heldResponseReleased;
    await route.fulfill({ response });
  }, { times: 1 });
  failureStage = 'cross_realm_holder_server_settle';
  await holder.getByRole('button', { name: 'Save & continue', exact: true }).click();
  if (await serverSettled !== 200) throw new Error('NYAY5_BARRIER_HOLDER_WRITE_FAILED');

  failureStage = 'cross_realm_prepare_second_login';
  // Retire actor A's browser credential only after its profile write has
  // settled. The subsequent start/state ceremony must mint and prove a fresh
  // server-owned actor B login flow before S-05 can expose OTP controls.
  await context.clearCookies({ name: 'nyayone_session' });
  await prepareStudentLoginOtp(initiator, actorBMobile);
  let verifyRequests = 0;
  initiator.on('request', (request) => {
    if (request.method() === 'POST'
      && new URL(request.url()).pathname === '/api/v1/auth/student/login/otp/verify') {
      verifyRequests += 1;
    }
  });
  const verifyResponsePromise = initiator.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/login/otp/verify'
  ));
  failureStage = 'cross_realm_start_second_verify';
  await initiator.getByRole('button', { name: 'Verify and continue', exact: true }).click();
  const pending = holder.getByTestId('student-session-pending');
  failureStage = 'cross_realm_wait_holder_pending';
  await pending.waitFor({ state: 'visible' });
  const verifyRequestsBeforeDelayedPeer = verifyRequests;
  const pendingSelectorCount = await pending.count();
  const privateMountedBeforeVerify = await holder.locator('[data-screen="S-10"]').count();
  const profilePostStartAttempt = await postStartAttacker.evaluate(() => (
    globalThis[Symbol.for('nyay5.profile-post-start-attempt.v1')]
  ));
  const profilePostStartAttemptObserved = profilePostStartAttempt?.listenerFired === true
    && (profilePostStartAttempt.controlFound === false
      || profilePostStartAttempt.clickInvoked === true);

  failureStage = 'cross_realm_late_realm_pending';
  const lateRealm = await context.newPage();
  let lateRealmSessionRequests = 0;
  lateRealm.on('request', (request) => {
    if (request.method() === 'GET'
      && new URL(request.url()).pathname === '/api/v1/auth/student/session') {
      lateRealmSessionRequests += 1;
    }
  });
  await lateRealm.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
  await lateRealm.getByTestId('student-session-pending').waitFor({ state: 'visible' });
  const newPageSessionRequestsBeforeEnd = lateRealmSessionRequests;
  const verifyRequestsBeforeInflightRelease = verifyRequests;

  failureStage = 'cross_realm_release_holder';
  releaseHeldResponse();
  const verifyResponse = await verifyResponsePromise;
  if (verifyResponse.status() !== 200) throw new Error('NYAY5_BARRIER_VERIFY_FAILED');
  failureStage = 'cross_realm_wait_second_landing';
  await initiator.waitForURL(/\/s-07$/u);
  await holder.unroute('**/api/v1/student/profile/personal');
  await holder.waitForTimeout(100);
  const actorBProjection = await profileProjection(context);
  const profileTransitionProtocolTrace = {
    initiator: await transitionTrace(initiator),
    peers: [await transitionTrace(holder), await transitionTrace(postStartAttacker)],
    lateRealm: await transitionTrace(lateRealm),
  };
  const transitionProtocolTrace = {
    ceremonies: [m01TransitionProtocolTrace, profileTransitionProtocolTrace],
  };
  const transitionMessagesExact = inspectTransitionProtocolTrace(transitionProtocolTrace).pass;
  const transitionMessageText = JSON.stringify(transitionProtocolTrace);
  const transitionMessagePrivateFindings = [...privateValues]
    .filter((value) => transitionMessageText.includes(value)).length;
  const oldActorAutomaticRetryCount = Math.max(0, oldActorPatchCount - 1);
  const newActorProjectionUnchanged = actorBProjection.status === 200
    && actorBProjection.body?.profile?.personal?.first_name === 'BarrierB'
    && actorBProjection.body?.profile?.personal?.city === null;
  await context.close();

  failureStage = 'cross_realm_missing_primitives';
  const missingPrimitives = await unsupportedTransitionContext(browser, () => {
    Object.defineProperty(globalThis, 'BroadcastChannel', {
      configurable: true, value: undefined, writable: true,
    });
    Object.defineProperty(navigator, 'locks', {
      configurable: true, value: undefined,
    });
  });
  failureStage = 'cross_realm_inaccessible_storage';
  const inaccessibleStorage = await inaccessibleStorageTransitionContext(browser, actorBMobile);
  failureStage = 'cross_realm_peer_nack';
  const peerNack = await transitionCleanupFailureProbe(browser, actorBMobile, 'peer-nack');
  const value = {
    delayedPeerObserved: pendingSelectorCount === 1,
    verifyRequestsBeforeDelayedPeer,
    pendingSelectorCount,
    privateMountedBeforeVerify,
    verifyRequestsBeforeInflightRelease,
    verifyRequests,
    oldActorPatchCount,
    oldActorAutomaticRetryCount,
    postStartOldActorMutationRequests,
    profilePostStartAttemptObserved,
    newPageSessionRequestsBeforeEnd,
    newActorProjectionUnchanged,
    transitionMessagesExact,
    transitionMessagePrivateFindings,
    missingPrimitivesUnavailable: missingPrimitives.unavailable,
    missingPrimitivesPrivateRequests: missingPrimitives.privateRequests,
    inaccessibleStorageUnavailable: inaccessibleStorage.unavailable,
    peerNackVerifyRequests: peerNack.verifyRequests,
    peerNackSessionCookieUnchanged: peerNack.cookieUnchanged,
    m01HolderCompletionControls,
    m01AttackerCompletionControls,
    m01ServerSettledStatus,
    m01VerifyRequestsBeforeResponseRelease,
    m01VerifyRequests: m01VerifyRequestsAtCompletion,
    m01CompletionRequests,
    m01CommitExactlyOnce,
    m01FirstTargetCompleted,
    m01FirstTargetAttendanceRecorded,
    m01PostStartSecondTargetRequests,
    m01PostStartAttemptObserved,
    m01PrivateControlsAfterTransitionStart,
    m01PrivateUiUnmounted,
    m01SecondTargetUntouched,
  };
  const inspected = inspectCrossRealmTransitionObservation(value);
  recordBrowserExecution(
    'cross_realm_auth_transition_barrier',
    inspected.pass,
    33,
    pendingSelectorCount + Number(missingPrimitives.unavailable)
      + Number(inaccessibleStorage.unavailable) + Number(peerNack.unavailable)
      + m01HolderCompletionControls + m01AttackerCompletionControls,
  );
  if (!inspected.pass) {
    const expected = {
      delayedPeerObserved: true,
      verifyRequestsBeforeDelayedPeer: 0,
      pendingSelectorCount: 1,
      privateMountedBeforeVerify: 0,
      verifyRequestsBeforeInflightRelease: 0,
      verifyRequests: 1,
      oldActorPatchCount: 1,
      oldActorAutomaticRetryCount: 0,
      postStartOldActorMutationRequests: 0,
      profilePostStartAttemptObserved: true,
      newPageSessionRequestsBeforeEnd: 0,
      newActorProjectionUnchanged: true,
      transitionMessagesExact: true,
      transitionMessagePrivateFindings: 0,
      missingPrimitivesUnavailable: true,
      missingPrimitivesPrivateRequests: 0,
      inaccessibleStorageUnavailable: true,
      peerNackVerifyRequests: 0,
      peerNackSessionCookieUnchanged: true,
      m01HolderCompletionControls: 2,
      m01AttackerCompletionControls: 2,
      m01ServerSettledStatus: 200,
      m01VerifyRequestsBeforeResponseRelease: 0,
      m01VerifyRequests: 1,
      m01CompletionRequests: 1,
      m01CommitExactlyOnce: true,
      m01FirstTargetCompleted: true,
      m01FirstTargetAttendanceRecorded: true,
      m01PostStartSecondTargetRequests: 0,
      m01PostStartAttemptObserved: true,
      m01PrivateControlsAfterTransitionStart: 0,
      m01PrivateUiUnmounted: true,
      m01SecondTargetUntouched: true,
    };
    const failedField = Object.keys(expected).find((field) => value[field] !== expected[field]);
    const safeField = String(failedField ?? 'unknown').replace(/([a-z])([A-Z])/gu, '$1_$2')
      .toUpperCase();
    throw new Error(`NYAY5_CROSS_REALM_${safeField}`);
  }
  return { ...value, pass: inspected.pass };
}

function canonical401DraftHandoffProbe(metrics) {
  const row = metrics?.canonical401;
  return Boolean(row
    && row.kind === '401'
    && row.canonicalCode === 'authentication_required'
    && row.sameActorResolved === true
    && row.restoredSelectorCount === 1
    && row.profilePatchCount === 1
    && row.automaticRetryCount === 0
    && row.browserPersistenceClean === true);
}

async function profileProjection(context) {
  const response = await context.request.get(`${API}/api/v1/student/profile`);
  const body = response.ok() ? await response.json() : null;
  return { status: response.status(), body, inspected: inspectNyay5Projection(body) };
}

async function fillPersonal(page, { city = 'Pune', firstName = 'Nyaay' } = {}) {
  await page.locator('#profile-personal-first-name').fill(firstName);
  await page.locator('#profile-personal-last-name').fill('Boundary');
  await page.locator('#profile-personal-language').selectOption('en');
  await page.locator('#profile-personal-city').fill(city);
}

function personalMutation(projection, expectedProfileVersion, overrides = {}) {
  const personal = projection?.profile?.personal;
  return {
    expected_profile_version: expectedProfileVersion,
    first_name: personal?.first_name,
    middle_name: personal?.middle_name,
    last_name: personal?.last_name,
    date_of_birth: personal?.date_of_birth,
    preferred_language: personal?.preferred_language,
    city: personal?.city,
    pronouns: personal?.pronouns,
    ...overrides,
  };
}

function profileFixtureIdempotencyKey() {
  const key = `nyay5-profile-${randomBytes(24).toString('hex')}`;
  rememberPrivate(key);
  return key;
}

async function patchPersonalProjection(context, projection, overrides = {}) {
  return context.request.patch(`${API}/api/v1/student/profile/personal`, {
    headers: {
      Origin: WEB_ORIGIN,
      'Idempotency-Key': profileFixtureIdempotencyKey(),
    },
    data: personalMutation(projection, projection?.profile_version, overrides),
  });
}

async function fillAcademicDraft(page, enrolmentNumber) {
  await page.locator('#profile-academic-college').selectOption({ index: 1 });
  await page.locator('#profile-academic-year').selectOption({ index: 1 });
  await page.locator('#profile-academic-enrolment').fill(enrolmentNumber);
}

async function fillInterestsDraft(page) {
  await page.locator('#profile-interests-first-option').click();
  await page.locator('#profile-interests-goal').selectOption({ index: 1 });
}

function countSectionPatches(page, pathname) {
  const state = { count: 0 };
  page.on('request', (request) => {
    if (request.method() === 'PATCH' && new URL(request.url()).pathname === pathname) {
      state.count += 1;
    }
  });
  return state;
}

const PROFILE_TYPED_FAILURE_ROUTE = '**/api/v1/student/profile/personal';

function persistenceDiagnostic(result) {
  if (result.pass) return 'clean';
  if (result.unexpectedLocalCount > 0) return 'unexpected_local';
  if (!result.localValueContractExact) return 'local_value';
  if (result.sessionCount > 0) return 'session_storage';
  if (!result.cacheInventoryExact) return 'cache_inventory';
  if (!result.serviceWorkerExact) return 'service_worker';
  if (!result.privacyInstrumentationExact) return 'privacy_instrumentation';
  if (result.indexedDatabaseCount > 0) return 'indexed_database';
  if (result.javascriptCookieCount > 0) return 'javascript_cookie';
  if (result.deterministicGlobalCount > 0) return 'deterministic_global';
  return 'serialized_private';
}

async function typedFailureMatrixProbe(page, context, mobile, sessionActor) {
  const cases = [
    { kind: 'missing_context', status: 422 },
    { kind: '401', status: 401, code: 'authentication_required' },
    { kind: '403', status: 403, code: 'profile_write_forbidden' },
    { kind: '409', status: 409, code: 'profile_version_conflict' },
    { kind: '422', status: 422, code: 'invalid_profile_field' },
    { kind: '429', status: 429, code: 'rate_limited' },
    { kind: '500', status: 500, code: 'profile_write_unavailable' },
    { kind: 'abort', status: null, abortCode: 'aborted' },
    { kind: 'timeout', status: null, timeout: true },
    { kind: 'network', status: null, abortCode: 'connectionfailed' },
  ];
  const rows = [];

  for (const [index, fixture] of cases.entries()) {
    failureStage = `complete_profile_typed_failure_${fixture.kind}_prepare`;
    const city = `Pune ${index + 1}`;
    await page.locator('#profile-personal-city').fill(city);
    let markHandled;
    const handled = new Promise((resolveHandled) => { markHandled = resolveHandled; });
    let profilePatchCount = 0;
    const trackPatch = (request) => {
      if (request.method() === 'PATCH'
        && new URL(request.url()).pathname === '/api/v1/student/profile/personal') {
        profilePatchCount += 1;
      }
    };
    page.on('request', trackPatch);
    let releaseSessionDiscovery = null;
    let sessionDiscoveryHeld = null;
    if (fixture.kind === '401') {
      const logout = await context.request.post(`${API}/api/v1/auth/student/logout`, {
        headers: { Origin: WEB_ORIGIN }, data: {},
      });
      if (logout.status() !== 200) throw new Error('NYAY5_CANONICAL_401_LOGOUT_FAILED');
      sessionDiscoveryHeld = new Promise((resolveHeld) => { releaseSessionDiscovery = resolveHeld; });
      await page.route('**/api/v1/auth/student/session', async (route) => {
        await sessionDiscoveryHeld;
        const response = await route.fetch();
        await route.fulfill({ response });
      }, { times: 1 });
    }
    await page.route(PROFILE_TYPED_FAILURE_ROUTE, async (route) => {
      try {
        if (fixture.kind === '401') {
          const response = await route.fetch();
          const body = await response.json().catch(() => null);
          fixture.observedCode = body?.detail?.code ?? null;
          markHandled(response.status());
          await route.fulfill({ response });
          return;
        }
        if (fixture.kind === 'missing_context') {
          const body = route.request().postDataJSON();
          delete body.expected_profile_version;
          const response = await route.fetch({ postData: JSON.stringify(body) });
          markHandled(response.status());
          await route.fulfill({ response });
          return;
        }
        if (fixture.timeout) {
          await new Promise((resolveDelay) => setTimeout(resolveDelay, 10_250));
          markHandled(null);
          await route.abort('timedout').catch(() => {});
          return;
        }
        if (fixture.abortCode) {
          markHandled(null);
          await route.abort(fixture.abortCode);
          return;
        }
        markHandled(fixture.status);
        await route.fulfill({
          status: fixture.status,
          contentType: 'application/json',
          body: JSON.stringify({ detail: { code: fixture.code } }),
        });
      } catch {
        markHandled(fixture.status);
        await route.abort('failed').catch(() => {});
      }
    }, { times: 1 });

    const previousError = page.getByTestId('profile-save-error');
    failureStage = `complete_profile_typed_failure_${fixture.kind}_submit`;
    await page.getByRole('button', { name: 'Save & continue' }).click();
    const observedStatus = await handled;
    if (fixture.kind === '401') {
      failureStage = 'complete_profile_typed_failure_401_boundary';
      const pending = page.getByTestId('student-session-pending');
      await pending.waitFor({ state: 'visible' });
      const pendingObserved = await pending.isVisible();
      const privateUnmounted = await page.locator('[data-screen="S-10"]').count() === 0;
      releaseSessionDiscovery();
      await page.waitForURL(/\/s-03(?:$|[?#])/u);
      const anonymousObserved = new URL(page.url()).pathname === '/s-03';
      failureStage = 'complete_profile_typed_failure_401_reauthentication';
      const {
        startResponse,
        verifyResponse,
        verifiedSessionResponse,
        verifiedSessionFinishedError,
      } = await loginStudentThroughUi(page, mobile);
      const verifiedSessionBody = verifiedSessionResponse.status() === 200
        && verifiedSessionFinishedError === null
        ? await verifiedSessionResponse.json().catch(() => null)
        : null;
      if (verifiedSessionResponse.status() !== 200
          || verifiedSessionFinishedError !== null
          || verifiedSessionBody?.authenticated !== true
          || !verifiedSessionBody?.actor?.roles?.includes('student')
          || verifiedSessionBody?.actor?.sub !== sessionActor?.sub) {
        failureStage = 'complete_profile_typed_failure_401_reauth_authority_invalid';
        throw new Error('NYAY5_CANONICAL_401_REAUTH_AUTHORITY_INVALID');
      }
      failureStage = 'complete_profile_typed_failure_401_private_rediscovery';
      try {
        await page.waitForURL(/\/s-10\?section=personal$/u);
      } catch (error) {
        const observedPath = new URL(page.url()).pathname;
        const screenMatch = /^\/s-(\d{2})$/u.exec(observedPath);
        const safeRoute = screenMatch ? `s${screenMatch[1]}`
          : observedPath === '/' ? 'root' : 'other';
        failureStage = `complete_profile_typed_failure_401_private_rediscovery_${safeRoute}`;
        throw error;
      }
      const restored = page.getByTestId('profile-reauth-draft-restored');
      await restored.waitFor({ state: 'visible' });
      const session = await context.request.get(`${API}/api/v1/auth/student/session`);
      const sessionBody = session.ok() ? await session.json() : null;
      const persistenceSnapshot = await storageSnapshot(page);
      const persistence = inspectBrowserPersistence(persistenceSnapshot);
      const persistenceCode = persistenceDiagnostic(persistence);
      rows.push({
        kind: fixture.kind,
        status: observedStatus,
        canonicalCode: fixture.observedCode,
        pendingObserved,
        privateUnmounted,
        anonymousObserved,
        sameActorResolved: startResponse.status() === 202
          && verifyResponse.status() === 200
          && sessionBody?.actor?.sub === sessionActor?.sub,
        restoredSelectorCount: await restored.count(),
        profilePatchCount,
        automaticRetryCount: Math.max(0, profilePatchCount - 1),
        browserPersistenceClean: persistence.pass,
        browserPersistenceCode: persistenceCode,
        browserPersistenceServiceWorker: persistenceSnapshot.serviceWorker,
        routeRetained: new URL(page.url()).pathname === '/s-10'
          && new URL(page.url()).search === '?section=personal',
        valuesRetained: await page.locator('#profile-personal-city').inputValue() === city,
        errorRole: await restored.getAttribute('role'),
        errorVisible: await restored.isVisible(),
        errorText: (await restored.textContent())?.trim() ?? '',
      });
      await page.unroute(PROFILE_TYPED_FAILURE_ROUTE);
      await page.unroute('**/api/v1/auth/student/session').catch(() => {});
      page.off('request', trackPatch);
      continue;
    }
    failureStage = `complete_profile_typed_failure_${fixture.kind}_error_state`;
    await previousError.waitFor({ state: 'visible', timeout: 25_000 });
    const row = {
      kind: fixture.kind,
      status: observedStatus,
      routeRetained: new URL(page.url()).pathname === '/s-10'
        && new URL(page.url()).searchParams.get('section') === 'personal',
      valuesRetained: await page.locator('#profile-personal-city').inputValue() === city,
      errorRole: await previousError.getAttribute('role'),
      errorVisible: await previousError.isVisible(),
      errorText: (await previousError.textContent())?.trim() ?? '',
    };
    rows.push(row);
    await page.unroute(PROFILE_TYPED_FAILURE_ROUTE);
    page.off('request', trackPatch);
  }

  return { rows, inspected: inspectTypedFailureMatrix(rows) };
}

async function storageSnapshot(page) {
  const viteClientResponse = await fetch(`${WEB}/@vite/client`);
  const viteClientText = viteClientResponse.ok ? await viteClientResponse.text() : '';
  const viteClientLooksLikeHtmlFallback = !viteClientResponse.ok
    || (viteClientResponse.headers.get('content-type')?.toLowerCase().includes('text/html') === true
      && /<!doctype html|<html/iu.test(viteClientText));
  const indexResponse = await fetch(`${WEB}/`);
  const indexText = indexResponse.ok ? await indexResponse.text() : '';
  const assetPaths = [...indexText.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/gu)]
    .map((match) => match[1]);
  const assetTexts = await Promise.all(assetPaths.map(async (path) => {
    const response = await fetch(`${WEB}${path}`);
    return response.ok ? response.text() : '';
  }));
  const productionAssets = viteClientLooksLikeHtmlFallback
    && indexResponse.ok
    && assetPaths.length > 0
    && assetTexts.every((value) => value.length > 0);
  const disableFlagAbsent = assetTexts.every((value) => (
    !value.includes('VITE_DISABLE_SERVICE_WORKER')
    && !value.includes('NYAY5_DISABLE_SERVICE_WORKER')
  ));
  return page.evaluate(async ({ productionAssetsExact, disableFlagIsAbsent }) => {
    if ('serviceWorker' in navigator) {
      await Promise.race([
        navigator.serviceWorker.ready,
        new Promise((resolveTimeout) => setTimeout(resolveTimeout, 5_000)),
      ]);
      for (let attempt = 0; attempt < 50 && !navigator.serviceWorker.controller; attempt += 1) {
        await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
      }
    }
    const localStorageEntries = Object.entries(localStorage).sort(([left], [right]) => (
      left.localeCompare(right)
    ));
    const registrations = 'serviceWorker' in navigator
      ? await navigator.serviceWorker.getRegistrations() : [];
    const cacheInventory = [];
    if ('caches' in window) {
      for (const name of (await caches.keys()).sort()) {
        const cache = await caches.open(name);
        const entries = [];
        for (const request of await cache.keys()) {
          const response = await cache.match(request);
          const url = new URL(request.url);
          entries.push({
            pathname: url.pathname,
            query: url.search,
            method: request.method,
            credentials: request.credentials,
            authorization: request.headers.has('authorization'),
            responseStatus: response?.status ?? 0,
          });
        }
        entries.sort((left, right) => left.pathname.localeCompare(right.pathname));
        cacheInventory.push({ name, entries });
      }
    }
    const privacyProbe = window[Symbol.for('nyay5.browser.privacy-probe.v1')];
    const newGlobalKeys = privacyProbe
      ? Reflect.ownKeys(window).filter((key) => (
        typeof key === 'string' && !privacyProbe.initialGlobalKeys.has(key)
      )) : [];
    let globalPrivateDetected = !privacyProbe;
    if (privacyProbe) {
      for (const key of newGlobalKeys) {
        let descriptor;
        try {
          descriptor = Object.getOwnPropertyDescriptor(window, key);
        } catch {
          globalPrivateDetected = true;
          break;
        }
        if (descriptor && Object.prototype.hasOwnProperty.call(descriptor, 'value')
          && privacyProbe.containsPrivate({ [key]: descriptor.value })) {
          globalPrivateDetected = true;
          break;
        }
      }
    }
    return {
      origin: location.origin,
      localStorageKeys: localStorageEntries.map(([key]) => key),
      localStorageEntries,
      sessionStorageKeys: Object.keys(sessionStorage).sort(),
      cacheInventory,
      serviceWorker: {
        supported: 'serviceWorker' in navigator,
        controlled: Boolean(navigator.serviceWorker?.controller),
        registrations: registrations.length,
        scriptPathnames: registrations.map((registration) => new URL(
          registration.active?.scriptURL
            ?? registration.waiting?.scriptURL
            ?? registration.installing?.scriptURL
            ?? location.href,
        ).pathname).sort(),
        productionAssets: productionAssetsExact,
        disableFlagAbsent: disableFlagIsAbsent,
      },
      indexedDatabases: 'databases' in indexedDB
        ? (await indexedDB.databases()).map((entry) => entry.name ?? '') : [],
      javascriptCookieNames: document.cookie
        .split(';').map((entry) => entry.split('=', 1)[0].trim()).filter(Boolean),
      deterministicGlobalKeys: newGlobalKeys.filter((key) => (
        /(?:actor|profile|registration|session).*(?:id|token)/iu.test(key)
      )),
      historyUrls: [location.href],
      privacyInstrumentation: {
        installed: privacyProbe?.installed === true,
        historyCallsObserved: privacyProbe?.historyCallsObserved ?? 0,
        transientHistoryPrivateDetected:
          privacyProbe?.transientHistoryPrivateDetected !== false,
        globalsScanned: newGlobalKeys.length,
        globalPrivateDetected,
        windowNamePrivateDetected: privacyProbe
          ? privacyProbe.containsPrivate(window.name) : true,
        historyStatePrivateDetected: privacyProbe
          ? privacyProbe.containsPrivate(history.state) : true,
      },
    };
  }, { productionAssetsExact: productionAssets, disableFlagIsAbsent: disableFlagAbsent });
}

async function pendingAndDenialProbe(browser) {
  const context = await createNyay5Context(browser);
  const page = await context.newPage();
  let releaseSession;
  const held = new Promise((resolveHeld) => { releaseSession = resolveHeld; });
  let pendingPrivateRequestCount = 0;
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/v1/student/profile')) pendingPrivateRequestCount += 1;
  });
  await page.route('**/api/v1/auth/student/session', async (route) => {
    await held;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: {
        'Access-Control-Allow-Origin': WEB_ORIGIN,
        'Access-Control-Allow-Credentials': 'true',
      },
      body: JSON.stringify({ authenticated: false, actor: null }),
    });
  });
  const navigation = page.goto(`${WEB}/s-14`, { waitUntil: 'domcontentloaded' });
  await page.getByTestId('student-session-pending').waitFor({ state: 'visible' });
  const privateMounted = await page.locator('[data-screen="S-14"]').count();
  const pendingObservation = inspectPendingSessionObservation({
    sessionPending: true,
    privateMounted,
    privateRequestCount: pendingPrivateRequestCount,
  });
  observe(
    'pending_session_fail_closed',
    pendingObservation.pass,
    { privateMounted, privateRequestCount: pendingPrivateRequestCount },
  );
  releaseSession();
  await navigation;
  await page.waitForURL(/\/s-03(?:$|[?#])/u);
  const anonymousDenied = new URL(page.url()).pathname === '/s-03';
  await page.unrouteAll({ behavior: 'wait' });
  let anonymousS15PostCount = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST'
      && new URL(request.url()).pathname
        === '/api/v1/auth/student/verification/email/request') {
      anonymousS15PostCount += 1;
    }
  });
  await page.goto(`${WEB}/s-15`, { waitUntil: 'domcontentloaded' });
  await page.waitForURL(/\/s-03(?:$|[?#])/u);
  const anonymousRedirectSelectors = await page.locator('[data-screen="S-03"]').count();
  const s15AnonymousDisabled = anonymousS15PostCount === 0
    && await page.getByRole('button', { name: 'Request verification review' }).count() === 0
    && anonymousRedirectSelectors === 1;
  recordBrowserExecution(
    's15_anonymous_disabled', s15AnonymousDisabled, 1, anonymousRedirectSelectors,
  );

  await context.close();

  const fixtures = await readDenialFixtures();
  const realDenials = [];
  let privateRequestCount = 0;
  const states = ['expired', 'revoked', 'deleted', 'wrong_role'];
  for (const state of states) {
    const realContext = await denialContext(browser, fixtures[state].token);
    const denialPage = await realContext.newPage();
    denialPage.on('request', (request) => {
      if (new URL(request.url()).pathname.startsWith('/api/v1/student/profile')) {
        privateRequestCount += 1;
      }
    });
    const sessionResponsePromise = denialPage.waitForResponse((response) => (
      new URL(response.url()).pathname === '/api/v1/auth/student/session'
    ));
    await denialPage.goto(`${WEB}/s-14`, { waitUntil: 'domcontentloaded' });
    const sessionResponse = await sessionResponsePromise;
    const sessionBody = sessionResponse.status() === 200
      ? await sessionResponse.json() : null;
    let denied;
    if (state === 'wrong_role') {
      denied = await denialPage.getByTestId('student-route-wrong-role').isVisible()
        && sessionBody?.authenticated === true
        && sessionBody?.actor?.roles?.includes('moderator');
    } else {
      await denialPage.waitForURL(/\/s-03(?:$|[?#])/u);
      denied = sessionBody?.authenticated === false && sessionBody?.actor === null;
    }
    realDenials.push(denied);
    await realContext.close();
  }
  const [expiredDenied, revokedDenied, deletedDenied, wrongRoleDenied] = realDenials;
  const denialObservation = inspectDenialObservation({
    anonymousDenied,
    expiredDenied,
    revokedDenied,
    deletedDenied,
    wrongRoleDenied,
    privateRequestCount,
  });
  observe('denial_matrix_fail_closed', denialObservation.pass
    && privateRequestCount === 0 && realDenials.every(Boolean), {
    cases: 5,
    passed: Number(anonymousDenied) + realDenials.filter(Boolean).length,
    privateRequestCount,
    realDenialsExact: realDenials.every(Boolean),
  });
}

const storageChecks = [];

function trackActorBoundary(page) {
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.origin !== API_ORIGIN || !url.pathname.startsWith('/api/v1/student/profile')) return;
    let exact;
    try {
      exact = inspectActorChannel({
        url: () => request.url(),
        headersArray: () => Object.entries(request.headers())
          .map(([name, value]) => ({ name, value })),
        postDataJSON: () => request.postDataJSON(),
      }).pass;
    } catch {
      exact = false;
    }
    requests.push(exact);
  });
}

async function recordStorage(page, surface) {
  const snapshot = await storageSnapshot(page);
  const privateLeak = [...privateValues].some((value) => JSON.stringify(snapshot).includes(value));
  const result = inspectBrowserPersistence(snapshot);
  storageChecks.push({ surface, pass: result.pass && !privateLeak });
}

async function completeProfileProbe(browser) {
  const { context, mobile, sessionActor } = await provisionStudent(browser);
  const page = await context.newPage();
  trackActorBoundary(page);
  failureStage = 'complete_profile_s10_navigation';
  const s10Readiness = armCanonicalReadiness(page, {
    apiOrigin: API_ORIGIN,
    requirements: [
      { kind: 'session' },
      { kind: 'profile' },
    ],
    stage: 'complete_profile_s10',
  });
  const s10SessionResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === 'GET'
      && url.origin === API_ORIGIN
      && url.pathname === '/api/v1/auth/student/session'
      && url.search === ''
      && url.hash === '';
  });
  const s10ProfileResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === 'GET'
      && url.origin === API_ORIGIN
      && url.pathname === '/api/v1/student/profile'
      && url.search === ''
      && url.hash === '';
  });
  await page.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
  const settledReadiness = settleCanonicalReadiness(s10Readiness);
  failureStage = 'complete_profile_s10_authority';
  const [s10SessionResponse, s10ProfileResponse] = await Promise.all([
    s10SessionResponsePromise,
    s10ProfileResponsePromise,
  ]);
  const [s10SessionFinishedError, s10ProfileFinishedError] = await Promise.all([
    s10SessionResponse.finished(),
    s10ProfileResponse.finished(),
  ]);
  const s10SessionBody = s10SessionResponse.status() === 200
    && s10SessionFinishedError === null
    ? await s10SessionResponse.json().catch(() => null)
    : null;
  if (s10SessionResponse.status() !== 200
      || s10SessionFinishedError !== null
      || s10SessionBody?.authenticated !== true
      || !s10SessionBody?.actor?.roles?.includes('student')
      || s10SessionBody?.actor?.sub !== sessionActor?.sub) {
    throw new Error('NYAY5_COMPLETE_PROFILE_SESSION_AUTHORITY_INVALID');
  }
  if (s10ProfileResponse.status() !== 200 || s10ProfileFinishedError !== null) {
    throw new Error('NYAY5_COMPLETE_PROFILE_PROJECTION_UNAVAILABLE');
  }
  failureStage = 'complete_profile_s10_mount';
  await waitForRouteDomSettled(page, '/s-10', {
    settledReadiness,
    selector: '#profile-personal-city',
    expectedSearch: '?section=personal',
  });
  await page.locator('#profile-personal-city').waitFor();
  failureStage = 'complete_profile_visual_contract';
  await recordVisualContract(page, 'S-10');
  failureStage = 'complete_profile_initial_projection';
  const initial = await profileProjection(context);

  failureStage = 'complete_profile_client_validation';
  await page.locator('#profile-personal-city').fill('');
  await page.getByRole('button', { name: 'Save & continue' }).click();
  const errorSummary = page.getByTestId('profile-error-summary');
  await errorSummary.waitFor();
  const clientErrorAccessible = await errorSummary.evaluate((node) => (
    node.getAttribute('role') === 'alert' && document.activeElement === node
  ));
  const validationSelectorCount = await errorSummary.count()
    + await page.locator('#profile-personal-city').count();

  await fillPersonal(page, { city: 'Pune' });
  failureStage = 'complete_profile_typed_failure_matrix';
  const typedFailures = await typedFailureMatrixProbe(page, context, mobile, sessionActor);
  await page.locator('#profile-personal-city').fill('Pune');

  failureStage = 'complete_profile_personal_write';
  let releaseWrite;
  let markStarted;
  const writeHeld = new Promise((resolveHeld) => { releaseWrite = resolveHeld; });
  const writeStarted = new Promise((resolveStarted) => { markStarted = resolveStarted; });
  await page.route('**/api/v1/student/profile/personal', async (route) => {
    markStarted();
    await writeHeld;
    const response = await route.fetch();
    await route.fulfill({ response });
  });
  await page.getByRole('button', { name: 'Save & continue' }).click();
  await writeStarted;
  const stayedUntilSettled = new URL(page.url()).searchParams.get('section') === 'personal';
  releaseWrite();
  await page.waitForURL(/\/s-10\?section=academic$/u);
  await page.unroute('**/api/v1/student/profile/personal');
  const afterPersonal = await profileProjection(context);
  const personalProgress = Number(
    await page.getByTestId('profile-completion-percent').getAttribute('aria-valuenow'),
  );
  const profileProjectionSelectorCount = await page.locator(
    '[data-testid="profile-completion-percent"], #profile-academic-college',
  ).count();

  failureStage = 'complete_profile_resume_projection';
  const resumed = await context.newPage();
  trackActorBoundary(resumed);
  await resumed.goto(`${WEB}/s-13`, { waitUntil: 'domcontentloaded' });
  await resumed.getByText(/34% done/u).waitFor();
  await recordVisualContract(resumed, 'S-13');
  const reloadResume = (await resumed.getByText('Continue here').count()) === 1;
  await resumed.reload({ waitUntil: 'domcontentloaded' });
  await resumed.getByText(/34% done/u).waitFor({ state: 'visible' });
  const reloadStillResume = (await resumed.getByText(/34% done/u).count()) === 1;
  await resumed.close();

  failureStage = 'complete_profile_academic_write';
  await page.locator('#profile-academic-college').selectOption({ index: 1 });
  await page.locator('#profile-academic-year').selectOption({ index: 1 });
  await page.locator('#profile-academic-enrolment').fill('QA/42/2026');
  await page.locator('#profile-academic-email').fill('student@synthetic.edu');
  rememberPrivate('student@synthetic.edu');
  await page.getByRole('button', { name: 'Save & continue' }).click();
  await page.waitForURL(/\/s-11$/u);
  const afterAcademic = await profileProjection(context);

  failureStage = 'complete_profile_verification_ceremony';
  const ceremonyPosts = [];
  const profileReadsBeforeS15 = requests.length;
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (request.method() === 'POST'
      && url.pathname === '/api/v1/auth/student/verification/email/request') {
      let body;
      try {
        body = request.postDataJSON();
      } catch {
        body = null;
      }
      ceremonyPosts.push({
        pathname: url.pathname,
        query: url.search,
        body,
      });
    }
  });
  await page.goto(`${WEB}/s-15`, { waitUntil: 'domcontentloaded' });
  await recordVisualContract(page, 'S-15');
  const ceremonyButton = page.getByRole('button', { name: 'Request verification review' });
  await ceremonyButton.waitFor();
  const ceremonyActionSelectorCount = await ceremonyButton.count();
  const ceremonySelectorCount = await page.locator([
    'input[type="email"]',
    'input[name*="email" i]',
    'select[name*="email" i]',
  ].join(',')).count();
  const s15Refetched = requests.length > profileReadsBeforeS15;
  const ceremonyResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === '/api/v1/auth/student/verification/email/request'
  ));
  await ceremonyButton.click();
  const ceremonyResponse = await ceremonyResponsePromise;
  const ceremonyStatus = ceremonyResponse.status();
  const ceremonyBody = ceremonyResponse.ok() ? await ceremonyResponse.json() : null;
  const ceremonyProjectionExact = inspectNyay5Projection(ceremonyBody).pass;
  const ceremonyRetryResponse = await context.request.post(
    `${API}/api/v1/auth/student/verification/email/request`,
    { headers: { Origin: WEB_ORIGIN }, data: {} },
  );
  const ceremonyRetryStatus = ceremonyRetryResponse.status();
  const ceremonyRetryBody = ceremonyRetryResponse.ok()
    ? await ceremonyRetryResponse.json() : null;
  failureStage = 'complete_profile_dashboard_return';
  const ceremonyRetryProjectionExact = inspectNyay5Projection(ceremonyRetryBody).pass;
  const s15BackButton = page.getByRole('button', { name: 'Back to dashboard', exact: true });
  const s15BackSelectorCount = await s15BackButton.count();
  await s15BackButton.click();
  await page.waitForURL((url) => url.pathname === '/s-14');
  await page.locator('[data-screen="S-14"]').waitFor();
  const s15BackUrl = new URL(page.url());
  const s15BackExact = s15BackSelectorCount === 1
    && s15BackUrl.pathname === '/s-14'
    && s15BackUrl.search === ''
    && s15BackUrl.hash === '';
  await recordVisualContract(page, 'S-14');
  failureStage = 'complete_profile_interests_write';
  await page.goto(`${WEB}/s-11`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: 'What should find you?', exact: true }).waitFor({ state: 'visible' });
  await recordVisualContract(page, 'S-11');
  const interestsGoalLabel = page.locator('label[for="profile-interests-goal"]');
  await interestsGoalLabel.waitFor({ state: 'visible' });
  const interestsGoalLabelCount = await interestsGoalLabel.count();
  await page.locator('#profile-interests-first-option').click();
  await page.locator('#profile-interests-goal').selectOption({ index: 1 });
  await page.getByRole('button', { name: 'Finish setup' }).click();
  await page.waitForURL(/\/s-12$/u);
  await recordVisualContract(page, 'S-12');
  failureStage = 'complete_profile_final_projection';
  const completed = await profileProjection(context);

  observe('single_authoritative_projection', initial.status === 200
    && initial.inspected.pass && afterPersonal.inspected.pass
    && afterAcademic.inspected.pass && completed.inspected.pass, {
    projections: 4,
    exact: [initial, afterPersonal, afterAcademic, completed]
      .filter((entry) => entry.inspected.pass).length,
    selectorCount: profileProjectionSelectorCount,
  });
  const confirmedWriteObservation = inspectConfirmedWriteObservation({
    serverSettled: afterPersonal.status === 200
      && afterPersonal.body?.completion_percent === 34,
    status: afterPersonal.status,
    heldBeforeNavigation: stayedUntilSettled,
    navigated: new URL(page.url()).pathname === '/s-12',
  });
  observe('confirmed_success_before_navigation', confirmedWriteObservation.pass, {
    heldBeforeNavigation: stayedUntilSettled,
    finalStatus: afterPersonal.status,
    selectorCount: profileProjectionSelectorCount,
  });
  observe('typed_failures_retain_route_and_values', typedFailures.inspected.pass, {
    cases: typedFailures.inspected.total,
    passed: typedFailures.inspected.passed,
    selectorCount: typedFailures.rows.filter((row) => row.errorVisible).length,
    canonical401: typedFailures.rows.find((row) => row.kind === '401') ?? null,
  });
  observe('completion_server_derived', personalProgress === 34
    && afterAcademic.body?.completion_percent === 67
    && completed.body?.completion_percent === 100
    && completed.body?.completed_sections?.join(',') === 'personal,academic,interests', {
    checkpoints: 3,
    matched: Number(personalProgress === 34)
      + Number(afterAcademic.body?.completion_percent === 67)
      + Number(completed.body?.completion_percent === 100),
  });
  const verificationObservation = inspectVerificationObservation({
    completionPercent: completed.body?.completion_percent,
    institutionalStatus: completed.body?.institutional_email_status,
    pagePosts: ceremonyPosts,
    status: ceremonyStatus,
    projectionExact: ceremonyProjectionExact,
    responseInstitutionalStatus: ceremonyBody?.institutional_email_status,
    selectorCount: ceremonySelectorCount,
    retryStatus: ceremonyRetryStatus,
    retryProjectionExact: ceremonyRetryProjectionExact,
    retryInstitutionalStatus: ceremonyRetryBody?.institutional_email_status,
    responseProfileVersion: ceremonyBody?.profile_version,
    retryProfileVersion: ceremonyRetryBody?.profile_version,
    refetched: s15Refetched,
  });
  const ceremonyWireExact = ceremonyPosts.length === 1
    && ceremonyStatus === 202
    && ceremonyBody?.institutional_email_status === 'pending'
    && ceremonySelectorCount === 0
    && ceremonyRetryStatus === 202
    && ceremonyRetryBody?.profile_version === ceremonyBody?.profile_version;
  observe('verification_distinct_from_completion', verificationObservation.pass
    && ceremonyWireExact && s15BackExact, {
    completion: completed.body?.completion_percent,
    ceremonyPostCount: ceremonyPosts.length,
    ceremonyStatus,
    ceremonySelectorCount,
    ceremonyRetryStatus,
    s15Refetched,
    s15BackExact,
    s15BackSelectorCount,
    actionSelectorCount: ceremonyActionSelectorCount,
  });
  const accessibleSelectorCount = await errorSummary.locator('a').count()
    + interestsGoalLabelCount
    + typedFailures.rows.filter((row) => row.errorVisible).length;
  observe('accessible_errors_and_controls', clientErrorAccessible
    && typedFailures.rows.every((row) => (
      row.errorRole === (row.kind === '401' ? 'status' : 'alert') && row.errorVisible
    ))
    && interestsGoalLabelCount === 1, {
    errorSummaryFocused: clientErrorAccessible,
    controlsLabelled: interestsGoalLabelCount === 1,
    selectorCount: accessibleSelectorCount,
  });
  const bypassSelectorCount = await page.getByRole('button', {
    name: /mark fields corrected|reviewer|demo/iu,
  }).count();
  recordBrowserExecution(
    'field_validation_no_bypass',
    clientErrorAccessible && bypassSelectorCount === 0,
    2,
    validationSelectorCount,
  );
  observe('reload_new_tab_resume', reloadResume && reloadStillResume, {
    newTab: reloadResume,
    reload: reloadStillResume,
    selectorCount: Number(reloadResume) + Number(reloadStillResume),
  });
  await recordStorage(page, 'profile');
  await context.close();
}

async function promptAndRoutingProbe(browser) {
  failureStage = 'prompt_routing_provision';
  const { context, mobile } = await provisionStudent(browser);
  const page = await context.newPage();
  trackActorBoundary(page);
  const redirects = [];
  for (const path of ['/s-11', '/s-10/', '/s-10?section=unknown']) {
    failureStage = `prompt_routing_redirect_${path.replace(/[^a-z0-9]+/giu, '_')}`;
    await page.goto(`${WEB}${path}`, { waitUntil: 'domcontentloaded' });
    await page.waitForURL(/\/s-10\?section=personal$/u);
    const routeExact = new URL(page.url()).pathname === '/s-10'
      && new URL(page.url()).searchParams.get('section') === 'personal';
    const personalScreenCount = await page.locator('[data-screen="S-10"]').count();
    redirects.push({ pass: routeExact && personalScreenCount === 1, personalScreenCount });
  }
  observe('direct_step_skip_denied', redirects.every((row) => row.pass), {
    cases: redirects.length,
    passed: redirects.filter((row) => row.pass).length,
    selectorCount: redirects.reduce((total, row) => total + row.personalScreenCount, 0),
  });

  failureStage = 'prompt_routing_initial_dialog';
  await page.goto(`${WEB}/s-07`, { waitUntil: 'domcontentloaded' });
  await recordVisualContract(page, 'S-07');
  const dialog = page.getByTestId('profile-completion-dialog');
  await dialog.waitFor();
  const promptHostSelectors = await dialog.count();
  recordBrowserExecution(
    's07_prompt_host',
    new URL(page.url()).pathname === '/s-07'
      && promptHostSelectors === 1
      && await page.locator('[data-screen="S-14"]').count() === 0,
    1,
    promptHostSelectors,
  );
  const heading = page.getByRole('heading', { name: 'Complete your profile' });
  const initialFocus = await heading.evaluate((node) => document.activeElement === node);
  const inert = await page.getByTestId('profile-prompt-background').evaluate((node) => (
    node.hasAttribute('inert') && node.getAttribute('aria-hidden') === 'true'
  ));
  await page.keyboard.press('Shift+Tab');
  const shiftWrapped = await page.getByRole('button', { name: 'Complete Profile' })
    .evaluate((node) => document.activeElement === node);
  await page.keyboard.press('Tab');
  const tabWrapped = await page.getByRole('button', { name: 'Close profile prompt' })
    .evaluate((node) => document.activeElement === node);

  await page.route('**/api/v1/student/profile/prompt-dismiss', (route) => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'profile_write_unavailable' } }),
  }));
  failureStage = 'prompt_routing_failed_dismiss';
  await page.getByRole('button', { name: 'Maybe Later' }).click();
  await page.getByTestId('profile-save-error').waitFor();
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === 'Maybe Later',
    );
    return button instanceof HTMLButtonElement && !button.disabled;
  });
  const dismissErrorRetained = await dialog.isVisible()
    && new URL(page.url()).pathname === '/s-07';
  await page.unroute('**/api/v1/student/profile/prompt-dismiss');

  const dismissal = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/student/profile/prompt-dismiss'
  ));
  failureStage = 'prompt_routing_successful_dismiss_response';
  await page.getByRole('button', { name: 'Close profile prompt' }).focus();
  await page.keyboard.press('Escape');
  const dismissedResponse = await dismissal;
  failureStage = 'prompt_routing_successful_dismiss_navigation';
  await page.waitForURL(/\/s-14$/u);
  const dashboardHeading = page.locator('[data-screen="S-14"] h1').first();
  await dashboardHeading.waitFor();
  await page.waitForFunction(() => (
    document.activeElement === document.querySelector('[data-screen="S-14"] h1')
  ));
  await recordVisualContract(page, 'S-14');
  const dashboardCardLocator = page.getByTestId('profile-completion-card');
  await dashboardCardLocator.waitFor({ state: 'visible' });
  const dashboardCard = await dashboardCardLocator.count() === 1;
  const focusRestored = await dashboardHeading.evaluate((node) => document.activeElement === node);
  failureStage = 'prompt_routing_profile_card';
  await page.goto(`${WEB}/s-17`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('heading', { name: 'Your profile', exact: true }).waitFor({ state: 'visible' });
  await recordVisualContract(page, 'S-17');
  const profileCardLocator = page.getByTestId('profile-completion-card');
  await profileCardLocator.waitFor({ state: 'visible' });
  const profileCard = await profileCardLocator.count() === 1;
  recordBrowserExecution(
    'completion_cards_until_100', dashboardCard && profileCard, 2,
    Number(dashboardCard) + Number(profileCard),
  );
  failureStage = 'prompt_routing_same_session';
  await page.goto(`${WEB}/s-07`, { waitUntil: 'domcontentloaded' });
  await page.waitForURL(/\/s-14$/u);
  const sameSessionHidden = await page.getByTestId('profile-completion-dialog').count() === 0;
  const completionObservation = observations.get('completion_server_derived');
  observe('completion_server_derived', completionObservation.pass
    && dashboardCard && profileCard, {
    ...completionObservation.metrics,
    completionCards: 2,
    completionCardsVisible: Number(dashboardCard) + Number(profileCard),
  });
  await recordStorage(page, 'prompt');

  failureStage = 'prompt_routing_rotate_session';
  const rotatedPage = await context.newPage();
  trackActorBoundary(rotatedPage);
  await context.clearCookies({ name: 'nyayone_session' });
  const rotated = await loginStudentThroughUi(rotatedPage, mobile);
  const rotatedAuthenticated = rotated.startResponse.status() === 202
    && rotated.verifyResponse.status() === 200;
  failureStage = 'prompt_routing_rotated_dialog';
  await rotatedPage.waitForURL(/\/s-07$/u);
  const rotatedDialog = rotatedPage.getByTestId('profile-completion-dialog');
  await rotatedDialog.waitFor({ state: 'visible' });
  const rotatedShown = await rotatedDialog.isVisible();
  const rotatedSelectorCount = await rotatedDialog.count();

  const dialogObservation = inspectDialogObservation({
    initialFocus,
    shiftWrapped,
    tabWrapped,
    focusRestored,
    backgroundInert: inert,
    dismissErrorRetained,
  });
  observe('dialog_focus_and_inert_contract', dialogObservation.pass, {
    focusChecks: 4,
    focusPassed: [initialFocus, shiftWrapped, tabWrapped, focusRestored].filter(Boolean).length,
    inert,
    dismissErrorRetained,
    selectorCount: promptHostSelectors + rotatedSelectorCount,
  });
  const promptRotationObservation = inspectPromptRotationObservation({
    dismissStatus: dismissedResponse.status(),
    sameSessionHidden,
    rotatedSessionShown: rotatedShown,
  });
  observe('prompt_session_scoped', promptRotationObservation.pass, {
    sameSessionHidden,
    rotatedSessionShown: rotatedShown,
    selectorCount: promptHostSelectors + rotatedSelectorCount,
  });
  observe('prompt_lifecycle_teardown', rotatedAuthenticated && rotatedShown, {
    startStatus: rotated.startResponse.status(),
    verifyStatus: rotated.verifyResponse.status(),
    rotatedAuthenticated,
    promptRestored: rotatedShown,
    selectorCount: rotatedSelectorCount,
  });
  await recordStorage(rotatedPage, 'rotated-session');
  await context.close();
}

async function crossSectionConflictProbe(browser) {
  const completePrerequisiteChanges = [];
  const prerequisiteRegressions = [];
  let selectorCount = 0;

  failureStage = 'cross_conflict_complete_provision';
  const completeActor = await provisionStudent(browser, { firstName: 'Cross' });
  const completeInitial = await profileProjection(completeActor.context);
  const completePersonal = await patchPersonalProjection(
    completeActor.context,
    completeInitial.body,
    { preferred_language: 'en', city: 'Pune' },
  );
  if (completePersonal.status() !== 200) {
    await completeActor.context.close();
    throw new Error('NYAY5_CROSS_SECTION_SETUP_FAILED');
  }
  const completePersonalBody = await completePersonal.json();
  const academicPage = await completeActor.context.newPage();
  trackActorBoundary(academicPage);
  failureStage = 'cross_conflict_complete_academic_mount';
  await academicPage.goto(`${WEB}/s-10?section=academic`, { waitUntil: 'domcontentloaded' });
  await fillAcademicDraft(academicPage, 'QA/101/2026');
  const academicPatches = countSectionPatches(
    academicPage,
    '/api/v1/student/profile/academic',
  );
  const academicConcurrent = await patchPersonalProjection(
    completeActor.context,
    completePersonalBody,
    { city: 'Jaipur' },
  );
  const academicConflictPromise = academicPage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/academic'
  ));
  failureStage = 'cross_conflict_complete_academic_conflict';
  await academicPage.getByRole('button', { name: 'Save & continue' }).click();
  const academicConflictStatus = (await academicConflictPromise).status();
  const academicReview = academicPage.getByTestId('profile-conflict-review');
  await academicReview.waitFor();
  const academicReviewVisible = await academicReview.isVisible();
  const academicRouteAndDraftRetained = new URL(academicPage.url()).searchParams
    .get('section') === 'academic'
    && await academicPage.locator('#profile-academic-enrolment').inputValue()
      === 'QA/101/2026';
  const academicPatchCountBeforeAdopt = academicPatches.count;
  await academicReview.getByRole('button', {
    name: 'Use current version and review my draft',
  }).click();
  await academicReview.waitFor({ state: 'detached' });
  const academicPatchCountAfterAdopt = academicPatches.count;
  const academicRetryPromise = academicPage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/academic'
  ));
  failureStage = 'cross_conflict_complete_academic_retry';
  await academicPage.getByRole('button', { name: 'Save & continue' }).click();
  const academicRetryStatus = (await academicRetryPromise).status();
  await academicPage.waitForURL(/\/s-11$/u);
  const afterAcademic = await profileProjection(completeActor.context);
  const academicDraftPersisted = afterAcademic.body?.profile_version === 4
    && afterAcademic.body?.profile?.academic?.enrolment_number === 'QA/101/2026';
  completePrerequisiteChanges.push({
    section: 'academic',
    firstStatus: academicConflictStatus,
    reviewVisible: academicReviewVisible,
    routeAndDraftRetained: academicRouteAndDraftRetained,
    patchCountBeforeAdopt: academicPatchCountBeforeAdopt,
    patchCountAfterAdopt: academicPatchCountAfterAdopt,
    deliberateRetryStatus: academicRetryStatus,
    deliberateDraftPersisted: academicDraftPersisted,
  });
  selectorCount += Number(academicReviewVisible) + 3;

  await fillInterestsDraft(academicPage);
  const interestsPatches = countSectionPatches(
    academicPage,
    '/api/v1/student/profile/interests',
  );
  const interestsConcurrent = await patchPersonalProjection(
    completeActor.context,
    afterAcademic.body,
    { city: 'Delhi' },
  );
  const interestsConflictPromise = academicPage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/interests'
  ));
  failureStage = 'cross_conflict_complete_interests_conflict';
  await academicPage.getByRole('button', { name: 'Finish setup' }).click();
  const interestsConflictStatus = (await interestsConflictPromise).status();
  const interestsReview = academicPage.getByTestId('profile-conflict-review');
  await interestsReview.waitFor();
  const interestsReviewVisible = await interestsReview.isVisible();
  const interestsRouteAndDraftRetained = new URL(academicPage.url()).pathname === '/s-11'
    && await academicPage.locator('#profile-interests-first-option')
      .getAttribute('aria-pressed') === 'true'
    && await academicPage.locator('#profile-interests-goal').inputValue() !== '';
  const interestsPatchCountBeforeAdopt = interestsPatches.count;
  await interestsReview.getByRole('button', {
    name: 'Use current version and review my draft',
  }).click();
  await interestsReview.waitFor({ state: 'detached' });
  const interestsPatchCountAfterAdopt = interestsPatches.count;
  const interestsRetryPromise = academicPage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/interests'
  ));
  failureStage = 'cross_conflict_complete_interests_retry';
  await academicPage.getByRole('button', { name: 'Finish setup' }).click();
  const interestsRetryStatus = (await interestsRetryPromise).status();
  await academicPage.waitForURL(/\/s-12$/u);
  const afterInterests = await profileProjection(completeActor.context);
  const interestsDraftPersisted = afterInterests.body?.profile_version === 6
    && afterInterests.body?.profile?.interests?.interests?.length === 1
    && afterInterests.body?.profile?.interests?.goals?.length === 1;
  completePrerequisiteChanges.push({
    section: 'interests',
    firstStatus: interestsConflictStatus,
    reviewVisible: interestsReviewVisible,
    routeAndDraftRetained: interestsRouteAndDraftRetained,
    patchCountBeforeAdopt: interestsPatchCountBeforeAdopt,
    patchCountAfterAdopt: interestsPatchCountAfterAdopt,
    deliberateRetryStatus: interestsRetryStatus,
    deliberateDraftPersisted: interestsDraftPersisted,
  });
  selectorCount += Number(interestsReviewVisible) + 2;
  const completeSetupExact = academicConcurrent.status() === 200
    && interestsConcurrent.status() === 200;
  await completeActor.context.close();

  failureStage = 'cross_conflict_regression_provision';
  const regressionActor = await provisionStudent(browser, { firstName: 'Restore' });
  const regressionInitial = await profileProjection(regressionActor.context);
  const regressionPersonal = await patchPersonalProjection(
    regressionActor.context,
    regressionInitial.body,
    { preferred_language: 'en', city: 'Pune' },
  );
  if (regressionPersonal.status() !== 200) {
    await regressionActor.context.close();
    throw new Error('NYAY5_PREREQUISITE_REGRESSION_SETUP_FAILED');
  }
  const regressionPersonalBody = await regressionPersonal.json();
  const regressionPage = await regressionActor.context.newPage();
  trackActorBoundary(regressionPage);
  failureStage = 'cross_conflict_regression_academic_mount';
  await regressionPage.goto(`${WEB}/s-10?section=academic`, {
    waitUntil: 'domcontentloaded',
  });
  await fillAcademicDraft(regressionPage, 'QA/201/2026');
  const regressionAcademicPatches = countSectionPatches(
    regressionPage,
    '/api/v1/student/profile/academic',
  );
  const academicRegression = await patchPersonalProjection(
    regressionActor.context,
    regressionPersonalBody,
    { preferred_language: null, city: null },
  );
  const academicRegressionConflict = regressionPage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/academic'
  ));
  failureStage = 'cross_conflict_regression_academic_conflict';
  await regressionPage.getByRole('button', { name: 'Save & continue' }).click();
  const academicRegressionStatus = (await academicRegressionConflict).status();
  const academicRegressionReview = regressionPage.getByTestId('profile-conflict-review');
  await academicRegressionReview.waitFor();
  const academicRegressionReviewVisible = await academicRegressionReview.isVisible();
  const academicRegressionRetained = new URL(regressionPage.url()).searchParams
    .get('section') === 'academic'
    && await regressionPage.locator('#profile-academic-enrolment').inputValue()
      === 'QA/201/2026';
  const academicRegressionPatchesBeforeAdopt = regressionAcademicPatches.count;
  const storageBeforeAcademicAdopt = inspectBrowserPersistence(
    await storageSnapshot(regressionPage),
  ).pass;
  await academicRegressionReview.getByRole('button', {
    name: 'Use current version and review my draft',
  }).click();
  failureStage = 'cross_conflict_regression_academic_repair';
  await regressionPage.waitForURL(/\/s-10\?section=personal$/u);
  const academicAdoptRoutedToPrerequisite = new URL(regressionPage.url()).searchParams
    .get('section') === 'personal';
  await fillPersonal(regressionPage, { city: 'Pune', firstName: 'Restore' });
  await regressionPage.getByRole('button', { name: 'Save & continue' }).click();
  await regressionPage.waitForURL(/\/s-10\?section=academic$/u);
  const academicRestoredNotice = regressionPage.getByTestId(
    'profile-conflict-draft-restored',
  );
  await academicRestoredNotice.waitFor();
  const academicDraftRestored = await academicRestoredNotice.isVisible()
    && await regressionPage.locator('#profile-academic-enrolment').inputValue()
      === 'QA/201/2026';
  const academicFinalRetry = regressionPage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/academic'
  ));
  failureStage = 'cross_conflict_regression_academic_retry';
  await regressionPage.getByRole('button', { name: 'Save & continue' }).click();
  const academicFinalStatus = (await academicFinalRetry).status();
  await regressionPage.waitForURL(/\/s-11$/u);
  const afterAcademicRegression = await profileProjection(regressionActor.context);
  const academicRegressionPersisted = afterAcademicRegression.body?.profile_version === 5
    && afterAcademicRegression.body?.profile?.academic?.enrolment_number === 'QA/201/2026';
  const storageAfterAcademicRepair = inspectBrowserPersistence(
    await storageSnapshot(regressionPage),
  ).pass;
  prerequisiteRegressions.push({
    section: 'academic',
    firstStatus: academicRegressionStatus,
    reviewVisible: academicRegressionReviewVisible,
    routeAndDraftRetained: academicRegressionRetained,
    patchCountBeforeAdopt: academicRegressionPatchesBeforeAdopt,
    adoptRoutedToPrerequisite: academicAdoptRoutedToPrerequisite,
    browserPersistenceClean: storageBeforeAcademicAdopt && storageAfterAcademicRepair,
    draftRestoredAfterRepair: academicDraftRestored,
    finalRetryStatus: academicFinalStatus,
    deliberateDraftPersisted: academicRegressionPersisted,
  });
  selectorCount += Number(academicRegressionReviewVisible)
    + Number(academicDraftRestored) + 4;

  await fillInterestsDraft(regressionPage);
  const regressionInterestsPatches = countSectionPatches(
    regressionPage,
    '/api/v1/student/profile/interests',
  );
  const interestsRegression = await patchPersonalProjection(
    regressionActor.context,
    afterAcademicRegression.body,
    { preferred_language: null, city: null },
  );
  const interestsRegressionConflict = regressionPage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/interests'
  ));
  failureStage = 'cross_conflict_regression_interests_conflict';
  await regressionPage.getByRole('button', { name: 'Finish setup' }).click();
  const interestsRegressionStatus = (await interestsRegressionConflict).status();
  const interestsRegressionReview = regressionPage.getByTestId('profile-conflict-review');
  await interestsRegressionReview.waitFor();
  const interestsRegressionReviewVisible = await interestsRegressionReview.isVisible();
  const interestsRegressionRetained = new URL(regressionPage.url()).pathname === '/s-11'
    && await regressionPage.locator('#profile-interests-first-option')
      .getAttribute('aria-pressed') === 'true'
    && await regressionPage.locator('#profile-interests-goal').inputValue() !== '';
  const interestsRegressionPatchesBeforeAdopt = regressionInterestsPatches.count;
  const storageBeforeInterestsAdopt = inspectBrowserPersistence(
    await storageSnapshot(regressionPage),
  ).pass;
  await interestsRegressionReview.getByRole('button', {
    name: 'Use current version and review my draft',
  }).click();
  failureStage = 'cross_conflict_regression_interests_repair';
  await regressionPage.waitForURL(/\/s-10\?section=personal$/u);
  const interestsAdoptRoutedToPrerequisite = new URL(regressionPage.url()).searchParams
    .get('section') === 'personal';
  await fillPersonal(regressionPage, { city: 'Pune', firstName: 'Restore' });
  await regressionPage.getByRole('button', { name: 'Save & continue' }).click();
  await regressionPage.waitForURL(/\/s-11$/u);
  const interestsRestoredNotice = regressionPage.getByTestId(
    'profile-conflict-draft-restored',
  );
  await interestsRestoredNotice.waitFor();
  const interestsDraftRestored = await interestsRestoredNotice.isVisible()
    && await regressionPage.locator('#profile-interests-first-option')
      .getAttribute('aria-pressed') === 'true'
    && await regressionPage.locator('#profile-interests-goal').inputValue() !== '';
  const interestsFinalRetry = regressionPage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/interests'
  ));
  failureStage = 'cross_conflict_regression_interests_retry';
  await regressionPage.getByRole('button', { name: 'Finish setup' }).click();
  const interestsFinalStatus = (await interestsFinalRetry).status();
  await regressionPage.waitForURL(/\/s-12$/u);
  const afterInterestsRegression = await profileProjection(regressionActor.context);
  const interestsRegressionPersisted = afterInterestsRegression.body?.profile_version === 8
    && afterInterestsRegression.body?.profile?.interests?.interests?.length === 1
    && afterInterestsRegression.body?.profile?.interests?.goals?.length === 1;
  const storageAfterInterestsRepair = inspectBrowserPersistence(
    await storageSnapshot(regressionPage),
  ).pass;
  prerequisiteRegressions.push({
    section: 'interests',
    firstStatus: interestsRegressionStatus,
    reviewVisible: interestsRegressionReviewVisible,
    routeAndDraftRetained: interestsRegressionRetained,
    patchCountBeforeAdopt: interestsRegressionPatchesBeforeAdopt,
    adoptRoutedToPrerequisite: interestsAdoptRoutedToPrerequisite,
    browserPersistenceClean: storageBeforeInterestsAdopt && storageAfterInterestsRepair,
    draftRestoredAfterRepair: interestsDraftRestored,
    finalRetryStatus: interestsFinalStatus,
    deliberateDraftPersisted: interestsRegressionPersisted,
  });
  selectorCount += Number(interestsRegressionReviewVisible)
    + Number(interestsDraftRestored) + 3;
  const regressionSetupExact = academicRegression.status() === 200
    && interestsRegression.status() === 200;
  await regressionActor.context.close();

  const observation = inspectCrossSectionConflictObservation({
    completePrerequisiteChanges,
    prerequisiteRegressions,
  });
  return {
    pass: observation.pass && completeSetupExact && regressionSetupExact,
    completePrerequisiteChanges,
    prerequisiteRegressions,
    selectorCount,
  };
}

async function staleCrossUserAndUncertainProbe(browser) {
  const first = await provisionStudent(browser, { firstName: 'First' });
  const second = await provisionStudent(browser, { firstName: 'Second' });
  const firstProjection = await profileProjection(first.context);
  const forgedQuery = await first.context.request.get(
    `${API}/api/v1/student/profile?registration_id=${second.sessionActor.student_profile_id}`,
  );
  const forgedHeader = await first.context.request.get(`${API}/api/v1/student/profile`, {
    headers: {
      'X-Actor-Claims': JSON.stringify({ sub: second.sessionActor.sub, roles: ['student'] }),
    },
  });
  const forgedBody = forgedHeader.ok() ? await forgedHeader.json() : null;
  const firstPage = await first.context.newPage();
  const stalePage = await first.context.newPage();
  trackActorBoundary(firstPage);
  trackActorBoundary(stalePage);
  for (const page of [firstPage, stalePage]) {
    await page.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
    await page.locator('#profile-personal-city').waitFor();
  }
  await fillPersonal(firstPage, { city: 'Pune', firstName: 'First' });
  await fillPersonal(stalePage, { city: 'Chennai', firstName: 'First' });
  await firstPage.getByRole('button', { name: 'Save & continue' }).click();
  await firstPage.waitForURL(/section=academic/u);
  let stalePatchCount = 0;
  stalePage.on('request', (request) => {
    if (request.method() === 'PATCH'
      && new URL(request.url()).pathname === '/api/v1/student/profile/personal') {
      stalePatchCount += 1;
    }
  });
  const firstConflict = stalePage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/personal'
  ));
  await stalePage.getByRole('button', { name: 'Save & continue' }).click();
  const firstConflictStatus = (await firstConflict).status();
  await stalePage.getByTestId('profile-save-error').waitFor();
  const conflictReview = stalePage.getByTestId('profile-conflict-review');
  await conflictReview.waitFor();
  const adoptButton = conflictReview.getByRole('button', {
    name: 'Use current version and review my draft',
  });
  const saveButtons = stalePage.getByRole('button', { name: /Save (?:and exit|& continue)/u });
  const patchCountBeforeReview = stalePatchCount;
  const staleRetainedBeforeReview = new URL(stalePage.url()).searchParams.get('section') === 'personal'
    && await stalePage.locator('#profile-personal-city').inputValue() === 'Chennai';
  const conflictReviewVisible = await conflictReview.isVisible();
  const serverWinnerVisible = await conflictReview.getByText('Current server version 2:', {
    exact: false,
  }).isVisible();
  const retainedDraftVisible = await conflictReview.getByText('Your retained draft:', {
    exact: false,
  }).isVisible()
    && (await conflictReview.textContent())?.includes('Chennai') === true;
  const saveButtonsDisabled = await saveButtons.count() === 2
    && await saveButtons.evaluateAll((buttons) => buttons.every((button) => button.disabled));
  await stalePage.waitForTimeout(100);
  const noAutomaticRetry = stalePatchCount === patchCountBeforeReview;

  await adoptButton.click();
  await conflictReview.waitFor({ state: 'detached' });
  const patchCountAfterAdopt = stalePatchCount;
  const draftRetainedAfterAdopt = new URL(stalePage.url()).searchParams.get('section') === 'personal'
    && await stalePage.locator('#profile-personal-city').inputValue() === 'Chennai';
  const deliberateRetry = stalePage.waitForResponse((response) => (
    response.request().method() === 'PATCH'
    && new URL(response.url()).pathname === '/api/v1/student/profile/personal'
  ));
  await stalePage.getByRole('button', { name: 'Save & continue' }).click();
  const deliberateRetryStatus = (await deliberateRetry).status();
  await stalePage.waitForURL(/section=academic/u);
  const latest = await profileProjection(first.context);
  const deliberateDraftPersisted = latest.body?.profile_version === 3
    && latest.body?.profile?.personal?.city === 'Chennai';
  const latestPersonal = latest.body?.profile?.personal;
  const wrongStale = await first.context.request.patch(
    `${API}/api/v1/student/profile/personal`,
    {
      headers: {
        Origin: WEB_ORIGIN,
        'Idempotency-Key': profileFixtureIdempotencyKey(),
      },
      data: {
        expected_profile_version: 1,
        first_name: latestPersonal?.first_name,
        middle_name: latestPersonal?.middle_name,
        last_name: latestPersonal?.last_name,
        date_of_birth: latestPersonal?.date_of_birth,
        preferred_language: latestPersonal?.preferred_language,
        city: 'Mumbai',
        pronouns: latestPersonal?.pronouns,
      },
    },
  );
  const wrongStaleStatus = wrongStale.status();
  const afterWrongStale = await profileProjection(first.context);
  const newerVersionPreserved = afterWrongStale.body?.profile_version === 3
    && afterWrongStale.body?.profile?.personal?.city === 'Chennai';
  const secondConflictStatus = wrongStaleStatus;
  const crossUserObservation = inspectCrossUserObservation({
    selectorStatus: forgedQuery.status(),
    canonicalStatus: forgedHeader.status(),
    canonicalOwnerStayedSame: forgedBody?.profile?.personal?.first_name
      === firstProjection.body?.profile?.personal?.first_name,
    otherOwnerReturned: forgedBody?.profile?.personal?.first_name === 'Second',
  });
  observe('cross_user_denied', crossUserObservation.pass, {
    selectorStatus: forgedQuery.status(),
    canonicalStatus: forgedHeader.status(),
    ownerStayedExact: true,
    cases: 3,
  });
  const staleConflictObservation = inspectStaleConflictObservation({
    firstStatus: firstConflictStatus,
    secondStatus: secondConflictStatus,
    routeAndValuesRetained: staleRetainedBeforeReview && draftRetainedAfterAdopt,
    patchCountBeforeReview,
    conflictReviewVisible,
    serverWinnerVisible,
    retainedDraftVisible,
    patchCountAfterAdopt,
    deliberateRetryStatus,
    wrongStaleStatus,
    deliberateDraftPersisted,
    newerVersionPreserved,
  });
  const personalConflictPass = staleConflictObservation.pass
    && saveButtonsDisabled && noAutomaticRetry;
  const personalSelectorCount = Number(conflictReviewVisible)
    + Number(serverWinnerVisible)
    + Number(retainedDraftVisible)
    + Number(saveButtonsDisabled)
    + Number(draftRetainedAfterAdopt);
  await recordStorage(stalePage, 'stale-tab');
  await first.context.close();
  await second.context.close();

  const crossSectionConflict = await crossSectionConflictProbe(browser);
  observe('stale_multi_tab_conflict', personalConflictPass
    && crossSectionConflict.pass, {
    tabs: 6,
    cases: 5,
    conflicts: Number(firstConflictStatus === 409) + Number(secondConflictStatus === 409)
      + crossSectionConflict.completePrerequisiteChanges
        .filter((row) => row.firstStatus === 409).length
      + crossSectionConflict.prerequisiteRegressions
        .filter((row) => row.firstStatus === 409).length,
    deliberateRetries: Number(deliberateRetryStatus === 200)
      + crossSectionConflict.completePrerequisiteChanges
        .filter((row) => row.deliberateRetryStatus === 200).length
      + crossSectionConflict.prerequisiteRegressions
        .filter((row) => row.finalRetryStatus === 200).length,
    patchCountBeforeReview,
    patchCountAfterAdopt,
    staleRetained: staleRetainedBeforeReview && draftRetainedAfterAdopt,
    currentVersionAdvanced: latest.body?.profile_version === 3,
    selectorCount: personalSelectorCount + crossSectionConflict.selectorCount,
  });

  const uncertain = await provisionStudent(browser, { firstName: 'Uncertain' });
  const uncertainPage = await uncertain.context.newPage();
  trackActorBoundary(uncertainPage);
  const sequence = [];
  uncertainPage.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/v1/student/profile')) sequence.push(`${request.method()} ${path}`);
  });
  await uncertainPage.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
  await uncertainPage.locator('#profile-personal-city').waitFor();
  await fillPersonal(uncertainPage, { city: 'Kochi', firstName: 'Uncertain' });
  let realWriteStatus = 0;
  await uncertainPage.route('**/api/v1/student/profile/personal', async (route) => {
    const response = await route.fetch();
    realWriteStatus = response.status();
    await route.abort('failed');
  });
  await uncertainPage.getByRole('button', { name: 'Save & continue' }).click();
  await uncertainPage.waitForURL(/section=academic/u);
  const reconciled = await profileProjection(uncertain.context);
  const patchIndex = sequence.findIndex((entry) => entry.includes('PATCH'));
  const refetchIndex = sequence.findIndex((entry, index) => index > patchIndex && entry.includes('GET'));
  const writeCount = sequence.filter((entry) => entry.includes('PATCH')).length;
  const uncertainObservation = inspectUncertainWriteObservation({
    writeStatus: realWriteStatus,
    writeCount,
    refetchedBeforeRetry: patchIndex >= 0 && refetchIndex > patchIndex,
    retryCount: Math.max(0, writeCount - 1),
    reconciled: reconciled.body?.profile?.personal?.city === 'Kochi',
  });
  observe('uncertain_write_reconciles', uncertainObservation.pass, {
    writeCount,
    refetchedBeforeRetry: refetchIndex > patchIndex,
    reconciled: reconciled.body?.profile_version === 2,
    selectorCount: await uncertainPage.locator('#profile-academic-college').count(),
  });
  await recordStorage(uncertainPage, 'uncertain-write');
  await uncertain.context.close();
}

async function minorAndResponsiveProbe(browser) {
  const { context, mobile } = await provisionStudent(
    browser, { dob: '2010-01-01', firstName: 'Minor' },
  );
  const page = await context.newPage();
  trackActorBoundary(page);
  await page.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
  await page.locator('#profile-personal-city').waitFor();
  await fillPersonal(page, { city: 'Delhi', firstName: 'Minor' });
  await page.getByRole('button', { name: 'Save & continue' }).click();
  await page.waitForURL(/\/s-16$/u);
  await recordVisualContract(page, 'S-16');
  const exactCapabilities = await page.getByText('Disabled capabilities: community, sharing.').isVisible();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForURL(/\/s-16$/u);
  const reloadLimitedMessage = page.getByText(
    'Disabled capabilities: community, sharing.',
  );
  await reloadLimitedMessage.waitFor({ state: 'visible' });
  const reloadLimited = await reloadLimitedMessage.isVisible();
  await page.goto(`${WEB}/s-50`, { waitUntil: 'domcontentloaded' });
  await page.waitForURL(/\/s-16$/u);
  const capabilityDenied = new URL(page.url()).pathname === '/s-16';
  const reloginPage = await context.newPage();
  trackActorBoundary(reloginPage);
  await context.clearCookies({ name: 'nyayone_session' });
  const relogin = await loginStudentThroughUi(reloginPage, mobile);
  const reloginAuthenticated = relogin.startResponse.status() === 202
    && relogin.verifyResponse.status() === 200;
  await reloginPage.goto(`${WEB}/s-50`, { waitUntil: 'domcontentloaded' });
  await reloginPage.waitForURL(/\/s-16$/u);
  const reloginLimitedMessage = reloginPage.getByText(
    'Disabled capabilities: community, sharing.',
  );
  await reloginLimitedMessage.waitFor({ state: 'visible' });
  const reloginLimited = await reloginLimitedMessage.isVisible();
  recordBrowserExecution(
    'limited_reload_login_direct',
    exactCapabilities && reloadLimited && capabilityDenied
      && reloginAuthenticated && reloginLimited,
    3,
    3,
  );
  const viewports = [
    { name: 'mobile-narrow', width: 360, height: 800 },
    { name: 'mobile-keyboard', width: 390, height: 430 },
    { name: 'mobile-standard', width: 390, height: 844 },
    { name: 'desktop', width: 1440, height: 1024 },
  ];
  const geometries = [];
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    if (viewport.name === 'mobile-keyboard') {
      await page.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
      const activeField = page.locator('#profile-personal-city');
      await activeField.waitFor();
      await activeField.focus();
      await activeField.scrollIntoViewIfNeeded();
      await page.getByRole('button', { name: 'Save & continue' }).scrollIntoViewIfNeeded();
      await activeField.focus();
    } else {
      await page.goto(`${WEB}/s-16`, { waitUntil: 'domcontentloaded' });
      await page.locator('[data-screen="S-16"]').waitFor();
      await page.getByRole('heading', {
        name: 'Some features are still locked',
      }).waitFor({ state: 'visible' });
    }
    geometries.push(await page.evaluate((viewportName) => {
      const targets = [...document.querySelectorAll('button,a,input,select')]
        .filter((item) => item.getClientRects().length > 0)
        .map((item) => Math.min(
          item.getBoundingClientRect().width,
          item.getBoundingClientRect().height,
        ));
      const headings = [...document.querySelectorAll('h1,h2')]
        .filter((item) => item.getClientRects().length > 0);
      const headingStyles = headings.map((item) => ({
        className: item.className,
        family: getComputedStyle(item).fontFamily.toLowerCase(),
        tagName: item.tagName.toLowerCase(),
      }));
      const typographyExact = headings.length > 0 && headings.every((item) => {
        const family = getComputedStyle(item).fontFamily.toLowerCase();
        return family.includes('aptos')
          && family.includes('calibri')
          && family.includes('carlito')
          && family.includes('system-ui');
      });
      const active = document.activeElement;
      const activeRect = active instanceof HTMLElement ? active.getBoundingClientRect() : null;
      const primary = [...document.querySelectorAll('button')].find((button) => (
        button.textContent?.trim() === 'Save & continue'
      ));
      const primaryRect = primary?.getBoundingClientRect() ?? null;
      const keyboardGeometryExact = viewportName !== 'mobile-keyboard' || Boolean(
        active?.id === 'profile-personal-city'
        && activeRect
        && activeRect.top >= 0
        && activeRect.bottom <= window.innerHeight
        && primaryRect
        && primaryRect.width >= 44
        && primaryRect.height >= 44,
      );
      return {
        viewportName,
        overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
        minimumTarget: targets.length > 0 ? Math.min(...targets) : 0,
        selectorCount: targets.length,
        headingStyles,
        typographyExact,
        keyboardGeometryExact,
      };
    }, viewport.name));
  }
  const previousDenialObservation = observations.get('denial_matrix_fail_closed');
  observe('denial_matrix_fail_closed', previousDenialObservation.pass
    && exactCapabilities && capabilityDenied, {
    ...previousDenialObservation.metrics,
    limitedChecks: 4,
    limitedPassed: [exactCapabilities, reloadLimited, capabilityDenied, reloginLimited]
      .filter(Boolean).length,
    selectorCount: Number(exactCapabilities) + Number(reloadLimited)
      + Number(capabilityDenied) + Number(reloginLimited),
  });
  const geometryObservations = geometries.map(inspectGeometryObservation);
  observe('responsive_targets_and_no_overflow', geometryObservations.every((entry) => (
    entry.pass
  )) && geometries.every((entry) => (
    entry.selectorCount > 0 && entry.typographyExact && entry.keyboardGeometryExact
  )), {
    cases: geometries.length,
    passed: geometries.filter((entry) => (
      !entry.overflow
      && entry.minimumTarget >= 44
      && entry.selectorCount > 0
      && entry.typographyExact
      && entry.keyboardGeometryExact
    )).length,
    selectorCount: geometries.reduce((total, entry) => total + entry.selectorCount, 0),
    geometries,
  });
  await recordStorage(page, 'limited-access');
  await context.close();
}

async function unicodeAndRegistrationProbe(browser) {
  const corpus = JSON.parse(await readFile(
    resolve(import.meta.dirname, '../../contracts/unicode-legal-name-v1.json'),
    'utf8',
  ));
  failureStage = 'unicode_corpus_provision';
  const { context } = await provisionStudent(browser, { firstName: 'Corpus' });
  const page = await context.newPage();
  trackActorBoundary(page);
  const corpusRows = [];
  for (const testCase of corpus.cases) {
    failureStage = `unicode_case_${testCase.id}_mount`;
    const repeat = Number(testCase.repeat ?? 1);
    const candidate = String(testCase.input).repeat(repeat);
    const expected = String(testCase.normalized ?? testCase.input).repeat(repeat)
      .normalize('NFC').replace(/ +/gu, ' ').replace(/^ | $/gu, '');

    await page.goto(`${WEB}/s-10?section=personal`, { waitUntil: 'domcontentloaded' });
    const firstNameInput = page.locator('#profile-personal-first-name');
    await firstNameInput.waitFor();
    await fillPersonal(page, { firstName: 'Corpus', city: 'Pune' });
    await firstNameInput.fill(candidate);
    const presentedCandidate = await firstNameInput.inputValue();
    const platformRejected = testCase.valid === false
      && /[\r\n]/u.test(candidate)
      && presentedCandidate !== candidate;
    let uiPatchCount = 0;
    const onPersonalPatch = (request) => {
      if (request.method() === 'PATCH'
        && new URL(request.url()).pathname === '/api/v1/student/profile/personal') {
        uiPatchCount += 1;
      }
    };
    page.on('request', onPersonalPatch);
    let uiStatus = null;
    let uiBody = null;
    let uiRouteAdvanced = false;
    let uiRouteRetained = false;
    let uiValueRetained = false;
    let uiErrorRole = null;
    let uiErrorVisible = false;
    if (testCase.valid) {
      const uiResponsePromise = page.waitForResponse((response) => (
        response.request().method() === 'PATCH'
        && new URL(response.url()).pathname === '/api/v1/student/profile/personal'
      ));
      failureStage = `unicode_case_${testCase.id}_valid_submit`;
      await page.getByRole('button', { name: 'Save & continue' }).click();
      const uiResponse = await uiResponsePromise;
      uiStatus = uiResponse.status();
      uiBody = uiResponse.ok() ? await uiResponse.json() : null;
      await page.waitForURL(/\/s-10\?section=academic$/u);
      const route = new URL(page.url());
      uiRouteAdvanced = route.pathname === '/s-10'
        && route.search === '?section=academic' && route.hash === '';
    } else {
      failureStage = `unicode_case_${testCase.id}_invalid_submit`;
      if (platformRejected) {
        const route = new URL(page.url());
        uiRouteRetained = route.pathname === '/s-10'
          && route.search === '?section=personal' && route.hash === '';
      } else {
        await page.getByRole('button', { name: 'Save & continue' }).click();
        const errorSummary = page.getByTestId('profile-error-summary');
        await errorSummary.waitFor({ state: 'visible' });
        const route = new URL(page.url());
        uiRouteRetained = route.pathname === '/s-10'
          && route.search === '?section=personal' && route.hash === '';
        uiValueRetained = await firstNameInput.inputValue() === candidate;
        uiErrorRole = await errorSummary.getAttribute('role');
        uiErrorVisible = await errorSummary.isVisible();
      }
    }
    page.off('request', onPersonalPatch);

    failureStage = `unicode_case_${testCase.id}_backend`;
    const backendBefore = await profileProjection(context);
    const backendResponse = await context.request.patch(
      `${API}/api/v1/student/profile/personal`,
      {
        headers: {
          Origin: WEB_ORIGIN,
          'Idempotency-Key': profileFixtureIdempotencyKey(),
        },
        data: personalMutation(
          backendBefore.body,
          backendBefore.body?.profile_version,
          { first_name: candidate },
        ),
      },
    );
    const backendStatus = backendResponse.status();
    const backendBody = backendResponse.ok() ? await backendResponse.json() : null;
    const backendAfter = await profileProjection(context);
    const backendZeroMutation = backendStatus === 422
      && backendAfter.body?.profile_version === backendBefore.body?.profile_version
      && JSON.stringify(backendAfter.body?.profile?.personal)
        === JSON.stringify(backendBefore.body?.profile?.personal);
    corpusRows.push({
      id: testCase.id,
      valid: testCase.valid,
      ui: testCase.valid ? {
        patchCount: uiPatchCount,
        status: uiStatus,
        normalizedExact: uiBody?.profile?.personal?.first_name === expected,
        projectionExact: inspectNyay5Projection(uiBody).pass,
        routeAdvanced: uiRouteAdvanced,
      } : {
        patchCount: uiPatchCount,
        status: uiStatus,
        normalizedExact: false,
        projectionExact: false,
        routeRetained: uiRouteRetained,
        valueRetained: uiValueRetained,
        errorRole: uiErrorRole,
        errorVisible: uiErrorVisible,
        platformRejected,
      },
      backend: testCase.valid ? {
        status: backendStatus,
        normalizedExact: backendBody?.profile?.personal?.first_name === expected,
        projectionExact: inspectNyay5Projection(backendBody).pass,
        zeroMutation: false,
      } : {
        status: backendStatus,
        normalizedExact: false,
        projectionExact: false,
        zeroMutation: backendZeroMutation,
      },
    });
  }
  const corpusInspection = inspectLegalNameCorpusObservation(corpusRows, corpus.cases);
  await page.close();
  await context.close();

  failureStage = 'unicode_registration_core_only_mount';
  const registrationContext = await createNyay5Context(browser);
  const registrationPage = await registrationContext.newPage();
  const nonce = createHash('sha256').update(randomBytes(32)).digest('hex');
  const mobile = `9${[...nonce].map((value) => Number.parseInt(value, 16) % 10).join('').slice(0, 9)}`;
  rememberPrivate(mobile);
  let registrationBody = null;
  registrationPage.on('request', (request) => {
    if (request.method() === 'POST'
      && new URL(request.url()).pathname === '/api/v1/auth/student/register') {
      registrationBody = request.postDataJSON();
    }
  });
  await resetOtp();
  await registrationPage.goto(`${WEB}/s-08`, { waitUntil: 'domcontentloaded' });
  const academicControlsAbsent = await registrationPage.locator(
    'input[type="email"], #profile-academic-email, #profile-academic-college',
  ).count() === 0;
  await registrationPage.locator('#v34-first').fill('Core');
  await registrationPage.locator('#v34-last').fill('Only');
  await registrationPage.locator('#v34-mobile').fill(mobile);
  await registrationPage.locator('#v34-dob').fill('2000-01-01');
  for (const checkbox of await registrationPage.locator('input[type="checkbox"]').all()) {
    await checkbox.check();
  }
  const created = registrationPage.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/auth/student/register'
  ));
  failureStage = 'unicode_registration_core_only_submit';
  await registrationPage.getByRole('button', { name: 'Send one time code' }).click();
  const createdResponse = await created;
  await registrationPage.waitForURL(/\/s-09$/u);
  const coreKeys = [
    'dob', 'first_name', 'last_name', 'middle_name', 'mobile',
    'privacy_notice_acknowledged', 'privacy_notice_version',
    'terms_accepted', 'terms_version',
  ];
  const coreBodyExact = registrationBody
    && Object.keys(registrationBody).sort().join(',') === coreKeys.join(',');
  const registrationExact = createdResponse.status() === 202
    && inspectRegistrationStartWire(
      createdResponse.ok() ? await createdResponse.json() : null,
    ).pass
    && academicControlsAbsent && coreBodyExact;
  observe('unicode_legal_name_corpus', corpusInspection.pass && registrationExact, {
    cases: corpus.cases.length,
    passed: corpusInspection.passed,
    uiPassed: corpusInspection.uiPassed,
    backendPassed: corpusInspection.backendPassed,
    registrationWireExact: registrationExact,
    selectorCount: corpus.cases.length + await registrationPage.locator(
      '#v34-first, #v34-last, #v34-mobile, #v34-dob, #v34-terms, #v34-privacy',
    ).count(),
  });
  await recordStorage(registrationPage, 'registration');
  await registrationContext.close();
}

async function extendedStorageBoundaryProbe(browser) {
  failureStage = 'storage_provision';
  const { context } = await provisionStudent(
    browser, { firstName: 'Storage', signupSessionOnly: true },
  );
  const page = await context.newPage();
  trackActorBoundary(page);
  const seedUrl = `${WEB}/__nyay5-namespace-retirement-seed`;
  await page.route(seedUrl, (route) => route.fulfill({
    body: '<!doctype html><html><body>namespace seed</body></html>',
    contentType: 'text/html',
    status: 200,
  }), { times: 1 });
  await page.goto(seedUrl, { waitUntil: 'domcontentloaded' });
  const legacyNamespacePlanted = await page.evaluate(async () => {
    localStorage.removeItem('nyayone.theme.v1');
    localStorage.setItem('ls-theme', 'dark');
    localStorage.setItem('ls-onboarding-seen', 'seen');
    localStorage.setItem('ls-reviewer', '1');
    localStorage.setItem('ls-locale', 'en-IN');
    const retiredCache = await caches.open('ls-shell-v1');
    await retiredCache.put(
      new Request(`${location.origin}/index.html`, { credentials: 'same-origin' }),
      new Response('<!doctype html><title>retired shell</title>', {
        headers: { 'Content-Type': 'text/html' },
        status: 200,
      }),
    );
    const cacheNames = await caches.keys();
    return localStorage.getItem('nyayone.theme.v1') === null
      && localStorage.getItem('ls-theme') === 'dark'
      && localStorage.getItem('ls-onboarding-seen') === 'seen'
      && localStorage.getItem('ls-reviewer') === '1'
      && localStorage.getItem('ls-locale') === 'en-IN'
      && cacheNames.includes('ls-shell-v1');
  });
  if (!legacyNamespacePlanted) throw new Error('NYAY5_LEGACY_NAMESPACE_SEED_FAILED');
  failureStage = 'storage_s18';
  await page.goto(`${WEB}/s-18`, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-screen="S-18"]').waitFor();
  const migratedNamespace = await page.waitForFunction(async () => {
    if (!('serviceWorker' in navigator) || !('caches' in window)) return false;
    await navigator.serviceWorker.ready;
    const cacheNames = await caches.keys();
    return localStorage.getItem('nyayone.theme.v1') === 'dark'
      && ['ls-theme', 'ls-onboarding-seen', 'ls-reviewer', 'ls-locale']
        .every((key) => localStorage.getItem(key) === null)
      && cacheNames.includes('nyayone-shell-v1')
      && !cacheNames.includes('ls-shell-v1');
  });
  namespaceRetirementExact = legacyNamespacePlanted
    && await migratedNamespace.jsonValue() === true;
  await migratedNamespace.dispose();
  await recordStorage(page, 's18-settings');

  failureStage = 'storage_s19_export';
  await page.goto(`${WEB}/s-19`, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-screen="S-19"]').waitFor();
  const dataRightsDisclosure = page
    .locator('details.v34c-mobile-disclosure').filter({ hasText: 'Data rights' });
  const dataRightsSummary = dataRightsDisclosure.locator('summary');
  if ((await dataRightsDisclosure.getAttribute('open')) === null) {
    await dataRightsSummary.waitFor({ state: 'visible' });
    await dataRightsSummary.click();
  }
  const exportResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/student/privacy/export'
  ));
  await page.getByRole('button', { name: 'Export' }).click();
  const exportResponse = await exportResponsePromise;
  if (exportResponse.status() !== 202) throw new Error('NYAY5_PRIVACY_EXPORT_REQUEST_FAILED');
  await page.getByText(/Export request/iu).waitFor();
  await recordStorage(page, 's19-privacy-export');

  failureStage = 'storage_s20';
  await page.goto(`${WEB}/s-20`, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-screen="S-20"]').waitFor();
  const viewListing = page.getByRole('button', { name: 'View' }).first();
  await viewListing.waitFor();
  await recordStorage(page, 's20-internship-browse');
  await viewListing.click();
  failureStage = 'storage_s21';
  await page.waitForURL(/\/s-21\?listing=/u);
  await page.getByRole('button', { name: 'Apply now' }).waitFor();
  await recordStorage(page, 's21-internship-detail');
  await page.getByRole('button', { name: 'Apply now' }).click();
  failureStage = 'storage_s22';
  await page.waitForURL(/\/s-22\?listing=/u);
  await page.getByRole('button', { name: 'Continue to documents' }).waitFor();
  await recordStorage(page, 's22-internship-apply');
  await page.getByRole('button', { name: 'Continue to documents' }).click();
  const pdf = { name: 'synthetic.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF') };
  await page.locator('#app-resume').setInputFiles(pdf);
  await page.locator('#app-transcript').setInputFiles({ ...pdf, name: 'synthetic-transcript.pdf' });
  await page.getByRole('button', { name: 'Review application' }).click();
  await page.getByRole('button', { name: 'Submit application' }).click();
  failureStage = 'storage_s23';
  await page.waitForURL(/\/s-23\?listing=/u);
  await page.locator('[data-screen="S-23"]').waitFor();
  await recordStorage(page, 's23-internship-confirm');
  await page.getByRole('button', { name: 'Open tracker' }).click();
  failureStage = 'storage_s24';
  await page.waitForURL(/\/s-24$/u);
  await page.locator('[data-screen="S-24"]').waitFor();
  await recordStorage(page, 's24-internship-tracker');

  failureStage = 'storage_s65';
  await page.goto(`${WEB}/s-65`, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-screen="S-65"]').waitFor();
  await page.getByRole('button', { name: 'Send to institution' }).click();
  await page.getByRole('status').waitFor();
  await recordStorage(page, 's65-clinical-export');

  failureStage = 'storage_s86';
  await page.goto(`${WEB}/s-86`, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-screen="S-86"]').waitFor();
  await page.locator('#ir-organisation').fill('Synthetic Organisation');
  const draftResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/v1/internship-reports'
  ));
  await page.getByRole('button', { name: 'Save private draft' }).click();
  const draftResponse = await draftResponsePromise;
  if (draftResponse.status() !== 201) throw new Error('NYAY5_PRIVATE_REPORT_DRAFT_FAILED');
  await page.getByText(/Draft saved privately/iu).waitFor();
  await recordStorage(page, 's86-private-report-draft');

  failureStage = 'storage_s93';
  await page.goto(`${WEB}/s-93?tab=reminders`, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-screen="S-93"]').waitFor();
  await page.locator('[data-wave5-ready="ready"]').waitFor();
  const reminderRow = page.locator('[data-testid^="cal-reminder-"]').first();
  await reminderRow.waitFor();
  await reminderRow.getByRole('button', { name: /^Configure /u }).click();
  const reminderCheckbox = reminderRow.locator('input[type="checkbox"]');
  const reminderResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname === '/api/v1/calendar/reminder-preferences'
  ));
  await reminderCheckbox.click();
  const reminderResponse = await reminderResponsePromise;
  if (reminderResponse.status() !== 200) throw new Error('NYAY5_REMINDER_UPDATE_FAILED');
  await reminderRow.getByText('Saved.').waitFor();
  const namespaceRetirementStillExact = await page.evaluate(async () => {
    const cacheNames = await caches.keys();
    return localStorage.getItem('nyayone.theme.v1') === 'dark'
      && ['ls-theme', 'ls-onboarding-seen', 'ls-reviewer', 'ls-locale']
        .every((key) => localStorage.getItem(key) === null)
      && cacheNames.includes('nyayone-shell-v1')
      && !cacheNames.includes('ls-shell-v1');
  });
  namespaceRetirementExact = namespaceRetirementExact && namespaceRetirementStillExact;
  if (!namespaceRetirementExact) throw new Error('NYAY5_NAMESPACE_RETIREMENT_FAILED');
  await recordStorage(page, 's93-server-reminders');
  await context.close();
}

async function run() {
  let browser;
  try {
    const readinessVarianceProof = runSeededHeadingStackVariance({ attempts: 1 });
    const readinessVarianceProofExact = readinessVarianceProof.attempts === 1
      && readinessVarianceProof.assertion === 'browser:redesigned_heading_stack'
      && readinessVarianceProof.legacyOutcome === 'FAIL_EARLY_SAMPLE'
      && readinessVarianceProof.settledOutcome === 'PASS';
    if (!readinessVarianceProofExact) {
      throw new Error('NYAY26_SEEDED_VARIANCE_PROOF_INVALID');
    }
    browser = await chromium.launch({ headless: true });
    observe('runtime_chromium', true, { engine: 'chromium', headless: true });
    failureStage = 'auth_wire_passwordless';
     await authWireAndPasswordlessProbe(browser);
     failureStage = 'pending_denial';
     await pendingAndDenialProbe(browser);
     failureStage = 'complete_profile';
     await completeProfileProbe(browser);
     failureStage = 'cross_realm_auth_transition';
     const crossRealmTransition = await crossRealmAuthTransitionProbe(browser);
     crossRealmTransitionExact = crossRealmTransition.pass;
    failureStage = 'prompt_routing';
    await promptAndRoutingProbe(browser);
    failureStage = 'cross_user_stale_uncertain';
    await staleCrossUserAndUncertainProbe(browser);
    failureStage = 'minor_responsive';
    await minorAndResponsiveProbe(browser);
    failureStage = 'unicode_registration';
    await unicodeAndRegistrationProbe(browser);
    failureStage = 'extended_storage_boundary';
    await extendedStorageBoundaryProbe(browser);
     observe('production_actor_channel_exact', authWireExact && crossRealmTransitionExact
       && requests.length > 0 && requests.every(Boolean), {
       authWireExact,
       crossRealmTransitionExact,
      requests: requests.length,
      exact: requests.filter(Boolean).length,
    });
    const storageSurfaceResults = inspectStorageSurfaceResults(storageChecks);
    observe('browser_persistence_inventory_clean',
      namespaceRetirementExact && storageSurfaceResults.pass, {
      surfaces: storageChecks.length,
      clean: storageChecks.filter((entry) => entry.pass).length,
      exact: storageSurfaceResults.exact,
      namespaceRetirementExact,
    });
    failureStage = null;
  } catch (error) {
    failureClass = error instanceof Error ? error.constructor.name : 'NonError';
    failureCode = error instanceof Error && /^NYAY5_[A-Z0-9_]+$/u.test(error.message)
      ? error.message : 'RUNTIME_ASSERTION_FAILED';
  } finally {
    await browser?.close().catch(() => {});
  }

  const rows = NYAY5_ASSERTION_INVENTORY.map((name) => ({ name, ...observations.get(name) }));
  const preliminary = summarizeNyay5Rows(rows);
  const mutantResults = seededNyay5MutantResults();
  const privateValueLeak = [...privateValues].some((value) => JSON.stringify(rows).includes(value));
  const requiredVisualScreens = Array.from({ length: 15 }, (_, index) => (
    `S-${String(index + 3).padStart(2, '0')}`
  ));
  const visualRows = requiredVisualScreens.map((screenId) => visualScreens.get(screenId));
  const visualHeadingCount = visualRows.reduce(
    (total, row) => total + Number(row?.headingCount ?? 0), 0,
  );
  const visualIconCount = visualRows.reduce(
    (total, row) => total + Number(row?.iconCount ?? 0), 0,
  );
  const visualScreensExact = visualRows.filter((row) => (
    row?.headingCount > 0
    && row?.typographyExact === true
    && row?.iconsExact === true
    && row?.legacyBrandVisible === false
  )).length;
  const visualContractExact = visualRows.every((row) => (
    row?.headingCount > 0
    && row?.typographyExact === true
    && row?.iconsExact === true
    && row?.legacyBrandVisible === false
  )) && visualRows.reduce((total, row) => total + Number(row?.iconCount ?? 0), 0) > 0;
  const screenshotInventoryExact = screenshotNames.size === 2;
  const privacyFindings = scanNyay5Evidence({
    rows,
    failureClass,
    failureStage,
    failureCode,
    total: preliminary.total,
    passed: preliminary.passed,
    failed: preliminary.failed,
  });
  const evidenceInputsPass = mutantResults.allKilled
    && !privateValueLeak
    && privacyFindings.length === 0
    && visualContractExact
    && screenshotInventoryExact;

  if (failureClass === null) {
    recordBrowserExecution(
      'redesigned_heading_stack',
      visualRows.every((row) => row?.headingCount > 0 && row?.typographyExact === true),
      requiredVisualScreens.length,
      visualHeadingCount,
    );
    recordBrowserExecution(
      'svg_icon_census',
      visualIconCount > 0 && visualRows.every((row) => row?.iconsExact === true),
      requiredVisualScreens.length,
      visualIconCount,
    );
    recordBrowserExecution(
      'rebrand_visible_copy',
      visualRows.every((row) => row?.legacyBrandVisible === false),
      requiredVisualScreens.length,
      requiredVisualScreens.length,
    );
    const responsive = observations.get('responsive_targets_and_no_overflow').metrics;
    recordObservedBrowserExecution(
      'responsive_targets_and_no_overflow',
      'responsive_targets_and_no_overflow',
      responsive.cases,
      responsive.selectorCount,
    );
    const storage = observations.get('browser_persistence_inventory_clean').metrics;
    recordObservedBrowserExecution(
      'browser_persistence_inventory_clean',
      'browser_persistence_inventory_clean',
      storage.surfaces,
    );
    const unicode = observations.get('unicode_legal_name_corpus').metrics;
    recordObservedBrowserExecution(
      'unicode_legal_name_corpus',
      'unicode_legal_name_corpus',
      unicode.cases,
    );
    const crossUser = observations.get('cross_user_denied').metrics;
    recordObservedBrowserExecution(
      'cross_user_denied', 'cross_user_denied', crossUser.cases,
    );
    const actorChannel = observations.get('production_actor_channel_exact').metrics;
    recordObservedBrowserExecution(
      'production_actor_channel_exact',
      'production_actor_channel_exact',
      actorChannel.requests,
    );
    const promptSession = observations.get('prompt_session_scoped').metrics;
    recordObservedBrowserExecution(
      'prompt_session_scoped',
      'prompt_session_scoped',
      2,
      promptSession.selectorCount,
    );
    const verification = observations.get('verification_distinct_from_completion').metrics;
    recordBrowserExecution(
      's15_back_to_dashboard_exact',
      verification.s15BackExact === true,
      1,
      verification.s15BackSelectorCount,
    );
    recordObservedBrowserExecution(
      'verification_distinct_from_completion',
      'verification_distinct_from_completion',
      4,
      verification.actionSelectorCount,
    );
    const denial = observations.get('denial_matrix_fail_closed').metrics;
    recordObservedBrowserExecution(
      'denial_matrix_fail_closed',
      'denial_matrix_fail_closed',
      denial.cases + denial.limitedChecks,
      denial.selectorCount,
    );
    const route = observations.get('direct_step_skip_denied').metrics;
    recordObservedBrowserExecution(
      'direct_step_skip_denied',
      'direct_step_skip_denied',
      route.cases,
      route.selectorCount,
    );
    const projection = observations.get('single_authoritative_projection').metrics;
    recordObservedBrowserExecution(
      'single_authoritative_projection',
      'single_authoritative_projection',
      projection.projections,
      projection.selectorCount,
    );
    const confirmed = observations.get('confirmed_success_before_navigation').metrics;
    recordObservedBrowserExecution(
      'confirmed_success_before_navigation',
      'confirmed_success_before_navigation',
      1,
      confirmed.selectorCount,
    );
     const failures = observations.get('typed_failures_retain_route_and_values').metrics;
    recordObservedBrowserExecution(
      'typed_failures_retain_route_and_values',
      'typed_failures_retain_route_and_values',
      failures.cases,
       failures.selectorCount,
     );
     recordBrowserExecution(
       'canonical_401_draft_handoff',
       canonical401DraftHandoffProbe(failures),
       10,
       failures.canonical401?.restoredSelectorCount ?? 0,
     );
    const uncertain = observations.get('uncertain_write_reconciles').metrics;
    recordObservedBrowserExecution(
      'uncertain_write_reconciles',
      'uncertain_write_reconciles',
      uncertain.writeCount + Number(uncertain.refetchedBeforeRetry),
      uncertain.selectorCount,
    );
    const resumed = observations.get('reload_new_tab_resume').metrics;
    recordObservedBrowserExecution(
      'reload_new_tab_resume',
      'reload_new_tab_resume',
      2,
      resumed.selectorCount,
    );
    const stale = observations.get('stale_multi_tab_conflict').metrics;
    recordObservedBrowserExecution(
      'stale_multi_tab_conflict',
      'stale_multi_tab_conflict',
      stale.tabs,
      stale.selectorCount,
    );
    const dialog = observations.get('dialog_focus_and_inert_contract').metrics;
    recordObservedBrowserExecution(
      'dialog_focus_and_inert_contract',
      'dialog_focus_and_inert_contract',
      dialog.focusChecks + 2,
      dialog.selectorCount,
    );
    const promptLifecycle = observations.get('prompt_lifecycle_teardown').metrics;
    recordObservedBrowserExecution(
      'prompt_lifecycle_teardown',
      'prompt_lifecycle_teardown',
      3,
      promptLifecycle.selectorCount,
    );
    const accessible = observations.get('accessible_errors_and_controls').metrics;
    recordObservedBrowserExecution(
      'accessible_errors_and_controls',
      'accessible_errors_and_controls',
      accessible.selectorCount,
      accessible.selectorCount,
    );
    recordObservedBrowserExecution('runtime_chromium', 'runtime_chromium', 1);
    recordBrowserExecution(
      'evidence_privacy_and_mutants',
      evidenceInputsPass,
      mutantResults.named + screenshotNames.size + requiredVisualScreens.length,
    );
  }

  const acceptanceExecutionCoverage = inspectBrowserExecutionCoverage(
    [...browserExecutions.values()],
  );
  const finalPass = evidenceInputsPass && acceptanceExecutionCoverage.pass;
  observe('evidence_privacy_and_mutants', finalPass, {
    mutantsNamed: mutantResults.named,
    mutantsKilled: mutantResults.killed,
    privateValueLeak,
    privacyFindingCount: privacyFindings.length,
    visualScreens: visualRows.length,
    visualScreensExact,
    screenshotCount: screenshotNames.size,
    acceptanceExecutionMapped: acceptanceExecutionCoverage.mapped,
    acceptanceExecutionMissing: acceptanceExecutionCoverage.missing,
    acceptanceExecutionUnknown: acceptanceExecutionCoverage.unknown,
  });

  const finalRows = NYAY5_ASSERTION_INVENTORY.map((name) => ({ name, ...observations.get(name) }));
  const summary = summarizeNyay5Rows(finalRows);
  const successfulReport = summary.overallPass
    && failureClass === null
    && failureStage === null
    && failureCode === null;
  const report = {
    gate: 'nyay5_profile_browser',
    target: 'isolated-loopback-real-api-postgresql-chromium',
    executed: observations.get('runtime_chromium').metrics.executed,
    status: successfulReport ? 'PASS' : 'FAIL',
    total: summary.total,
    passed: summary.passed,
    failed: summary.failed,
    inventoryExact: summary.inventoryExact,
    artifacts: { screenshots: screenshotNames.size },
    rows: finalRows,
    executions: [...browserExecutions.values()],
    acceptanceExecutionCoverage,
    failureClass,
    failureStage,
    failureCode,
  };
  const finalFindings = scanNyay5Evidence(report);
  if (finalFindings.length > 0) {
    report.status = 'FAIL';
    report.failed = Math.max(1, report.failed);
  }
  await mkdir(dirname(OUTPUT), { recursive: true });
  await writeFile(OUTPUT, `${JSON.stringify(report, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
  process.stdout.write(`${JSON.stringify({
    gate: report.gate,
    status: report.status,
    total: report.total,
    passed: report.passed,
    failed: report.failed,
    diagnostics: report.status === 'FAIL'
      ? summarizeNyay5BrowserFailure(report) : null,
  })}\n`);
  if (report.status !== 'PASS') process.exitCode = 1;
}

await run();
