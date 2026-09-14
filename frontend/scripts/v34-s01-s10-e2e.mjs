import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { chromium } from 'playwright';
import { runS04PendingSubmitBrowser } from './lib/s04-pending-submit-browser.mjs';

const base = process.env.V34_BASE_URL ?? 'http://127.0.0.1:4174';
const apiBase = process.env.V34_API_BASE_URL ?? base;
const webOrigin = new URL(base).origin;
const captureBase = process.env.V34_OTP_CAPTURE_URL ?? 'http://127.0.0.1:1099';
const loginMobile = process.env.V34_LOGIN_MOBILE ?? '9000000042';
const evidenceDir = resolve(process.env.V34_EVIDENCE_DIR ?? 'test-results/v34-s01-s10');
const screenshotsDir = resolve(evidenceDir, 'screenshots');
await mkdir(screenshotsDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const rows = [];
const record = (area, expected, actual, pass, detail = '') => rows.push({ area, expected, actual, pass, detail });
const resetOtp = async () => {
  const response = await fetch(`${captureBase}/reset`, { method: 'POST' });
  if (!response.ok) throw new Error(`OTP capture reset failed: ${response.status}`);
};
const latestOtp = async () => {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const response = await fetch(`${captureBase}/latest`);
    const payload = await response.json();
    if (payload.to === loginMobile && /^\d{6}$/.test(payload.code ?? '')) return payload.code;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 100));
  }
  throw new Error('OTP capture did not receive the expected login code');
};
const provisionLoginStudent = async () => {
  await resetOtp();
  const fixtureContext = await browser.newContext();
  const response = await fixtureContext.request.post(`${apiBase}/api/v1/auth/student/register`, {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': `v34-login-e2e-${loginMobile}`,
      Origin: webOrigin,
    },
    data: {
      first_name: 'Aditi',
      middle_name: null,
      last_name: 'Nair',
      mobile: loginMobile,
      dob: '2004-03-14',
      terms_accepted: true,
      terms_version: 'dpdp-2023.v1',
      privacy_notice_acknowledged: true,
      privacy_notice_version: 'dpdp-2023.v1',
    },
  });
  if (response.status() !== 202) throw new Error(`login fixture registration failed: ${response.status()}`);
  const code = await latestOtp();
  const verified = await fixtureContext.request.post(`${apiBase}/api/v1/auth/student/otp/verify`, {
    headers: { 'Content-Type': 'application/json', Origin: webOrigin },
    data: { code },
  });
  if (!verified.ok()) throw new Error(`login fixture OTP verification failed: ${verified.status()}`);
  const session = await fixtureContext.request.get(`${apiBase}/api/v1/auth/student/session`);
  const sessionBody = session.ok() ? await session.json() : null;
  const cookies = await fixtureContext.cookies(`${apiBase}/api/v1/auth/student/session`);
  if (
    sessionBody?.authenticated !== true
    || !sessionBody?.actor?.roles?.includes('student')
    || !cookies.some((cookie) => cookie.httpOnly && cookie.value)
  ) throw new Error('login fixture did not establish a canonical student session');
  await fixtureContext.close();
  return cookies;
};
const requirePendingFlowCookies = async (fixtureContext, purpose) => {
  const stateResponse = await fixtureContext.request.get(`${apiBase}/api/v1/auth/student/otp/state`, {
    headers: { Origin: webOrigin },
  });
  const stateBody = stateResponse.ok() ? await stateResponse.json() : null;
  const cookies = await fixtureContext.cookies(`${apiBase}/api/v1/auth/student/otp/state`);
  const flowCookies = cookies.filter((cookie) => cookie.name === 'nyayone_otp_flow');
  if (
    stateResponse.status() !== 200
    || stateBody?.status !== 'pending'
    || stateBody?.purpose !== purpose
    || flowCookies.length !== 1
    || !flowCookies[0].httpOnly
  ) throw new Error(`visual ${purpose} fixture did not establish a server-owned pending flow`);
  return flowCookies;
};
const provisionVisualOtpFlows = async () => {
  const loginContext = await browser.newContext();
  const loginResponse = await loginContext.request.post(`${apiBase}/api/v1/auth/student/login/otp/start`, {
    headers: { 'Content-Type': 'application/json', Origin: webOrigin },
    data: { mobile: loginMobile },
  });
  if (loginResponse.status() !== 202) throw new Error(`visual login flow failed: ${loginResponse.status()}`);
  const login = await requirePendingFlowCookies(loginContext, 'login');
  await loginContext.close();

  const signupMobile = process.env.V34_VISUAL_SIGNUP_MOBILE ?? '9000000043';
  const signupContext = await browser.newContext();
  const signupResponse = await signupContext.request.post(`${apiBase}/api/v1/auth/student/register`, {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': `v34-visual-signup-${signupMobile}`,
      Origin: webOrigin,
    },
    data: {
      first_name: 'Visual',
      middle_name: null,
      last_name: 'Fixture',
      mobile: signupMobile,
      dob: '2004-03-14',
      terms_accepted: true,
      terms_version: 'dpdp-2023.v1',
      privacy_notice_acknowledged: true,
      privacy_notice_version: 'dpdp-2023.v1',
    },
  });
  if (signupResponse.status() !== 202) throw new Error(`visual signup flow failed: ${signupResponse.status()}`);
  const signup = await requirePendingFlowCookies(signupContext, 'signup');
  await signupContext.close();
  return { login, signup };
};
const createPendingVisualContext = async (viewport, theme, flowCookies) => {
  const isolated = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    colorScheme: theme,
  });
  await isolated.addInitScript(
    ({ themeValue }) => localStorage.setItem('nyayone.theme.v1', themeValue),
    { themeValue: theme },
  );
  await isolated.addCookies(flowCookies);
  const installedCookies = await isolated.cookies(`${apiBase}/api/v1/auth/student/otp/state`);
  if (
    installedCookies.some((cookie) => cookie.name === 'nyayone_session')
    || installedCookies.length !== 1
    || installedCookies[0]?.name !== 'nyayone_otp_flow'
  ) {
    await isolated.close();
    throw new Error('visual OTP context mixed session and pending-flow authority');
  }
  return isolated;
};

try {
  const authenticatedCookies = await provisionLoginStudent();
  const visualOtpFlowCookies = await provisionVisualOtpFlows();
  for (const viewport of [{ name: 'mobile', width: 390, height: 844 }, { name: 'desktop', width: 1440, height: 900 }]) {
    for (const theme of ['light', 'dark']) {
      const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, colorScheme: theme });
      await context.addCookies(authenticatedCookies);
      await context.addInitScript(({ themeValue }) => localStorage.setItem('nyayone.theme.v1', themeValue), { themeValue: theme });
      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
      page.on('pageerror', (error) => pageErrors.push(error.message));

      for (let number = 1; number <= 10; number += 1) {
        const id = `S-${String(number).padStart(2, '0')}`;
        const path = `/s-${String(number).padStart(2, '0')}`;
        const pendingFlowCookies = number === 5 ? visualOtpFlowCookies.login
          : number === 9 ? visualOtpFlowCookies.signup
            : null;
        const screenContext = pendingFlowCookies
          ? await createPendingVisualContext(viewport, theme, pendingFlowCookies)
          : context;
        const screenPage = pendingFlowCookies ? await screenContext.newPage() : page;
        if (pendingFlowCookies) {
          screenPage.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
          screenPage.on('pageerror', (error) => pageErrors.push(error.message));
        }
        let otpStateRequestCount = 0;
        screenPage.on('request', (request) => {
          const requestUrl = new URL(request.url());
          if (
            pendingFlowCookies
            && request.method() === 'GET'
            && requestUrl.origin === new URL(apiBase).origin
            && requestUrl.pathname === '/api/v1/auth/student/otp/state'
          ) otpStateRequestCount += 1;
        });
        await screenPage.goto(`${base}${path}`, { waitUntil: 'domcontentloaded' });
        const feature = screenPage.locator(`[data-screen="${id}"]`);
        await feature.waitFor({ state: 'visible' });
        if (pendingFlowCookies) {
          await screenPage.getByLabel('Six digit code').waitFor({ state: 'visible' });
          if (!await feature.isVisible()) {
            await screenContext.close();
            throw new Error(`visual ${id} left its server-pending screen before capture`);
          }
        }
        if (pendingFlowCookies && otpStateRequestCount < 1) {
          await screenContext.close();
          throw new Error(`visual ${id} cold load did not request server OTP state`);
        }
        const geometry = await screenPage.evaluate(({ allowDesktopLegalTextLinks }) => {
          const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const smallTargets = [...document.querySelectorAll('button,input,select,a[href]')]
            .filter((element) => visible(element)
              && !element.closest('.v34-actions__hint')
              && !(allowDesktopLegalTextLinks && element.matches('.v321-legal a')))
            .map((element) => {
              const rect = element.getBoundingClientRect();
              return { name: element.getAttribute('aria-label') || element.textContent?.trim() || element.id, width: rect.width, height: rect.height };
            })
            .filter((target) => target.width < 44 || target.height < 44);
          return {
            horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            legacyShells: document.querySelectorAll('.ls-rail,.ls-topbar,.ls-bnav').length,
            smallTargets,
          };
        }, { allowDesktopLegalTextLinks: viewport.name === 'desktop' });
        record(`${id}_${viewport.name}_${theme}_overflow`, '0 horizontal px', geometry.horizontalOverflow, geometry.horizontalOverflow === 0);
        record(`${id}_${viewport.name}_${theme}_shell`, '0 legacy shell nodes', geometry.legacyShells, geometry.legacyShells === 0);
        record(`${id}_${viewport.name}_${theme}_targets`, 'all visible targets >=44x44', geometry.smallTargets, geometry.smallTargets.length === 0);
        await screenPage.screenshot({ path: resolve(screenshotsDir, `${id}__${viewport.name}__${theme}.png`), fullPage: true });
        if (pendingFlowCookies) await screenContext.close();
      }
      record(`${viewport.name}_${theme}_runtime`, '0 console/page errors', { consoleErrors, pageErrors }, consoleErrors.length === 0 && pageErrors.length === 0);
      await context.close();
    }
  }

  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  let capturedPayload = null;
  await page.route('**/api/v1/auth/student/register', async (route) => {
    capturedPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'accepted', next: 'otp', expires_in_seconds: 300, resend_after_seconds: 30,
      }),
    });
  });

  const loadRegistration = async () => {
    await page.goto(`${base}/s-08`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Create your student account' }).waitFor();
  };
  const fillRequired = async ({ first = 'Rajeev', last = 'Barnwal', mobile = '9876543210', dob = '2000-01-01' } = {}) => {
    await page.getByLabel('FIRST NAME').fill(first);
    await page.getByLabel('LAST NAME').fill(last);
    await page.locator('#v34-mobile').fill(mobile);
    await page.locator('#v34-dob').fill(dob);
    await page.getByRole('checkbox', { name: 'I accept the Terms.', exact: true }).check();
    await page.getByRole('checkbox', { name: 'I acknowledge the Privacy Notice.', exact: true }).check();
  };
  const submit = () => page.getByRole('button', { name: 'Send one time code' }).click();

  await loadRegistration();
  await fillRequired({ mobile: '123456789' });
  await submit();
  const mobile9Error = await page.locator('#v34-mobile-error').textContent();
  record('mobile_9_digits', 'typed exact-length error and remain S-08', mobile9Error,
    await page.locator('#v34-mobile-error').isVisible()
      && mobile9Error === 'Mobile number must be exactly 10 digits.'
      && new URL(page.url()).pathname === '/s-08');

  await loadRegistration();
  await fillRequired({ mobile: '12345678901' });
  await submit();
  const mobile11Error = await page.locator('#v34-mobile-error').textContent();
  record('mobile_11_digits', 'typed exact-length error and remain S-08', mobile11Error,
    await page.locator('#v34-mobile-error').isVisible()
      && mobile11Error === 'Mobile number must be exactly 10 digits.'
      && new URL(page.url()).pathname === '/s-08');

  await loadRegistration();
  await fillRequired({ dob: '2030-01-01' });
  await submit();
  const futureDobError = await page.locator('#v34-dob-error').textContent();
  record('future_dob', 'future date rejected with clear error', futureDobError,
    await page.locator('#v34-dob-error').isVisible()
      && futureDobError === 'Enter a valid date of birth that is not in the future.');

  await loadRegistration();
  await fillRequired({ first: 'Rajeev!', last: 'Barnwal1' });
  await submit();
  const specialFieldErrors = {
    first: await page.locator('#v34-first-error').textContent(),
    last: await page.locator('#v34-last-error').textContent(),
  };
  record(
    'special_name_characters',
    'first and last names rejected',
    specialFieldErrors,
    await page.locator('#v34-first-error').isVisible()
      && await page.locator('#v34-last-error').isVisible()
      && Object.values(specialFieldErrors).every((text) => /characters that aren't allowed/i.test(text ?? '')),
  );

  await loadRegistration();
  await submit();
  const requiredErrorSelectors = [
    '#v34-first-error',
    '#v34-last-error',
    '#v34-mobile-error',
    '#v34-dob-error',
    '#v34-terms-error',
    '#v34-privacy-error',
  ];
  const requiredErrorsVisible = await Promise.all(
    requiredErrorSelectors.map((selector) => page.locator(selector).isVisible()),
  );
  record(
    'empty_required_fields',
    'all six required identity and legal-consent errors are visible',
    { requiredErrorSelectors, requiredErrorsVisible },
    requiredErrorsVisible.every(Boolean),
  );

  await loadRegistration();
  const sixty = 'A'.repeat(60);
  await fillRequired({ first: sixty, last: sixty });
  await submit();
  await page.waitForURL('**/s-09');
  record('name_60_boundary', '60 characters accepted', { firstLength: capturedPayload?.first_name?.length, lastLength: capturedPayload?.last_name?.length }, capturedPayload?.first_name?.length === 60 && capturedPayload?.last_name?.length === 60);
  const splitNamePayloadValid = capturedPayload?.first_name === sixty
    && capturedPayload?.middle_name === null
    && capturedPayload?.last_name === sixty;
  record('split_name_payload', 'first/middle/last mapped independently', {
    valid: splitNamePayloadValid,
    fieldKeys: Object.keys(capturedPayload ?? {}).sort(),
    firstLength: capturedPayload?.first_name?.length ?? 0,
    middleIsNull: capturedPayload?.middle_name === null,
    lastLength: capturedPayload?.last_name?.length ?? 0,
  }, splitNamePayloadValid);

  await loadRegistration();
  await fillRequired({ first: 'B'.repeat(61) });
  const maxLengthActual = await page.getByLabel('FIRST NAME').inputValue();
  await submit();
  const name61Error = await page.locator('#v34-first-error').textContent();
  record('name_61_boundary', '61 characters retained, rejected, and remain S-08', {
    length: maxLengthActual.length,
    error: name61Error,
    path: new URL(page.url()).pathname,
  }, maxLengthActual.length === 61
    && await page.locator('#v34-first-error').isVisible()
    && name61Error === 'First name must be 60 characters or fewer.'
    && new URL(page.url()).pathname === '/s-08');

  const currentSelectors = {
    'FIRST NAME': '#v34-first',
    'MIDDLE NAME': '#v34-middle',
    'LAST NAME': '#v34-last',
    'MOBILE NUMBER': '#v34-mobile',
    'DATE OF BIRTH': '#v34-dob',
    'TERMS': '#v34-terms',
    'PRIVACY NOTICE': '#v34-privacy',
  };
  const currentFieldCounts = Object.fromEntries(await Promise.all(
    Object.entries(currentSelectors).map(async ([label, selector]) => [label, await page.locator(selector).count()]),
  ));
  const retiredFieldCount = await page.locator('#v34-email,#v34-college,#v34-year,#v34-bar').count();
  record(
    'legacy_schema_parity',
    'one core identity/control instance each and zero retired academic fields on S-08',
    { currentFieldCounts, retiredFieldCount },
    Object.values(currentFieldCounts).every((count) => count === 1) && retiredFieldCount === 0,
  );

  await page.goto(`${base}/s-08`);
  const iconActions = page.getByRole('button', { name: 'Send one time code', exact: true });
  const iconContract = await iconActions.evaluateAll((buttons) => buttons.map((button) => ({ aria: button.getAttribute('aria-label'), tip: button.getAttribute('data-tip'), svg: button.querySelectorAll('svg').length })));
  record('icon_tooltip_contract', 'every icon CTA has SVG, aria-label and visible-tooltip text', iconContract, iconContract.length > 0 && iconContract.every((item) => item.aria && item.tip === item.aria && item.svg === 1));

  await resetOtp();
  const loginCalls = [];
  let cancelRequest = null;
  let markCancelObserved;
  const cancelObserved = new Promise((resolvePromise) => { markCancelObserved = resolvePromise; });
  let releaseCancelResponse;
  const cancelResponseReleased = new Promise((resolvePromise) => { releaseCancelResponse = resolvePromise; });
  await page.route('**/api/v1/auth/student/otp/cancel', async (route) => {
    cancelRequest = {
      method: route.request().method(),
      body: route.request().postDataJSON(),
    };
    const upstream = await route.fetch();
    markCancelObserved({ status: upstream.status() });
    await cancelResponseReleased;
    await route.fulfill({ response: upstream });
  });
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/auth/student/')) {
      loginCalls.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
  });
  await page.goto(`${base}/s-04`);
  await page.locator('#v34-login-mobile').fill(loginMobile);
  await page.getByRole('button', { name: 'Send Code', exact: true }).click();
  await page.waitForURL('**/s-05');
  const cancelledCode = await latestOtp();
  // A same-identity restart remains subject to the server's issue floor even
  // after explicit cancellation. Observe the product's authoritative poll
  // projection rather than sleeping for a runner-dependent duration.
  const restartFloorHandle = await page.waitForFunction(() => {
    const button = [...document.querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === 'Resend Code',
    );
    const resendRow = [...document.querySelectorAll('.v34-kv span')].find(
      (candidate) => candidate.textContent?.includes('Resend in'),
    );
    return button instanceof HTMLButtonElement
      && button.disabled === false
      && resendRow?.textContent?.replace(/\s+/gu, ' ').trim() === 'Resend in 00:00';
  });
  const restartFloorReady = await restartFloorHandle.jsonValue();
  const capturedFlowCookie = (await context.cookies(`${apiBase}/api/v1/auth/student/otp/state`))
    .find((cookie) => cookie.name === 'nyayone_otp_flow');
  if (!capturedFlowCookie) throw new Error('login cancellation fixture did not expose its HttpOnly flow cookie to Playwright');
  await page.getByRole('button', { name: 'Change persona', exact: true }).click();
  const cancelUpstream = await cancelObserved;
  const pathWhileCancelResponseDeferred = new URL(page.url()).pathname;
  releaseCancelResponse();
  await page.waitForURL('**/s-03');
  const pathAfterCancel = new URL(page.url()).pathname;
  await page.unroute('**/api/v1/auth/student/otp/cancel');

  const cancelledVerifyContext = await browser.newContext();
  await cancelledVerifyContext.addCookies([capturedFlowCookie]);
  const cancelledVerify = await cancelledVerifyContext.request.post(`${apiBase}/api/v1/auth/student/login/otp/verify`, {
    headers: { 'Content-Type': 'application/json', Origin: webOrigin },
    data: { code: cancelledCode },
  });
  const cancelledVerifyBody = await cancelledVerify.json();
  await cancelledVerifyContext.close();

  await resetOtp();
  await page.getByRole('button', { name: 'Sign In Securely', exact: true }).click();
  await page.waitForURL('**/s-04');
  await page.locator('#v34-login-mobile').fill(loginMobile);
  await page.getByRole('button', { name: 'Send Code', exact: true }).click();
  await page.waitForURL('**/s-05');
  const loginCode = await latestOtp();
  await page.getByLabel('Six digit code').fill(loginCode);
  await page.getByRole('button', { name: 'Verify and continue' }).click();
  await page.waitForURL('**/s-07');
  const authenticated = await page.evaluate(async (sessionUrl) => {
    const response = await fetch(sessionUrl, { credentials: 'include' });
    return { status: response.status, body: await response.json() };
  }, `${apiBase}/api/v1/auth/student/session`);
  const loginBrowserState = await page.evaluate(({ mobile, otp }) => {
    const registrationKey = 'legalsaathi.student.registration.v2';
    const allowedLocalKeys = new Set(['nyayone.theme.v1']);
    const allowedSessionKeys = new Set();
    const forbiddenKey = /(?:access[_-]?token|auth[_-]?token|session[_-]?token|onboarding[_-]?(?:token|capability)|authorization|bearer|password|otp|secret)/i;
    const credentialValue = /(?:\bBearer\s+[A-Za-z0-9._~-]{12,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|\b[A-Za-z0-9_-]{48,}\b)/;
    const local = Object.fromEntries(Object.keys(localStorage).map((key) => [key, localStorage.getItem(key)]));
    const session = Object.fromEntries(Object.keys(sessionStorage).map((key) => [key, sessionStorage.getItem(key)]));
    const serialized = JSON.stringify({ local, session, cookie: document.cookie });
    const visibleCookieNames = document.cookie
      .split(';')
      .map((entry) => entry.trim().split('=', 1)[0])
      .filter(Boolean)
      .sort();
    const browserValues = Object.values({ ...local, ...session }).map((value) => String(value ?? ''));
    return {
      localKeys: Object.keys(local).sort(),
      sessionKeys: Object.keys(session).sort(),
      visibleCookieNames,
      secretLeak: serialized.includes(mobile) || serialized.includes(otp),
      unexpectedLocalKeys: Object.keys(local).filter((key) => !allowedLocalKeys.has(key)),
      unexpectedSessionKeys: Object.keys(session).filter((key) => !allowedSessionKeys.has(key)),
      credentialKeyLeak: [...Object.keys(local), ...Object.keys(session)].some((key) => forbiddenKey.test(key)),
      credentialValueLeak: browserValues.some((value) => credentialValue.test(value)),
      registrationCapabilityLeak: registrationKey in session || serialized.includes(registrationKey),
      authCookieVisible: visibleCookieNames.some((name) => /(?:session|auth|token|bearer)/i.test(name)),
    };
  }, { mobile: loginMobile, otp: loginCode });
  const pendingSubmitRegression = await runS04PendingSubmitBrowser({ browser, base });
  record('login_otp_server_lifecycle', 'real cancel retirement + fresh start + verify + cookie session endpoints; synthetic abandoned-submit subchecks', {
    loginCalls,
    cancelRequest,
    cancelUpstream,
    pathWhileCancelResponseDeferred,
    pathAfterCancel,
    restartFloorReady,
    cancelledVerify: { status: cancelledVerify.status(), body: cancelledVerifyBody },
    authenticated,
    pendingSubmitRegression,
  },
    pendingSubmitRegression.pass
      && loginCalls.filter((call) => call.includes('POST /api/v1/auth/student/login/otp/start')).length >= 2
      && loginCalls.some((call) => call.includes('POST /api/v1/auth/student/otp/cancel'))
      && loginCalls.some((call) => call.includes('POST /api/v1/auth/student/login/otp/verify'))
      && cancelRequest?.method === 'POST'
      && JSON.stringify(cancelRequest?.body) === '{}'
      && cancelUpstream.status === 200
      && pathWhileCancelResponseDeferred === '/s-05'
      && pathAfterCancel === '/s-03'
      && restartFloorReady === true
      && cancelledVerify.status() === 401
      && authenticated.status === 200
      && authenticated.body?.actor?.roles?.includes('student'));
  record('login_secret_storage_privacy', 'no raw mobile, OTP, or session cookie visible to JavaScript storage', loginBrowserState,
    loginBrowserState.secretLeak === false
      && loginBrowserState.credentialKeyLeak === false
      && loginBrowserState.credentialValueLeak === false
      && loginBrowserState.registrationCapabilityLeak === false
      && loginBrowserState.authCookieVisible === false
      && loginBrowserState.unexpectedLocalKeys.length === 0
      && loginBrowserState.unexpectedSessionKeys.length === 0);
  await page.screenshot({ path: resolve(screenshotsDir, 'S-07__login-authenticated__mobile__light.png'), fullPage: true });
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.waitForURL('**/s-03');
  const afterLogout = await page.evaluate(async (sessionUrl) => {
    const response = await fetch(sessionUrl, { credentials: 'include' });
    return { status: response.status, body: await response.json() };
  }, `${apiBase}/api/v1/auth/student/session`);
  record('logout_clears_browser_session', 'S-03 and anonymous browser session probe after logout', { path: new URL(page.url()).pathname, ...afterLogout },
    new URL(page.url()).pathname === '/s-03'
      && afterLogout.status === 200
      && afterLogout.body?.authenticated === false
      && afterLogout.body?.actor === null);
  await context.close();
} finally {
  await browser.close();
}

const summary = { total: rows.length, passed: rows.filter((row) => row.pass).length, failed: rows.filter((row) => !row.pass).length, rows };
await writeFile(resolve(evidenceDir, 'results.json'), `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
await writeFile(resolve(evidenceDir, 'summary.txt'), `V3.4 S-01–S-10\ntotal=${summary.total}\npassed=${summary.passed}\nfailed=${summary.failed}\n`, 'utf8');
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
console.log(JSON.stringify({ total: summary.total, passed: summary.passed, failed: summary.failed, evidenceDir }, null, 2));
if (summary.failed > 0) process.exitCode = 1;
