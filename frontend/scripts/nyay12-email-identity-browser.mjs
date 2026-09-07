// NYAY-12 verified-email identity: real Chromium negative-path and lifecycle runner.
//
// Runs against a live loopback stack (production build + uvicorn + OTP capture
// double). Evidence written to NYAY12_EVIDENCE_DIR contains only closed-world
// row names, booleans/status codes and masked destinations. No raw email,
// code, cookie or token is ever written; screenshots are captured only in
// states that render masked or empty identity fields.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { chromium } from 'playwright';

const require = createRequire(import.meta.url);
const axeSource = await readFile(require.resolve('axe-core/axe.min.js'), 'utf8');

const WEB = process.env.NYAY12_WEB_BASE_URL ?? 'http://127.0.0.1:1148';
const API = process.env.NYAY12_API_BASE_URL ?? 'http://127.0.0.1:1146';
const CAPTURE = process.env.NYAY12_OTP_CAPTURE_URL ?? 'http://127.0.0.1:1147';
const OUT = process.env.NYAY12_EVIDENCE_DIR ?? path.resolve('test-results/nyay12-browser');
const RUN_TAG = process.env.NYAY12_RUN_TAG ?? Date.now().toString(36);
const rows = [];
const record = (name, expected, actual, pass) => rows.push({ name, expected, actual, pass: Boolean(pass) });
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function latestDelivery(destination) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const response = await fetch(`${CAPTURE}/latest`);
    const payload = await response.json();
    if (payload.to === destination && /^\d{6}$/.test(payload.code ?? '')) return payload.code;
    await wait(100);
  }
  throw new Error('capture did not observe the expected delivery');
}

async function resetCapture() {
  const response = await fetch(`${CAPTURE}/reset`, { method: 'POST' });
  if (!response.ok) throw new Error('capture reset failed');
}

async function noDeliveryFor(destination, ms = 1500) {
  await wait(ms);
  const payload = await (await fetch(`${CAPTURE}/latest`)).json();
  return payload.to !== destination;
}

async function observeAxe(page) {
  await page.addScriptTag({ content: axeSource });
  return page.evaluate(async () => {
    const result = await window.axe.run(document, { resultTypes: ['violations'] });
    return result.violations
      .filter((violation) => ['critical', 'serious'].includes(violation.impact ?? ''))
      .map((violation) => ({ id: violation.id, impact: violation.impact, nodes: violation.nodes.length }));
  });
}

async function webStorageAudit(page, secrets) {
  return page.evaluate((forbidden) => {
    const dump = [];
    for (const store of [localStorage, sessionStorage]) {
      for (let index = 0; index < store.length; index += 1) {
        const key = store.key(index);
        dump.push(`${key}=${store.getItem(key)}`);
      }
    }
    const joined = dump.join('\n');
    return {
      keys: dump.map((entry) => entry.split('=')[0]),
      leaks: forbidden.filter((value) => value && joined.includes(value)),
      hasAt: joined.includes('@'),
    };
  }, secrets);
}

async function registerStudent(context, mobile, dob = '2004-03-14') {
  const registered = await context.request.post(`${API}/api/v1/auth/student/register`, {
    headers: { Origin: WEB },
    data: {
      first_name: 'Synthetic', last_name: 'Student', mobile, dob,
      terms_accepted: true, terms_version: 'terms-2026-08.v1',
      privacy_notice_acknowledged: true, privacy_notice_version: 'privacy-2026-08.v1',
    },
  });
  if (registered.status() !== 202) throw new Error(`register ${registered.status()}`);
  const code = await latestDelivery(mobile);
  const verified = await context.request.post(`${API}/api/v1/auth/student/otp/verify`, { headers: { Origin: WEB }, data: { code } });
  if (verified.status() !== 200) throw new Error(`verify ${verified.status()}`);
  return { registrationStatus: registered.status(), verifyStatus: verified.status() };
}

function key(label) {
  return `nyay12-browser-${label}-${RUN_TAG}-${Math.random().toString(36).slice(2, 12)}`;
}

async function api(context, method, pathName, { body, idempotent = true, origin = WEB } = {}) {
  const headers = { Origin: origin };
  if (idempotent) headers['Idempotency-Key'] = key(method.toLowerCase());
  const response = await context.request.fetch(`${API}${pathName}`, { method, headers, data: body });
  const json = await response.json().catch(() => null);
  return { status: response.status(), json, headers: response.headers() };
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ headless: true });
const suffix = RUN_TAG.slice(-4).replace(/[^a-z0-9]/g, '0');
const MOBILE_A = `98765${suffix}1`.padEnd(10, '0').slice(0, 10);
const MOBILE_B = `98765${suffix}2`.padEnd(10, '0').slice(0, 10);
const EMAIL_A1 = `alpha-${RUN_TAG}@example.test`;
const EMAIL_A2 = `beta-${RUN_TAG}@example.test`;
const EMAIL_SHARED = `shared-${RUN_TAG}@example.test`;
const secrets = [];

try {
  await resetCapture();
  // --------------------------------------------------------------------- //
  // Actor A: authenticated identity lifecycle through the S-17 panel        //
  // --------------------------------------------------------------------- //
  const contextA = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, baseURL: WEB });
  const a = await registerStudent(contextA, MOBILE_A);
  record('A_registered_and_authenticated', '202/200', `${a.registrationStatus}/${a.verifyStatus}`, a.registrationStatus === 202 && a.verifyStatus === 200);
  const cookiesA = await contextA.cookies();
  const sessionA = cookiesA.find((cookie) => cookie.name === 'nyayone_session');
  if (sessionA) secrets.push(sessionA.value);
  record('A_session_cookie_httponly', 'HttpOnly', sessionA?.httpOnly ? 'HttpOnly' : 'exposed', sessionA?.httpOnly === true);

  const pageA = await contextA.newPage();
  await pageA.goto(`${WEB}/s-17`);
  const panel = pageA.getByTestId('profile-email-identities');
  await panel.waitFor({ state: 'visible', timeout: 20_000 });
  record('S17_panel_visible', 'visible', 'visible', true);
  await pageA.screenshot({ path: path.join(OUT, 'S-17-panel-empty-390.png'), fullPage: true });
  const axeEmpty = await observeAxe(pageA);
  record('S17_axe_serious_critical_empty', 0, axeEmpty.length, axeEmpty.length === 0);

  // Add A1 (masked in UI), verify with a wrong code first, then the real code.
  await pageA.getByLabel('Add a sign-in email').fill(EMAIL_A1);
  await pageA.getByRole('button', { name: 'Add sign-in email' }).click();
  const codeA1 = await latestDelivery(EMAIL_A1);
  secrets.push(codeA1);
  const rowA1 = panel.locator('[data-testid="profile-email-identity-row"]').first();
  await rowA1.waitFor({ state: 'visible' });
  const maskA1 = await rowA1.locator('.st-mono').first().innerText();
  record('S17_add_renders_mask_only', 'masked', /^[^\s@•]•{5}@[^\s@]+$/u.test(maskA1) && !maskA1.includes('alpha-') ? 'masked' : 'raw', /^[^\s@•]•{5}@[^\s@]+$/u.test(maskA1) && !maskA1.includes('alpha-'));
  const inputCleared = (await pageA.getByLabel('Add a sign-in email').inputValue()) === '';
  record('S17_add_success_clears_input', 'cleared', inputCleared ? 'cleared' : 'retained', inputCleared);
  const codeField = pageA.getByLabel(`Six digit code for ${maskA1}`);
  await codeField.fill(codeA1 === '000000' ? '111111' : '000000');
  await pageA.getByRole('button', { name: `Verify email ${maskA1}` }).click();
  const alert = pageA.getByRole('alert');
  await alert.first().waitFor({ state: 'visible' });
  const wrongCodeRetained = (await codeField.inputValue()).length === 6;
  const alertFocused = await pageA.evaluate(() => document.activeElement?.getAttribute('role') === 'alert');
  record('S17_wrong_code_typed_error_preserves_input_and_focuses_alert', 'retained+focused', `${wrongCodeRetained ? 'retained' : 'cleared'}+${alertFocused ? 'focused' : 'unfocused'}`, wrongCodeRetained && alertFocused);
  await codeField.fill(codeA1);
  await pageA.getByRole('button', { name: `Verify email ${maskA1}` }).click();
  await pageA.getByTestId('profile-email-identity-primary-badge').waitFor({ state: 'visible', timeout: 15_000 });
  record('S17_verify_marks_verified_and_primary', 'primary badge', 'primary badge', true);
  await pageA.screenshot({ path: path.join(OUT, 'S-17-panel-verified-390.png'), fullPage: true });
  const axeVerified = await observeAxe(pageA);
  record('S17_axe_serious_critical_verified', 0, axeVerified.length, axeVerified.length === 0);

  // Replayed proof after verification: the same code cannot verify anything again.
  const listingA = await api(contextA, 'GET', '/api/v1/auth/student/email-identities', { idempotent: false });
  const identityA1 = listingA.json.identities[0].id;
  const replay = await api(contextA, 'POST', `/api/v1/auth/student/email-identities/${identityA1}/verify`, { body: { code: codeA1 } });
  record('replayed_code_after_verification_rejected', 401, replay.status, replay.status === 401 && replay.json?.detail?.code === 'email_identity_verification_failed');

  // Spoofed selector / DOM tampering: remove maxLength and push non-digits; client keeps the six-digit contract.
  await pageA.getByLabel('Add a sign-in email').fill(EMAIL_A2);
  await pageA.getByRole('button', { name: 'Add sign-in email' }).click();
  const codeA2 = await latestDelivery(EMAIL_A2);
  secrets.push(codeA2);
  const rowA2 = panel.locator('[data-testid="profile-email-identity-row"]').filter({ hasNot: pageA.getByTestId('profile-email-identity-primary-badge') }).first();
  await rowA2.waitFor({ state: 'visible' });
  const maskA2 = await rowA2.locator('.st-mono').first().innerText();
  const codeField2 = pageA.getByLabel(`Six digit code for ${maskA2}`);
  await codeField2.evaluate((node) => { node.removeAttribute('maxlength'); node.setAttribute('inputmode', 'text'); });
  await codeField2.fill('12ab34cd56');
  const tamperedValue = await codeField2.inputValue();
  record('S17_dom_tamper_cannot_bypass_six_digit_contract', 'digits<=6', tamperedValue.length <= 6 && /^\d*$/.test(tamperedValue) ? 'digits<=6' : 'tampered', tamperedValue.length <= 6 && /^\d*$/.test(tamperedValue));
  if (tamperedValue.length === 6) {
    // The sanitized six digits are a wrong code: the server, not the DOM, decides.
    await pageA.getByRole('button', { name: `Verify email ${maskA2}` }).click();
    await pageA.getByRole('alert').first().waitFor({ state: 'visible' });
    const stillPending = await pageA.getByRole('button', { name: `Verify email ${maskA2}` }).count();
    record('S17_dom_tamper_wrong_code_typed_failure_no_promotion', 'still pending', stillPending > 0 ? 'still pending' : 'promoted', stillPending > 0);
  }
  const forged = await pageA.evaluate(async ({ apiBase, identityId }) => {
    const response = await fetch(`${apiBase}/api/v1/auth/student/email-identities/${identityId}/verify`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': `forged-nyay12-${Date.now()}-abcdef` },
      body: JSON.stringify({ code: '123456', user_id: '00000000-0000-4000-8000-000000000000', verified: true }),
    });
    return response.status;
  }, { apiBase: API, identityId: identityA1 });
  record('forged_body_fields_rejected_422', 422, forged, forged === 422);

  // Delivery failure presentation: a typed 503 keeps the typed address and focuses the error.
  await pageA.route('**/api/v1/auth/student/email-identities', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    return route.fulfill({ status: 503, contentType: 'application/json', headers: { 'Cache-Control': 'private, no-store' }, body: JSON.stringify({ detail: { code: 'email_delivery_unavailable', message: 'Request failed' } }) });
  });
  await pageA.getByLabel('Add a sign-in email').fill('gamma-unused@example.test');
  await pageA.getByRole('button', { name: 'Add sign-in email' }).click();
  await pageA.locator('#profile-email-identity-input-error').waitFor({ state: 'visible' });
  const retained = (await pageA.getByLabel('Add a sign-in email').inputValue()) === 'gamma-unused@example.test';
  const errorFocused = await pageA.evaluate(() => document.activeElement?.id === 'profile-email-identity-input-error');
  record('S17_delivery_failure_preserves_input_and_focuses_error', 'retained+focused', `${retained ? 'retained' : 'cleared'}+${errorFocused ? 'focused' : 'unfocused'}`, retained && errorFocused);
  await pageA.unroute('**/api/v1/auth/student/email-identities');
  await pageA.getByLabel('Add a sign-in email').fill('');

  // Complete A2 verification via the UI, then concurrent primary promotions.
  await codeField2.evaluate((node) => { node.setAttribute('maxlength', '6'); });
  await codeField2.fill(codeA2);
  await pageA.getByRole('button', { name: `Verify email ${maskA2}` }).click();
  await pageA.getByRole('button', { name: `Make ${maskA2} the primary sign-in email` }).waitFor({ state: 'visible', timeout: 15_000 });
  const listingA2 = await api(contextA, 'GET', '/api/v1/auth/student/email-identities', { idempotent: false });
  const ids = listingA2.json.identities.map((identity) => identity.id);
  const promotions = await Promise.all([...ids, ...ids].map((identityId) => api(contextA, 'POST', `/api/v1/auth/student/email-identities/${identityId}/primary`, { body: {} })));
  const afterPromotions = await api(contextA, 'GET', '/api/v1/auth/student/email-identities', { idempotent: false });
  const primaries = afterPromotions.json.identities.filter((identity) => identity.is_primary).length;
  record('concurrent_primary_promotions_exactly_one_primary', 1, primaries, primaries === 1 && promotions.every((outcome) => [200, 409, 429].includes(outcome.status)));

  // Cross-user binding: B cannot verify, resend, remove or promote A's identities; B's pending claim on A's address cannot win.
  const contextB = await browser.newContext({ viewport: { width: 1440, height: 1024 }, baseURL: WEB });
  const b = await registerStudent(contextB, MOBILE_B);
  record('B_registered', '202/200', `${b.registrationStatus}/${b.verifyStatus}`, b.registrationStatus === 202 && b.verifyStatus === 200);
  const crossStatuses = await Promise.all([
    api(contextB, 'POST', `/api/v1/auth/student/email-identities/${identityA1}/verify`, { body: { code: codeA1 } }),
    api(contextB, 'POST', `/api/v1/auth/student/email-identities/${identityA1}/resend`, { body: {} }),
    api(contextB, 'DELETE', `/api/v1/auth/student/email-identities/${identityA1}`),
    api(contextB, 'POST', `/api/v1/auth/student/email-identities/${identityA1}/primary`, { body: {} }),
  ]);
  record('cross_user_management_denied_404', '404x4', crossStatuses.map((outcome) => outcome.status).join(','), crossStatuses.every((outcome) => outcome.status === 404 && outcome.json?.detail?.code === 'email_identity_not_found'));
  const claimB = await api(contextB, 'POST', '/api/v1/auth/student/email-identities', { body: { email: EMAIL_A1 } });
  const codeBclaim = await latestDelivery(EMAIL_A1);
  secrets.push(codeBclaim);
  const collision = await api(contextB, 'POST', `/api/v1/auth/student/email-identities/${claimB.json.identity.id}/verify`, { body: { code: codeBclaim } });
  const stillA = await api(contextA, 'GET', '/api/v1/auth/student/email-identities', { idempotent: false });
  record('verified_collision_fails_closed_409_owner_unchanged', '202→409, A verified', `${claimB.status}→${collision.status}, A ${stillA.json.identities.find((identity) => identity.id === identityA1)?.state}`, claimB.status === 202 && collision.status === 409 && collision.json?.detail?.code === 'email_identity_conflict' && stillA.json.identities.find((identity) => identity.id === identityA1)?.state === 'verified');
  const crossOrigin = await api(contextB, 'POST', '/api/v1/auth/student/email-identities', { body: { email: EMAIL_SHARED }, origin: 'https://evil.example' });
  record('cross_origin_mutation_rejected_403', 403, crossOrigin.status, crossOrigin.status === 403);

  // Web Storage audit on A (authenticated, after full lifecycle).
  const storageA = await webStorageAudit(pageA, secrets);
  record('web_storage_holds_no_email_code_or_token', 'no leaks', storageA.leaks.length === 0 && !storageA.hasAt ? 'no leaks' : 'leak', storageA.leaks.length === 0 && !storageA.hasAt);

  // --------------------------------------------------------------------- //
  // Auth precedence: logout, then the panel and API are unavailable.       //
  // --------------------------------------------------------------------- //
  const logout = await api(contextA, 'POST', '/api/v1/auth/student/logout', { body: {}, idempotent: false });
  await pageA.goto(`${WEB}/s-17`);
  await pageA.locator('[data-screen="S-03"]').waitFor({ state: 'visible', timeout: 20_000 });
  const anonymousListing = await api(contextA, 'GET', '/api/v1/auth/student/email-identities', { idempotent: false });
  record('logout_redirects_s17_to_s03_and_api_401', '200/S-03/401', `${logout.status}/S-03/${anonymousListing.status}`, logout.status === 200 && anonymousListing.status === 401);

  // --------------------------------------------------------------------- //
  // S-04 / S-05: server-proven channel choice and destination continuity.  //
  // --------------------------------------------------------------------- //
  await pageA.goto(`${WEB}/s-04`);
  const emailButton = pageA.getByRole('button', { name: 'Verified Email' });
  await emailButton.waitFor({ state: 'visible' });
  await pageA.waitForFunction(() => {
    const button = Array.from(document.querySelectorAll('button')).find((node) => node.textContent?.includes('Verified Email'));
    return button && !button.disabled;
  }, undefined, { timeout: 15_000 });
  record('S04_email_channel_enabled_only_from_server_projection', 'enabled', 'enabled', true);
  await emailButton.click();
  await pageA.locator('#v34-login-email').waitFor({ state: 'visible' });
  const pressed = await emailButton.getAttribute('aria-pressed');
  record('S04_email_channel_aria_pressed_and_email_field', 'true+email field', `${pressed}+email field`, pressed === 'true');
  await pageA.screenshot({ path: path.join(OUT, 'S-04-email-channel-390.png'), fullPage: true });
  const axeS04 = await observeAxe(pageA);
  record('S04_axe_serious_critical', 0, axeS04.length, axeS04.length === 0);
  // Keyboard: Shift+Tab from the email field lands on the email segment button; Space re-selects mobile.
  await pageA.locator('#v34-login-email').focus();
  await pageA.keyboard.press('Shift+Tab');
  const focusedText = await pageA.evaluate(() => document.activeElement?.textContent ?? '');
  record('S04_keyboard_reaches_channel_group', 'Verified Email', focusedText.trim(), focusedText.includes('Verified Email'));

  // Unknown address: identical 202 shape, S-05 renders the masked destination, no delivery, no authentication.
  await resetCapture();
  await pageA.locator('#v34-login-email').fill(`unknown-${RUN_TAG}@example.test`);
  await pageA.getByRole('button', { name: 'Send one time code' }).click();
  await pageA.locator('[data-screen="S-05"]').waitFor({ state: 'visible', timeout: 20_000 });
  await pageA.getByLabel('Six digit code').waitFor({ state: 'visible' });
  const s05Unknown = await pageA.locator('[data-screen="S-05"]').innerText();
  const maskUnknown = /[^\s@•]•{5}@[^\s@]+/u.exec(s05Unknown)?.[0] ?? '';
  record('S05_unknown_email_renders_masked_destination_no_raw', 'masked', maskUnknown && !s05Unknown.includes(`unknown-${RUN_TAG}`) ? 'masked' : 'raw/missing', Boolean(maskUnknown) && !s05Unknown.includes(`unknown-${RUN_TAG}`));
  record('S05_unknown_email_no_delivery', 'none', (await noDeliveryFor(`unknown-${RUN_TAG}@example.test`)) ? 'none' : 'delivered', await noDeliveryFor(`unknown-${RUN_TAG}@example.test`, 200));
  await pageA.getByLabel('Six digit code').fill('123456');
  await pageA.getByRole('button', { name: 'Verify and continue' }).click();
  await pageA.getByRole('alert').first().waitFor({ state: 'visible' });
  const stillS05 = await pageA.locator('[data-screen="S-05"]').isVisible();
  record('S05_unknown_email_code_cannot_authenticate', 'stays S-05', stillS05 ? 'stays S-05' : 'navigated', stillS05);
  await pageA.getByRole('button', { name: 'Change email address' }).click();
  await pageA.locator('[data-screen="S-04"]').waitFor({ state: 'visible' });
  record('S05_change_returns_to_S04', 'S-04', 'S-04', true);

  // Verified address: masked continuity, wrong code fails, real code authenticates into S-07.
  await resetCapture();
  await pageA.getByRole('button', { name: 'Verified Email' }).click();
  await pageA.locator('#v34-login-email').fill(EMAIL_A1.toUpperCase());
  await pageA.getByRole('button', { name: 'Send one time code' }).click();
  await pageA.locator('[data-screen="S-05"]').waitFor({ state: 'visible', timeout: 20_000 });
  await pageA.getByLabel('Six digit code').waitFor({ state: 'visible' });
  const s05Text = await pageA.locator('[data-screen="S-05"]').innerText();
  record('S05_verified_email_masked_continuity_case_insensitive', maskA1, /[^\s@•]•{5}@[^\s@]+/u.exec(s05Text)?.[0] ?? 'missing', s05Text.includes(maskA1) && !s05Text.toLowerCase().includes('alpha-'));
  await pageA.screenshot({ path: path.join(OUT, 'S-05-email-destination-390.png'), fullPage: true });
  const axeS05 = await observeAxe(pageA);
  record('S05_axe_serious_critical', 0, axeS05.length, axeS05.length === 0);
  const loginCode = await latestDelivery(EMAIL_A1);
  secrets.push(loginCode);
  await pageA.getByLabel('Six digit code').fill(loginCode === '000000' ? '111111' : '000000');
  await pageA.getByRole('button', { name: 'Verify and continue' }).click();
  await pageA.getByRole('alert').first().waitFor({ state: 'visible' });
  record('S05_wrong_code_typed_failure_no_navigation', 'stays S-05', (await pageA.locator('[data-screen="S-05"]').isVisible()) ? 'stays S-05' : 'navigated', await pageA.locator('[data-screen="S-05"]').isVisible());
  await pageA.getByLabel('Six digit code').fill(loginCode);
  await pageA.getByRole('button', { name: 'Verify and continue' }).click();
  await pageA.locator('[data-screen="S-07"], [data-screen="S-14"]').first().waitFor({ state: 'visible', timeout: 20_000 });
  const sessionProbe = await api(contextA, 'GET', '/api/v1/auth/student/session', { idempotent: false });
  record('S05_verified_email_login_authenticates_server_session', 'authenticated', sessionProbe.json?.authenticated ? 'authenticated' : 'anonymous', sessionProbe.json?.authenticated === true);
  const storageAfterLogin = await webStorageAudit(pageA, secrets);
  record('web_storage_after_email_login_clean', 'no leaks', storageAfterLogin.leaks.length === 0 && !storageAfterLogin.hasAt ? 'no leaks' : 'leak', storageAfterLogin.leaks.length === 0 && !storageAfterLogin.hasAt);

  // Channel projection failure → fail-closed mobile-only S-04 (client never decides).
  const pageC = await contextB.newPage();
  await pageC.route('**/api/v1/auth/student/login/channels', (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }));
  await pageC.goto(`${WEB}/s-04`);
  await pageC.locator('#v34-login-mobile').waitFor({ state: 'visible' });
  await wait(500);
  const emailDisabled = await pageC.getByRole('button', { name: 'Verified Email' }).isDisabled();
  record('S04_projection_failure_falls_back_to_mobile_only', 'disabled', emailDisabled ? 'disabled' : 'enabled', emailDisabled);
  await pageC.screenshot({ path: path.join(OUT, 'S-04-projection-absent-1440.png'), fullPage: true });
  await pageC.unroute('**/api/v1/auth/student/login/channels');
  await pageC.goto(`${WEB}/s-04`);
  await pageC.waitForFunction(() => {
    const button = Array.from(document.querySelectorAll('button')).find((node) => node.textContent?.includes('Verified Email'));
    return button && !button.disabled;
  }, undefined, { timeout: 15_000 });
  await pageC.getByRole('button', { name: 'Verified Email' }).click();
  await pageC.locator('#v34-login-email').waitFor({ state: 'visible' });
  await pageC.screenshot({ path: path.join(OUT, 'S-04-email-channel-1440.png'), fullPage: true });
  const axeS04Desktop = await observeAxe(pageC);
  record('S04_axe_serious_critical_desktop', 0, axeS04Desktop.length, axeS04Desktop.length === 0);
  await contextB.close();
  await contextA.close();
} catch (error) {
  record('runner_uncaught_failure', 'none', String(error?.name ?? error).slice(0, 120), false);
} finally {
  await browser.close();
}

const summary = {
  schema_version: 'nyay12-browser-evidence/v1',
  web_base_url: WEB,
  total: rows.length,
  passed: rows.filter((row) => row.pass).length,
  failed: rows.filter((row) => !row.pass).length,
  rows,
};
await writeFile(path.join(OUT, 'results.json'), `${JSON.stringify(summary, null, 2)}\n`);
console.log(JSON.stringify({ total: summary.total, passed: summary.passed, failed: summary.failed }));
if (summary.failed > 0) process.exit(1);
