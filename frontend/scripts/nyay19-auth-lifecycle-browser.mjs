import { createHash } from 'node:crypto';
import { chromium } from 'playwright';
import {
  NYAY19_MUTATION_TRACE,
  buildNyay19AbortEnvelope,
  hasExactAuthenticatedStudentSession,
  hasExactAuthenticationRequired,
  hasExactProtectedAuthorityChannel,
  hasFutureCookieExpiry,
  inspectAuthorityCookieInventory,
  inspectCookieRetirementHeaders,
  inspectCookieTransitionHeaders,
  inspectCaptureFinality,
  inspectExactOrderedMutationTrace,
  inspectIndependentProtectedProbes,
  inspectNyay19SessionBootstrap,
  inspectStudentContextBoundary,
  nextNyay19LoginIssuanceDelay,
  parseNyay19OtpCooldown,
  parseNyay19OtpFlowTtl,
  parseNyay19SessionTtl,
  scanNyay19Evidence,
  snapshotNyay19MutationRequest,
  summarizeNyay19Rows,
} from './lib/nyay19-auth-lifecycle-runner-contract.mjs';

const WEB = process.env.NYAY19_WEB_BASE_URL ?? 'http://127.0.0.1:4179';
const API = process.env.NYAY19_API_BASE_URL ?? 'http://127.0.0.1:1139';
const CAPTURE = process.env.NYAY19_OTP_CAPTURE_URL ?? 'http://127.0.0.1:1099';
const SESSION_TTL_SECONDS = parseNyay19SessionTtl(
  process.env.NYAY19_SESSION_TTL_SECONDS ?? '20',
);
const OTP_COOLDOWN_SECONDS = parseNyay19OtpCooldown(
  process.env.NYAY19_OTP_RESEND_COOLDOWN_SECONDS ?? '1',
);
const OTP_FLOW_TTL_SECONDS = parseNyay19OtpFlowTtl(
  process.env.NYAY19_OTP_FLOW_TTL_SECONDS ?? '600',
);
const RECOVERY_PROOF_TTL_SECONDS_RAW = process.env.NYAY19_RECOVERY_PROOF_TTL_SECONDS ?? '300';
if (!/^[1-9]\d{0,4}$/u.test(RECOVERY_PROOF_TTL_SECONDS_RAW)) {
  throw new Error('NYAY19_RECOVERY_PROOF_TTL_INVALID');
}
const RECOVERY_PROOF_TTL_SECONDS = Number.parseInt(RECOVERY_PROOF_TTL_SECONDS_RAW, 10);
const WEB_ORIGIN = new URL(WEB).origin;
const API_ORIGIN = new URL(API).origin;
const API_HOST = new URL(API).hostname;
const API_LOCAL_HTTP = new URL(API).protocol === 'http:'
  && ['127.0.0.1', 'localhost', '::1'].includes(API_HOST);
const SESSION_COOKIE = 'nyayone_session';
const FLOW_COOKIE = 'nyayone_otp_flow';
const SESSION_BOOTSTRAP_EXPECTED = 2;
const SESSION_BOOTSTRAP_TIMEOUT_MS = 10_000;
let lastLoginIssueConfirmedAt = 0;
let sessionProbeSequence = 0;

const rows = [];
const mutationTrace = [];
const forbiddenEvidenceValues = new Set();
const record = (name, expected, actual, pass) => rows.push({ name, expected, actual, pass });

class Nyay19BootstrapTimeoutError extends Error {
  constructor() {
    super('session bootstrap timeout');
    this.name = 'Nyay19BootstrapTimeoutError';
  }
}

class Nyay19BootstrapInvariantError extends Error {
  constructor() {
    super('session bootstrap invariant');
    this.name = 'Nyay19BootstrapInvariantError';
  }
}

function rememberSecret(value) {
  if (typeof value === 'string' && value.length > 0) forbiddenEvidenceValues.add(value);
}

async function rememberCookieValues(context) {
  for (const cookie of await context.cookies()) rememberSecret(cookie.value);
}

function captureBrowserMutations(page) {
  page.on('request', (request) => {
    if (request.method() === 'POST') {
      mutationTrace.push({ snapshot: snapshotNyay19MutationRequest(request) });
    }
  });
}

async function resetCapture() {
  const response = await fetch(`${CAPTURE}/reset`, { method: 'POST' });
  if (!response.ok) throw new Error('NYAY19_CAPTURE_RESET_FAILED');
}

async function latestOtp(mobile) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const response = await fetch(`${CAPTURE}/latest`);
    if (response.ok) {
      const payload = await response.json();
      if (payload?.to === mobile && /^\d{6}$/u.test(payload?.code ?? '')) {
        rememberSecret(payload.code);
        return payload.code;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('NYAY19_CAPTURE_CODE_UNAVAILABLE');
}

async function clearCaptureEvidence() {
  const resetResponse = await fetch(`${CAPTURE}/reset`, { method: 'POST' });
  const resetBody = await resetResponse.json().catch(() => null);
  const reads = [];
  for (let index = 0; index < 2; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const response = await fetch(`${CAPTURE}/latest`);
    reads.push({
      status: response.status,
      body: await response.json().catch(() => null),
    });
  }
  return inspectCaptureFinality(
    { status: resetResponse.status, body: resetBody },
    reads,
  );
}

function exactAnonymousSession(body) {
  return body
    && Object.keys(body).sort().join(',') === 'actor,authenticated'
    && body.authenticated === false
    && body.actor === null;
}

async function waitForNextLoginIssuance() {
  const delayMs = nextNyay19LoginIssuanceDelay(
    lastLoginIssueConfirmedAt,
    Date.now(),
    OTP_COOLDOWN_SECONDS,
  );
  if (!Number.isFinite(delayMs)) throw new Error('NYAY19_LOGIN_COOLDOWN_INVALID');
  if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
}

async function setupDisposableStudent(browser, mobile, idempotencyKey) {
  const context = await browser.newContext();
  try {
    await resetCapture();
    const registration = await context.request.post(
      `${API}/api/v1/auth/student/register`,
      {
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
          Origin: WEB_ORIGIN,
        },
        data: {
          first_name: 'Nyay',
          middle_name: null,
          last_name: 'Lifecycle',
          mobile,
          dob: '2004-03-14',
          consent: { accepted: true, policy_version: 'nyay19-browser-lifecycle' },
        },
      },
    );
    await rememberCookieValues(context);
    const code = await latestOtp(mobile);
    const verification = await context.request.post(
      `${API}/api/v1/auth/student/otp/verify`,
      { headers: { Origin: WEB_ORIGIN }, data: { code } },
    );
    await rememberCookieValues(context);
    const logout = await context.request.post(
      `${API}/api/v1/auth/student/logout`,
      { headers: { Origin: WEB_ORIGIN }, data: {} },
    );
    const cookiesAfter = await context.cookies();
    return {
      registrationHttp: registration.status(),
      verificationHttp: verification.status(),
      logoutHttp: logout.status(),
      cookiesRetired: cookiesAfter.length === 0,
    };
  } finally {
    await context.close();
  }
}

async function productStudentSession(page) {
  sessionProbeSequence += 1;
  const probeId = `nyay19-session-probe-${sessionProbeSequence}`;
  rememberSecret(probeId);
  const responsePromise = page.waitForResponse(async (response) => {
    if (response.request().method() !== 'GET'
        || new URL(response.url()).origin !== API_ORIGIN
        || new URL(response.url()).pathname !== '/api/v1/auth/student/session') return false;
    const requestIds = (await response.request().headersArray()).filter((header) => (
      header?.name?.toLowerCase() === 'x-request-id'
    ));
    return requestIds.length === 1 && requestIds[0].value === probeId;
  });
  const bodyPromise = page.evaluate(async ({ requestId }) => {
    const studentApi = await import('/src/features/student/lib/studentApiClient.ts');
    const response = await studentApi.studentApiFetch(
      '/api/v1/auth/student/session',
      { method: 'GET', requestId },
      { notifyAuthChanged: false },
    );
    return response.json();
  }, { requestId: probeId });
  const [response, body] = await Promise.all([responsePromise, bodyPromise]);
  const actor = await page.evaluate(async () => {
    const registrationApi = await import('/src/features/student/lib/registrationApi.ts');
    return registrationApi.getStudentSession();
  });
  return { response, body, actor, request: response.request() };
}

async function loginWithBrowser(browser, mobile) {
  await resetCapture();
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  captureBrowserMutations(page);
  await page.goto(`${WEB}/s-04`, { waitUntil: 'domcontentloaded' });
  await page.locator('[data-screen="S-04"]').waitFor({ state: 'visible' });
  await page.getByRole('button', { name: 'Use a one time code' }).click();
  await page.locator('#v34-login-mobile').fill(mobile);
  await waitForNextLoginIssuance();
  const startPromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/login/otp/start'
  ));
  await page.getByRole('button', { name: 'Send one time code' }).click();
  const startResponse = await startPromise;
  lastLoginIssueConfirmedAt = Date.now();
  const startCookieTransition = inspectCookieTransitionHeaders(
    await startResponse.headersArray(),
    [{ name: FLOW_COOKIE, action: 'issue', maxAge: OTP_FLOW_TTL_SECONDS }],
    API,
  );
  await rememberCookieValues(context);
  const code = await latestOtp(mobile);
  const verifyPromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/login/otp/verify'
  ));
  await page.getByLabel('Six digit code').fill(code);
  await page.getByRole('button', { name: 'Verify and continue' }).click();
  const verifyResponse = await verifyPromise;
  const loginCookieTransition = inspectCookieTransitionHeaders(
    await verifyResponse.headersArray(),
    [
      { name: SESSION_COOKIE, action: 'issue', maxAge: SESSION_TTL_SECONDS },
      { name: FLOW_COOKIE, action: 'retire' },
    ],
    API,
  );
  await page.locator('[data-screen="S-07"]').waitFor({ state: 'visible' });
  const session = await productStudentSession(page);
  if (!hasExactAuthenticatedStudentSession(session.body, session.actor)) {
    throw new Error('NYAY19_BROWSER_ACTOR_INVALID');
  }
  rememberSecret(session.actor.sub);
  rememberSecret(session.actor.student_profile_id);
  await rememberCookieValues(context);
  return {
    context,
    page,
    actor: session.actor,
    startHttp: startResponse.status(),
    startCookieTransitionExact: startCookieTransition.pass,
    verifyHttp: verifyResponse.status(),
    loginCookieTransitionExact: loginCookieTransition.pass,
  };
}

async function studentContextSnapshot(page, actor) {
  return page.evaluate(async ({ subject, studentProfileId }) => {
    const [{ queryClient }, attemptStore, profileStore] = await Promise.all([
      import('/src/app/queryClient.ts'),
      import('/src/features/student/lib/registrationAttemptStore.ts'),
      import('/src/features/student/lib/profileStore.ts'),
    ]);
    const localBase = [
      'legalsaathi.student.profile.v1',
      'legalsaathi.student.onboarding.v34',
      'legalsaathi.internship.applications.v1',
      'legalsaathi.clinical.export-audit.v1',
      'ls-auth-student',
    ];
    const sessionBase = [
      'legalsaathi.student.registration.v2',
      'legalsaathi.student.privacy.export.v1',
      'legalsaathi.student.privacy.delete.v1',
    ];
    const actorIds = [...new Set([subject, studentProfileId].filter(Boolean))];
    const actorKeys = actorIds.flatMap((id) => [`ls-reports-${id}`, `ls-reminder-prefs-${id}`]);
    const managedExpectedCount = localBase.length + sessionBase.length + actorKeys.length;
    const managedPresentCount = [...localBase, ...actorKeys]
      .filter((key) => localStorage.getItem(key) !== null).length
      + sessionBase.filter((key) => sessionStorage.getItem(key) !== null).length;
    const profile = profileStore.getProfileDraft();
    const profileDraftPresent = Boolean(
      profile.firstName || profile.middleName || profile.lastName || profile.fullName
      || profile.dateOfBirth || profile.college || profile.yearOfStudy
      || profile.enrolmentNumber || profile.institutionalEmail
      || profile.barEnrolmentNumber || profile.interests.length || profile.careerGoal,
    );
    return {
      managedExpectedCount,
      managedPresentCount,
      retiredActorRegistryAbsent:
        localStorage.getItem('legalsaathi.student.cleanup-registry.v1') === null
        && sessionStorage.getItem('legalsaathi.student.cleanup-registry.v1') === null,
      registrationAttemptPresent: attemptStore.getRegistrationAttempt() !== null,
      profileDraftPresent,
      queryCacheCount: queryClient.getQueryCache().getAll().length,
      mutationCacheCount: queryClient.getMutationCache().getAll().length,
      controls: {
        theme: localStorage.getItem('ls-theme'),
        locale: localStorage.getItem('ls-locale'),
        unrelated: localStorage.getItem('nyay19-unrelated-control'),
      },
    };
  }, { subject: actor.sub, studentProfileId: actor.student_profile_id });
}

async function seedStudentContext(page, actor) {
  await page.evaluate(async ({ subject, studentProfileId }) => {
    const [{ queryClient }, attemptStore, profileStore] = await Promise.all([
      import('/src/app/queryClient.ts'),
      import('/src/features/student/lib/registrationAttemptStore.ts'),
      import('/src/features/student/lib/profileStore.ts'),
    ]);
    attemptStore.setRegistrationAttempt({ body: 'planted-private-body', key: 'planted-private-key' });
    profileStore.updateProfileDraft({ fullName: 'Planted private draft' });
    queryClient.setQueryData(['nyay19-private-query'], { planted: true });
    queryClient.getMutationCache().build(queryClient, {
      mutationKey: ['nyay19-private-mutation'],
      mutationFn: async () => true,
    });
    for (const key of [
      'legalsaathi.student.profile.v1',
      'legalsaathi.student.onboarding.v34',
      'legalsaathi.internship.applications.v1',
      'legalsaathi.clinical.export-audit.v1',
      'ls-auth-student',
    ]) localStorage.setItem(key, 'planted-private-state');
    for (const key of [
      'legalsaathi.student.registration.v2',
      'legalsaathi.student.privacy.export.v1',
      'legalsaathi.student.privacy.delete.v1',
    ]) sessionStorage.setItem(key, 'planted-private-state');
    const actorIds = [...new Set([subject, studentProfileId].filter(Boolean))];
    for (const id of actorIds) {
      localStorage.setItem(`ls-reports-${id}`, 'planted-private-state');
      localStorage.setItem(`ls-reminder-prefs-${id}`, 'planted-private-state');
    }
    localStorage.setItem('ls-theme', 'dark');
    localStorage.setItem('ls-locale', 'hi');
    localStorage.setItem('nyay19-unrelated-control', 'retain');
  }, { subject: actor.sub, studentProfileId: actor.student_profile_id });
  return studentContextSnapshot(page, actor);
}

function isExactBootstrapSessionRequest(request) {
  try {
    const url = new URL(request.url());
    return request.method() === 'GET'
      && url.origin === API_ORIGIN
      && url.pathname === '/api/v1/auth/student/session'
      && url.search === ''
      && url.hash === '';
  } catch {
    return false;
  }
}

function createExactSessionBootstrapBarrier(page) {
  const requests = new Set();
  const responses = new Set();
  const finished = new Set();
  const failed = new Set();
  let responsesSuccessful = true;
  let settled = false;
  let resolveReady;
  let rejectReady;

  const inspect = () => inspectNyay19SessionBootstrap({
    requestCount: requests.size,
    responseCount: responses.size,
    finishedCount: finished.size,
    failedCount: failed.size,
    responsesSuccessful,
  });
  const rejectInvariant = () => {
    if (settled) return;
    settled = true;
    rejectReady(new Nyay19BootstrapInvariantError());
  };
  const notify = () => {
    const inspection = inspect();
    if (inspection.requestCount > SESSION_BOOTSTRAP_EXPECTED
        || inspection.responseCount > SESSION_BOOTSTRAP_EXPECTED
        || inspection.finishedCount > SESSION_BOOTSTRAP_EXPECTED
        || inspection.failedCount > 0
        || inspection.responseCount > inspection.requestCount
        || inspection.finishedCount > inspection.requestCount
        || !inspection.responsesSuccessful) {
      rejectInvariant();
      return;
    }
    if (inspection.pass && !settled) {
      settled = true;
      resolveReady(inspection);
    }
  };
  const onRequest = (request) => {
    if (!isExactBootstrapSessionRequest(request)) return;
    requests.add(request);
    notify();
  };
  const onResponse = (response) => {
    const request = response.request();
    if (!requests.has(request)) return;
    responses.add(request);
    responsesSuccessful = responsesSuccessful && response.status() === 200;
    notify();
  };
  const onRequestFinished = (request) => {
    if (!requests.has(request)) return;
    finished.add(request);
    notify();
  };
  const onRequestFailed = (request) => {
    if (!requests.has(request)) return;
    failed.add(request);
    notify();
  };

  const ready = new Promise((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  const timeout = setTimeout(() => {
    if (settled) return;
    settled = true;
    rejectReady(new Nyay19BootstrapTimeoutError());
  }, SESSION_BOOTSTRAP_TIMEOUT_MS);

  page.on('request', onRequest);
  page.on('response', onResponse);
  page.on('requestfinished', onRequestFinished);
  page.on('requestfailed', onRequestFailed);

  return {
    inspect,
    waitForExact: () => ready,
    dispose: () => {
      clearTimeout(timeout);
      page.off('request', onRequest);
      page.off('response', onResponse);
      page.off('requestfinished', onRequestFinished);
      page.off('requestfailed', onRequestFailed);
    },
  };
}

async function openProtectedProbePage(context) {
  const page = await context.newPage();
  const bootstrap = createExactSessionBootstrapBarrier(page);
  try {
    await Promise.all([
      bootstrap.waitForExact(),
      page.goto(`${WEB}/s-03`, {
        waitUntil: 'domcontentloaded',
        timeout: SESSION_BOOTSTRAP_TIMEOUT_MS,
      }),
      page.locator('[data-screen="S-03"]').waitFor({
        state: 'visible',
        timeout: SESSION_BOOTSTRAP_TIMEOUT_MS,
      }),
    ]);
    const inspection = bootstrap.inspect();
    if (inspection.expectedCount !== SESSION_BOOTSTRAP_EXPECTED || !inspection.pass) {
      throw new Nyay19BootstrapInvariantError();
    }
    return page;
  } finally {
    bootstrap.dispose();
  }
}

async function ambientCookieOnlyProtectedProbe(browser, rawCookie) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const page = await openProtectedProbePage(context);
    await context.addCookies([{
      name: SESSION_COOKIE,
      value: rawCookie,
      domain: API_HOST,
      path: '/api/v1',
      httpOnly: true,
      secure: !API_LOCAL_HTTP,
      sameSite: 'Strict',
    }]);
    const protectedRequests = [];
    page.on('request', (request) => {
      try {
        const url = new URL(request.url());
        if (request.method() === 'GET'
            && url.origin === API_ORIGIN
            && url.pathname === '/api/v1/student/profile') protectedRequests.push(request);
      } catch { /* fail closed through exact cardinality */ }
    });
    const responsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && new URL(response.url()).origin === API_ORIGIN
        && new URL(response.url()).pathname === '/api/v1/student/profile'
    ));
    await page.evaluate(async (api) => {
      await fetch(`${api}/api/v1/student/profile`, {
        method: 'GET',
        credentials: 'include',
      });
    }, API);
    const response = await responsePromise;
    const body = await response.json();
    rememberSecret(body?.request_id);
    return {
      channel: 'ambient',
      request: protectedRequests[0],
      requestCount: protectedRequests.length,
      channelExact: protectedRequests.length === 1
        && await hasExactProtectedAuthorityChannel(
          protectedRequests[0],
          'ambient',
          SESSION_COOKIE,
          rawCookie,
          API_ORIGIN,
        ),
      denialExact: await hasExactAuthenticationRequired(response, body),
    };
  } finally {
    await context.close();
  }
}

async function bearerOnlyProtectedProbe(browser, rawCookie) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const page = await openProtectedProbePage(context);
    const cookiesBefore = (await context.cookies()).length;
    const protectedRequests = [];
    page.on('request', (request) => {
      try {
        const url = new URL(request.url());
        if (request.method() === 'GET'
            && url.origin === API_ORIGIN
            && url.pathname === '/api/v1/student/profile') protectedRequests.push(request);
      } catch { /* fail closed through exact cardinality */ }
    });
    const responsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && new URL(response.url()).origin === API_ORIGIN
        && new URL(response.url()).pathname === '/api/v1/student/profile'
    ));
    await page.evaluate(async ({ api, bearer }) => {
      await fetch(`${api}/api/v1/student/profile`, {
        method: 'GET',
        credentials: 'omit',
        headers: { Authorization: `Bearer ${bearer}` },
      });
    }, { api: API, bearer: rawCookie });
    const response = await responsePromise;
    const body = await response.json();
    rememberSecret(body?.request_id);
    const cookiesAfter = (await context.cookies()).length;
    return {
      channel: 'bearer',
      request: protectedRequests[0],
      requestCount: protectedRequests.length,
      cookiesBefore,
      cookiesAfter,
      channelExact: protectedRequests.length === 1
        && await hasExactProtectedAuthorityChannel(
          protectedRequests[0],
          'bearer',
          SESSION_COOKIE,
          rawCookie,
          API_ORIGIN,
        ),
      denialExact: await hasExactAuthenticationRequired(response, body),
    };
  } finally {
    await context.close();
  }
}

async function independentStaleAuthorityProbes(browser, rawCookie) {
  const ambient = await ambientCookieOnlyProtectedProbe(browser, rawCookie);
  const bearer = await bearerOnlyProtectedProbe(browser, rawCookie);
  return inspectIndependentProtectedProbes(ambient, bearer);
}

async function staleCookieSessionProbe(browser, rawCookie) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const page = await openProtectedProbePage(context);
    await context.addCookies([{
      name: SESSION_COOKIE,
      value: rawCookie,
      domain: API_HOST,
      path: '/api/v1',
      httpOnly: true,
      secure: !API_LOCAL_HTTP,
      sameSite: 'Strict',
    }]);
    const session = await productStudentSession(page);
    const retirement = inspectCookieRetirementHeaders(
      await session.response.headersArray(),
      [SESSION_COOKIE],
      API,
    );
    const absent = inspectAuthorityCookieInventory(await context.cookies(), [], API);
    const correlatedStaleCookieExact = await hasExactProtectedAuthorityChannel(
      session.request,
      'ambient',
      SESSION_COOKIE,
      rawCookie,
      API_ORIGIN,
      '/api/v1/auth/student/session',
    );
    return {
      anonymousExact: exactAnonymousSession(session.body) && session.actor === null,
      retirementExact: retirement.pass,
      retirementHeaderCount: retirement.total,
      retirementNamesExact: retirement.exactNames,
      retirementComponents: retirement.components,
      correlatedStaleCookieExact,
      authorityCookieAbsent: absent.pass,
    };
  } finally {
    await context.close();
  }
}

async function startRecoveryFlowForLogout(page, mobile) {
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/recovery/start'
  ));
  const statusPromise = page.evaluate(async ({ api, rawMobile }) => {
    const response = await fetch(`${api}/api/v1/auth/student/recovery/start`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mobile: rawMobile }),
    });
    return response.status;
  }, { api: API, rawMobile: mobile });
  const [response, status] = await Promise.all([responsePromise, statusPromise]);
  const startCookieTransition = inspectCookieTransitionHeaders(
    await response.headersArray(),
    [{ name: FLOW_COOKIE, action: 'issue', maxAge: OTP_FLOW_TTL_SECONDS }],
    API,
  );
  return { response, status, startCookieTransitionExact: startCookieTransition.pass };
}

async function waitForSessionExpiry(ttlSeconds) {
  await new Promise((resolve) => setTimeout(resolve, (ttlSeconds * 1_000) + 1_500));
}

async function openPrivacySettings(page) {
  const settingsPromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/v1/student/settings'
  ));
  await page.goto(`${WEB}/s-19`, { waitUntil: 'domcontentloaded' });
  const settingsResponse = await settingsPromise;
  await page.locator('[data-screen="S-19"]').waitFor({ state: 'visible' });
  const disclosure = page.locator('details').filter({ hasText: 'Data rights' });
  await disclosure.evaluate((element) => { element.open = true; });
  await page.getByRole('button', { name: 'Delete…' }).waitFor({ state: 'visible' });
  return settingsResponse.status();
}

const nonce = createHash('sha256')
  .update(`${Date.now()}-${process.pid}-${Math.random()}`)
  .digest('hex');
const mobile = `8${nonce.split('').map((value) => Number.parseInt(value, 16) % 10).join('').slice(0, 9)}`;
const idempotencyKey = `nyay19-browser-${nonce}`;
rememberSecret(nonce);
rememberSecret(mobile);
rememberSecret(idempotencyKey);

let browser = null;
let currentStage = 'launch';
try {
  browser = await chromium.launch({ headless: true });

  currentStage = 'setup';
  const setup = await setupDisposableStudent(browser, mobile, idempotencyKey);
  record(
    'setup-disposable-student',
    'real PostgreSQL registration, OTP verification and logout complete without residual cookies',
    setup,
    setup.registrationHttp === 201
      && setup.verificationHttp === 200
      && setup.logoutHttp === 200
      && setup.cookiesRetired,
  );

  currentStage = 'login_a';
  const loginA = await loginWithBrowser(browser, mobile);
  const cookiesA = await loginA.context.cookies();
  const cookieInventoryA = inspectAuthorityCookieInventory(cookiesA, [SESSION_COOKIE], API);
  const sessionCookieA = cookiesA.find((cookie) => cookie.name === SESSION_COOKIE);
  const rawCookieA = sessionCookieA?.value ?? '';
  rememberSecret(rawCookieA);
  record(
    'login-a-authority-cookie',
    'browser login A succeeds with exactly one host-only opaque session cookie',
    {
      startHttp: loginA.startHttp,
      startFlowIssuanceExact: loginA.startCookieTransitionExact,
      verifyHttp: loginA.verifyHttp,
      issuanceAndFlowRetirementExact: loginA.loginCookieTransitionExact,
      cookieInventoryExact: cookieInventoryA.pass,
    },
    loginA.startHttp === 202
      && loginA.startCookieTransitionExact
      && loginA.verifyHttp === 200
      && loginA.loginCookieTransitionExact
      && cookieInventoryA.pass,
  );

  const beforeA = await seedStudentContext(loginA.page, loginA.actor);
  const seededA = inspectStudentContextBoundary(beforeA, {
    ...beforeA,
    managedPresentCount: 0,
    registrationAttemptPresent: false,
    profileDraftPresent: false,
    queryCacheCount: 0,
    mutationCacheCount: 0,
  });
  record(
    'actor-a-context-seeded',
    'actor-linked storage, memory stores and both TanStack caches are observably populated',
    {
      managedExpected: beforeA.managedExpectedCount,
      managedPresent: beforeA.managedPresentCount,
      memoryAndCachesSeeded: seededA.beforeExact,
      unrelatedControlsPresent: beforeA.controls.theme === 'dark'
        && beforeA.controls.locale === 'hi'
        && beforeA.controls.unrelated === 'retain',
    },
    seededA.beforeExact,
  );

  currentStage = 'rotation';
  const loginB = await loginWithBrowser(browser, mobile);
  const cookiesBInitial = await loginB.context.cookies();
  const cookieInventoryB = inspectAuthorityCookieInventory(
    cookiesBInitial,
    [SESSION_COOKIE],
    API,
  );
  const rotationCookieStillLive = hasFutureCookieExpiry(sessionCookieA, Date.now());
  const staleRotationProbes = await independentStaleAuthorityProbes(browser, rawCookieA);
  record(
    'rotation-b-invalidates-a',
    'login B rotates authority and a protected request carrying the stale A cookie is denied',
    {
      loginBStartHttp: loginB.startHttp,
      loginBStartFlowIssuanceExact: loginB.startCookieTransitionExact,
      loginBVerifyHttp: loginB.verifyHttp,
      loginBIssuanceExact: loginB.loginCookieTransitionExact,
      loginBCookieExact: cookieInventoryB.pass,
      rotationCookieStillLive,
      ambientAndBearerDeniedIndependently: staleRotationProbes.pass,
    },
    loginB.startHttp === 202
      && loginB.startCookieTransitionExact
      && loginB.verifyHttp === 200
      && loginB.loginCookieTransitionExact
      && cookieInventoryB.pass
      && rotationCookieStillLive
      && staleRotationProbes.pass,
  );

  const rotatedSession = await productStudentSession(loginA.page);
  const rotationRetirement = inspectCookieRetirementHeaders(
    await rotatedSession.response.headersArray(),
    [SESSION_COOKIE],
    API,
  );
  const afterA = await studentContextSnapshot(loginA.page, loginA.actor);
  const boundaryA = inspectStudentContextBoundary(beforeA, afterA);
  const emptyCookiesA = inspectAuthorityCookieInventory(
    await loginA.context.cookies(),
    [],
    API,
  );
  record(
    'rotation-a-retirement-and-clear',
    'A resolves anonymous, retires the stale cookie and clears actor A context while retaining controls',
    {
      anonymousSessionExact: exactAnonymousSession(rotatedSession.body) && rotatedSession.actor === null,
      retirementExact: rotationRetirement.pass,
      authorityCookiesAbsent: emptyCookiesA.pass,
      contextBoundaryExact: boundaryA.pass,
    },
    exactAnonymousSession(rotatedSession.body)
      && rotatedSession.actor === null
      && rotationRetirement.pass
      && emptyCookiesA.pass
      && boundaryA.pass,
  );

  currentStage = 'logout';
  const beforeB = await seedStudentContext(loginB.page, loginB.actor);
  await resetCapture();
  const recoveryForLogout = await startRecoveryFlowForLogout(loginB.page, mobile);
  await latestOtp(mobile);
  const cookiesBeforeLogout = await loginB.context.cookies();
  await rememberCookieValues(loginB.context);
  const sessionCookieB = cookiesBeforeLogout.find((cookie) => cookie.name === SESSION_COOKIE);
  const rawCookieB = sessionCookieB?.value ?? '';
  rememberSecret(rawCookieB);
  const twoCookieInventory = inspectAuthorityCookieInventory(
    cookiesBeforeLogout,
    [SESSION_COOKIE, FLOW_COOKIE],
    API,
  );
  const boundaryBSeeded = inspectStudentContextBoundary(beforeB, {
    ...beforeB,
    managedPresentCount: 0,
    registrationAttemptPresent: false,
    profileDraftPresent: false,
    queryCacheCount: 0,
    mutationCacheCount: 0,
  });
  record(
    'logout-precondition-two-cookies',
    'authenticated B has independently seeded context plus exactly session and flow cookies',
    {
      recoveryStartHttp: recoveryForLogout.status,
      recoveryStartFlowIssuanceExact: recoveryForLogout.startCookieTransitionExact,
      twoCookieInventoryExact: twoCookieInventory.pass,
      contextSeeded: boundaryBSeeded.beforeExact,
    },
    recoveryForLogout.status === 202
      && recoveryForLogout.startCookieTransitionExact
      && twoCookieInventory.pass
      && boundaryBSeeded.beforeExact,
  );

  const logoutResponsePromise = loginB.page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/logout'
  ));
  await loginB.page.getByRole('button', { name: 'Sign out' }).click();
  const logoutResponse = await logoutResponsePromise;
  await loginB.page.waitForURL('**/s-03');
  const logoutRetirement = inspectCookieRetirementHeaders(
    await logoutResponse.headersArray(),
    [SESSION_COOKIE, FLOW_COOKIE],
    API,
  );
  const emptyCookiesB = inspectAuthorityCookieInventory(
    await loginB.context.cookies(),
    [],
    API,
  );
  const logoutStaleProbes = await independentStaleAuthorityProbes(browser, rawCookieB);
  const logoutCookieStillLive = hasFutureCookieExpiry(sessionCookieB, Date.now());
  record(
    'logout-cookie-retirement',
    'logout retires both cookies and revokes the pre-logout session over independent ambient and bearer channels',
    {
      httpStatus: logoutResponse.status(),
      retirementExact: logoutRetirement.pass,
      authorityCookiesAbsent: emptyCookiesB.pass,
      ambientAndBearerDeniedIndependently: logoutStaleProbes.pass,
      logoutCookieStillLive,
    },
    logoutResponse.status() === 200
      && logoutRetirement.pass
      && emptyCookiesB.pass
      && logoutStaleProbes.pass
      && logoutCookieStillLive,
  );

  const afterB = await studentContextSnapshot(loginB.page, loginB.actor);
  const boundaryB = inspectStudentContextBoundary(beforeB, afterB);
  record(
    'logout-context-clear',
    'logout clears storage, registration/profile memory and query/mutation caches while controls survive',
    {
      contextBoundaryExact: boundaryB.pass,
      signedOutScreenVisible: await loginB.page.locator('[data-screen="S-03"]').isVisible(),
    },
    boundaryB.pass && await loginB.page.locator('[data-screen="S-03"]').isVisible(),
  );

  currentStage = 'expiry_login';
  const loginExpiry = await loginWithBrowser(browser, mobile);
  const cookiesExpiry = await loginExpiry.context.cookies();
  const expiryCookieInventory = inspectAuthorityCookieInventory(
    cookiesExpiry,
    [SESSION_COOKIE],
    API,
  );
  const beforeExpiry = await seedStudentContext(loginExpiry.page, loginExpiry.actor);
  const boundaryExpirySeeded = inspectStudentContextBoundary(beforeExpiry, {
    ...beforeExpiry,
    managedPresentCount: 0,
    registrationAttemptPresent: false,
    profileDraftPresent: false,
    queryCacheCount: 0,
    mutationCacheCount: 0,
  });
  record(
    'expiry-login-and-context-seed',
    'fresh expiry actor starts with exact session authority and populated private browser context',
    {
      loginHttpExact: loginExpiry.startHttp === 202 && loginExpiry.verifyHttp === 200,
      startFlowIssuanceExact: loginExpiry.startCookieTransitionExact,
      issuanceAndFlowRetirementExact: loginExpiry.loginCookieTransitionExact,
      cookieInventoryExact: expiryCookieInventory.pass,
      contextSeeded: boundaryExpirySeeded.beforeExact,
    },
    loginExpiry.startHttp === 202
      && loginExpiry.startCookieTransitionExact
      && loginExpiry.verifyHttp === 200
      && loginExpiry.loginCookieTransitionExact
      && expiryCookieInventory.pass
      && boundaryExpirySeeded.beforeExact,
  );

  const rawExpiryCookie = cookiesExpiry
    .find((cookie) => cookie.name === SESSION_COOKIE)?.value ?? '';
  rememberSecret(rawExpiryCookie);
  currentStage = 'expiry_wait';
  await waitForSessionExpiry(SESSION_TTL_SECONDS);
  // Destroy the actor-bearing JS realm before session discovery. The new page
  // can clear dynamic report/reminder keys only through the persisted exact-key
  // registry, proving expiry cleanup survives a real reload boundary.
  await loginExpiry.page.close();
  const expiryRestartPage = await openProtectedProbePage(loginExpiry.context);
  const expiredSession = await productStudentSession(expiryRestartPage);
  const naturalExpiryHeaders = await expiredSession.response.headersArray();
  const naturalExpirySetCookieCount = naturalExpiryHeaders.filter((header) => (
    header?.name?.toLowerCase() === 'set-cookie'
  )).length;
  const emptyExpiryCookies = inspectAuthorityCookieInventory(
    await loginExpiry.context.cookies(),
    [],
    API,
  );
  currentStage = 'expiry_stale_probe';
  const staleExpiryProbe = await staleCookieSessionProbe(browser, rawExpiryCookie);
  const staleExpiryAuthorityProbes = await independentStaleAuthorityProbes(
    browser,
    rawExpiryCookie,
  );
  record(
    'expiry-anonymous-and-retirement',
    'natural client expiry is anonymous without a retirement header; a re-injected stale cookie is anonymously retired',
    {
      anonymousSessionExact: exactAnonymousSession(expiredSession.body) && expiredSession.actor === null,
      naturalClientExpiryHasNoRetirement: naturalExpirySetCookieCount === 0,
      authorityCookiesAbsent: emptyExpiryCookies.pass,
      staleCookieAnonymous: staleExpiryProbe.anonymousExact,
      staleCookieRetirementExact: staleExpiryProbe.retirementExact,
      staleCookieRetirementHeaderCount: staleExpiryProbe.retirementHeaderCount,
      staleCookieRetirementNamesExact: staleExpiryProbe.retirementNamesExact,
      staleCookieRetirementComponents: staleExpiryProbe.retirementComponents,
      correlatedStaleCookieExact: staleExpiryProbe.correlatedStaleCookieExact,
      staleCookieAbsentAfterProbe: staleExpiryProbe.authorityCookieAbsent,
      ambientAndBearerDeniedIndependently: staleExpiryAuthorityProbes.pass,
    },
    exactAnonymousSession(expiredSession.body)
      && expiredSession.actor === null
      && naturalExpirySetCookieCount === 0
      && emptyExpiryCookies.pass
      && staleExpiryProbe.anonymousExact
      && staleExpiryProbe.retirementExact
      && staleExpiryProbe.correlatedStaleCookieExact
      && staleExpiryProbe.authorityCookieAbsent
      && staleExpiryAuthorityProbes.pass,
  );

  currentStage = 'expiry_context';
  const afterExpiry = await studentContextSnapshot(expiryRestartPage, loginExpiry.actor);
  const boundaryExpiry = inspectStudentContextBoundary(beforeExpiry, afterExpiry);
  record(
    'expiry-context-clear',
    'anonymous session resolution clears all private browser context while preserving theme, locale and control',
    { contextBoundaryExact: boundaryExpiry.pass },
    boundaryExpiry.pass,
  );

  currentStage = 'deletion_login';
  const loginDelete = await loginWithBrowser(browser, mobile);
  const settingsHttp = await openPrivacySettings(loginDelete.page);
  const sessionDelete = await productStudentSession(loginDelete.page);
  if (!hasExactAuthenticatedStudentSession(sessionDelete.body, sessionDelete.actor)) {
    throw new Error('NYAY19_DELETE_ACTOR_INVALID');
  }
  const beforeDelete = await seedStudentContext(loginDelete.page, loginDelete.actor);
  const deleteCookieInventory = inspectAuthorityCookieInventory(
    await loginDelete.context.cookies(),
    [SESSION_COOKIE],
    API,
  );
  const boundaryDeleteSeeded = inspectStudentContextBoundary(beforeDelete, {
    ...beforeDelete,
    managedPresentCount: 0,
    registrationAttemptPresent: false,
    profileDraftPresent: false,
    queryCacheCount: 0,
    mutationCacheCount: 0,
  });
  record(
    'deletion-login-and-context-seed',
    'fresh deletion actor loads protected settings with exact session authority and populated context',
    {
      loginHttpExact: loginDelete.startHttp === 202 && loginDelete.verifyHttp === 200,
      startFlowIssuanceExact: loginDelete.startCookieTransitionExact,
      issuanceAndFlowRetirementExact: loginDelete.loginCookieTransitionExact,
      settingsHttp,
      cookieInventoryExact: deleteCookieInventory.pass,
      contextSeeded: boundaryDeleteSeeded.beforeExact,
    },
    loginDelete.startHttp === 202
      && loginDelete.startCookieTransitionExact
      && loginDelete.verifyHttp === 200
      && loginDelete.loginCookieTransitionExact
      && settingsHttp === 200
      && deleteCookieInventory.pass
      && boundaryDeleteSeeded.beforeExact,
  );

  currentStage = 'deletion_reauth';
  await loginDelete.page.getByRole('button', { name: 'Delete…' }).click();
  await loginDelete.page.getByLabel('Registered mobile number').fill(mobile);
  await resetCapture();
  const recoveryStartPromise = loginDelete.page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/recovery/start'
  ));
  await loginDelete.page.getByRole('button', { name: 'Send code' }).click();
  const recoveryStart = await recoveryStartPromise;
  const recoveryStartTransition = inspectCookieTransitionHeaders(
    await recoveryStart.headersArray(),
    [{ name: FLOW_COOKIE, action: 'issue', maxAge: OTP_FLOW_TTL_SECONDS }],
    API,
  );
  const recoveryCode = await latestOtp(mobile);
  const recoveryVerifyPromise = loginDelete.page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/auth/student/recovery/verify'
  ));
  await loginDelete.page.getByLabel('One-time code').fill(recoveryCode);
  await loginDelete.page.getByRole('button', { name: 'Verify code' }).click();
  const recoveryVerify = await recoveryVerifyPromise;
  const recoveryVerifyTransition = inspectCookieTransitionHeaders(
    await recoveryVerify.headersArray(),
    [{ name: FLOW_COOKIE, action: 'issue', maxAge: RECOVERY_PROOF_TTL_SECONDS }],
    API,
  );
  await loginDelete.page.getByLabel('Type DELETE to confirm').waitFor({ state: 'visible' });
  const beforeDeleteCookies = await loginDelete.context.cookies();
  await rememberCookieValues(loginDelete.context);
  const preDeletionSessionCookie = beforeDeleteCookies
    .find((cookie) => cookie.name === SESSION_COOKIE);
  const rawDeleteCookie = preDeletionSessionCookie?.value ?? '';
  rememberSecret(rawDeleteCookie);
  const deletionTwoCookieInventory = inspectAuthorityCookieInventory(
    beforeDeleteCookies,
    [SESSION_COOKIE, FLOW_COOKIE],
    API,
  );
  record(
    'deletion-reauth-authority',
    'real recovery start and verify retain exactly session plus verified flow authority before deletion',
    {
      startHttp: recoveryStart.status(),
      startFlowIssuanceExact: recoveryStartTransition.pass,
      verifyHttp: recoveryVerify.status(),
      verifiedFlowIssuanceExact: recoveryVerifyTransition.pass,
      twoCookieInventoryExact: deletionTwoCookieInventory.pass,
      confirmationVisible: await loginDelete.page.getByLabel('Type DELETE to confirm').isVisible(),
    },
    recoveryStart.status() === 202
      && recoveryStartTransition.pass
      && recoveryVerify.status() === 200
      && recoveryVerifyTransition.pass
      && deletionTwoCookieInventory.pass
      && await loginDelete.page.getByLabel('Type DELETE to confirm').isVisible(),
  );

  currentStage = 'deletion_submit';
  await loginDelete.page.getByLabel('Type DELETE to confirm').fill('DELETE');
  const deletionResponsePromise = loginDelete.page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v1/student/privacy/delete'
  ));
  await loginDelete.page.getByRole('button', { name: 'Delete my account' }).click();
  const deletionResponse = await deletionResponsePromise;
  await loginDelete.page.waitForURL('**/s-03');
  await loginDelete.page.getByText('DELETION REQUEST ACCEPTED', { exact: true })
    .waitFor({ state: 'visible' });
  const deletionRetirement = inspectCookieRetirementHeaders(
    await deletionResponse.headersArray(),
    [SESSION_COOKIE, FLOW_COOKIE],
    API,
  );
  const emptyDeleteCookies = inspectAuthorityCookieInventory(
    await loginDelete.context.cookies(),
    [],
    API,
  );
  record(
    'deletion-cookie-retirement-and-ack',
    'accepted deletion retires both cookies with exact attributes and lands on the signed-out acknowledgement',
    {
      httpStatus: deletionResponse.status(),
      retirementExact: deletionRetirement.pass,
      authorityCookiesAbsent: emptyDeleteCookies.pass,
      acknowledgementVisible: true,
    },
    deletionResponse.status() === 202
      && deletionRetirement.pass
      && emptyDeleteCookies.pass,
  );

  const afterDelete = await studentContextSnapshot(loginDelete.page, loginDelete.actor);
  const boundaryDelete = inspectStudentContextBoundary(beforeDelete, afterDelete);
  record(
    'deletion-context-clear',
    'accepted deletion clears storage, memory and both caches while retaining unrelated controls',
    { contextBoundaryExact: boundaryDelete.pass },
    boundaryDelete.pass,
  );

  currentStage = 'deletion_stale_probe';
  const staleDeletionProbes = await independentStaleAuthorityProbes(browser, rawDeleteCookie);
  const deletionCookieStillLive = hasFutureCookieExpiry(
    preDeletionSessionCookie,
    Date.now(),
  );
  record(
    'deletion-stale-cookie-denied',
    'independent ambient-cookie-only and bearer-only protected requests deny the pre-deletion authority',
    {
      ambientAndBearerDeniedIndependently: staleDeletionProbes.pass,
      deletionCookieStillLive,
    },
    staleDeletionProbes.pass && deletionCookieStillLive,
  );

  currentStage = 'trace';
  const mutationTraceInspection = await inspectExactOrderedMutationTrace(
    mutationTrace,
    NYAY19_MUTATION_TRACE,
    WEB_ORIGIN,
    API_ORIGIN,
  );
  const mutationTraceExact = mutationTraceInspection.pass;
  record(
    'browser-mutation-trace',
    'all page POSTs have exact API target, raw Origin, method, body shape, order and cardinality',
    {
      expectedCount: NYAY19_MUTATION_TRACE.length,
      observedCount: mutationTrace.length,
      exactCardinality: mutationTraceInspection.exactCardinality,
      inspectionReadable: mutationTraceInspection.inspectionReadable,
      failingSlots: mutationTraceInspection.failingSlots,
      components: mutationTraceInspection.components,
      traceExact: mutationTraceExact,
    },
    mutationTraceExact,
  );

  currentStage = 'finality';
  const finalCookieInventories = await Promise.all([
    loginA.context.cookies(),
    loginB.context.cookies(),
    loginExpiry.context.cookies(),
    loginDelete.context.cookies(),
  ]);
  const allAuthorityRetired = finalCookieInventories.every((cookies) => (
    inspectAuthorityCookieInventory(cookies, [], API).pass
  ));
  await Promise.all([
    loginA.context.close(),
    loginB.context.close(),
    loginExpiry.context.close(),
    loginDelete.context.close(),
  ]);
  const lifecycleContextsClosed = true;
  const captureProviderCleared = await clearCaptureEvidence();
  const proposedFinalRow = {
    name: 'evidence-privacy-and-finality',
    expected: 'aggregate-only evidence contains no raw secret, contact, OTP, PII or identifier and every lifecycle context closes cleanly',
    actual: {
      evidencePrivacyExact: true,
      allAuthorityCookiesRetired: allAuthorityRetired,
      lifecycleContextsClosed,
      captureResetExact: captureProviderCleared.resetExact,
      captureEmptyReadCount: captureProviderCleared.emptyReadCount,
      captureSettledEmptyTwice: captureProviderCleared.settledEmptyTwice,
    },
    pass: allAuthorityRetired && lifecycleContextsClosed && captureProviderCleared.pass,
  };
  const evidencePrivacyExact = scanNyay19Evidence(
    [...rows, proposedFinalRow],
    [...forbiddenEvidenceValues],
  );
  record(
    'evidence-privacy-and-finality',
    proposedFinalRow.expected,
    {
      evidencePrivacyExact,
      allAuthorityCookiesRetired: allAuthorityRetired,
      lifecycleContextsClosed,
      captureResetExact: captureProviderCleared.resetExact,
      captureEmptyReadCount: captureProviderCleared.emptyReadCount,
      captureSettledEmptyTwice: captureProviderCleared.settledEmptyTwice,
    },
    evidencePrivacyExact
      && allAuthorityRetired
      && lifecycleContextsClosed
      && captureProviderCleared.pass,
  );

  currentStage = 'summary';
  const summary = summarizeNyay19Rows(rows);
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
  if (summary.failed > 0) process.exitCode = 1;
} catch (error) {
  const candidateAbortEnvelope = buildNyay19AbortEnvelope(currentStage, error, rows.length);
  const abortEnvelope = scanNyay19Evidence(
    candidateAbortEnvelope,
    [...forbiddenEvidenceValues],
  )
    ? candidateAbortEnvelope
    : buildNyay19AbortEnvelope('unknown', new Error(), 0);
  process.stderr.write(`${JSON.stringify(abortEnvelope)}\n`);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
}
