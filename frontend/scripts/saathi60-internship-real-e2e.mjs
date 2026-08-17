/**
 * SAATHI-60 real HTTP/PostgreSQL/browser release gate.
 *
 * This runner installs no route mocks. It creates a student through the real
 * registration OTP flow, obtains a real HttpOnly login-session cookie, and
 * proves catalogue identity plus account-backed save persistence through the
 * production frontend and API. Raw OTPs, mobile numbers, and session tokens
 * remain in memory and are never written to evidence.
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import axe from 'axe-core';
import { chromium, request as playwrightRequest } from 'playwright';

const WEB = loopbackOrigin('SAATHI60_WEB_URL', process.env.SAATHI60_WEB_URL ?? 'http://127.0.0.1:4177');
const API = loopbackOrigin('SAATHI60_API_URL', process.env.SAATHI60_API_URL ?? 'http://127.0.0.1:1042');
const OTP = loopbackOrigin('SAATHI60_OTP_URL', process.env.SAATHI60_OTP_URL ?? 'http://127.0.0.1:1099');
if (WEB.hostname !== API.hostname || WEB.hostname !== OTP.hostname) {
  throw new Error('SAATHI60_WEB_URL, SAATHI60_API_URL, and SAATHI60_OTP_URL must use the same loopback hostname');
}
const output = process.env.SAATHI60_EVIDENCE_DIR;
if (!output || !path.isAbsolute(output)) throw new Error('SAATHI60_EVIDENCE_DIR must be an absolute path');
const OUT = path.resolve(output);
const SCREENSHOTS = path.join(OUT, 'screenshots');
await mkdir(SCREENSHOTS, { recursive: true });

const viewports = [
  { name: '390x844', width: 390, height: 844 },
  { name: '430x932', width: 430, height: 932 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '1024x768', width: 1024, height: 768 },
  { name: '1440x900', width: 1440, height: 900 },
];
const themes = ['light', 'dark'];
const mobileScrollBudget = { 'S-20': 172, 'S-21': 205, 'S-25': 0, 'S-26': 0 };
const report = {
  evidenceClass: 'real-http-postgresql-cookie-browser',
  startedAt: new Date().toISOString(),
  webOrigin: WEB.origin,
  apiOrigin: API.origin,
  rows: [],
  failures: [],
  screenshots: 0,
};
const secrets = new Set();
let fatalError = null;

function loopbackOrigin(name, raw) {
  const value = new URL(raw);
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(value.hostname)
      || !['http:', 'https:'].includes(value.protocol)
      || value.username || value.password || value.search || value.hash || value.pathname !== '/') {
    throw new Error(`${name} must contain only an HTTP(S) loopback origin`);
  }
  return value;
}

function sanitize(value) {
  let text = typeof value === 'string' ? value : JSON.stringify(value);
  for (const secret of secrets) text = text.replaceAll(secret, '[REDACTED]');
  return text.slice(0, 4000);
}

function record(name, expected, actual, pass) {
  const row = { name, expected, actual: sanitize(actual), pass: Boolean(pass) };
  report.rows.push(row);
  if (!row.pass) report.failures.push(`${name}: expected ${expected}; actual ${row.actual}`);
}

function requireRow(name, expected, actual, pass) {
  record(name, expected, actual, pass);
  if (!pass) throw new Error(`${name}: expected ${expected}; actual ${sanitize(actual)}`);
}

async function jsonResponse(response) {
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { /* caller validates */ }
  return { status: response.status(), body };
}

async function apiJson(api, method, pathname, data) {
  return jsonResponse(await api.fetch(pathname, {
    method,
    ...(data === undefined ? {} : { data }),
  }));
}

async function resetOtp() {
  const response = await fetch(new URL('/reset', OTP), { method: 'POST' });
  if (!response.ok) throw new Error('OTP capture reset failed');
}

async function latestOtp() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await fetch(new URL('/latest', OTP));
    if (response.ok) {
      const body = await response.json();
      if (/^\d{6}$/.test(body.code ?? '')) {
        secrets.add(body.code);
        return body.code;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('OTP provider did not receive a strict six-digit code');
}

function responseMatches(response, method, pathname) {
  const url = new URL(response.url());
  return response.request().method() === method && url.pathname === pathname;
}

async function finishedResponse(promise, expectedStatus = 200) {
  const response = await promise;
  const failure = await response.finished();
  const actual = {
    method: response.request().method(),
    path: new URL(response.url()).pathname,
    status: response.status(),
    finishedError: failure?.message ?? null,
  };
  requireRow(
    `response:${actual.method}:${actual.path}`,
    `HTTP ${expectedStatus}, body fully received`,
    actual,
    actual.status === expectedStatus && actual.finishedError === null,
  );
  return response;
}

function watchRuntime(page) {
  const runtime = { consoleErrors: [], pageErrors: [], failedRequests: [], httpErrors: [] };
  page.on('console', (message) => {
    if (message.type() === 'error') runtime.consoleErrors.push(sanitize(message.text()));
  });
  page.on('pageerror', (error) => runtime.pageErrors.push(sanitize(error.message)));
  page.on('requestfailed', (request) => {
    runtime.failedRequests.push(sanitize(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`));
  });
  page.on('response', (response) => {
    if (response.status() >= 400) runtime.httpErrors.push(sanitize(`${response.status()} ${response.url()}`));
  });
  return runtime;
}

function runtimeClean(runtime) {
  return Object.values(runtime).every((entries) => entries.length === 0);
}

async function addSessionCookies(context, api) {
  const state = await api.storageState();
  const cookies = state.cookies.filter((cookie) => cookie.name === 'nyayone_session');
  if (cookies.length !== 1) throw new Error('login did not produce exactly one session cookie');
  secrets.add(cookies[0].value);
  await context.addCookies(cookies);
}

async function newAuthenticatedContext(api, viewport, theme) {
  const context = await browser.newContext({ viewport, colorScheme: theme });
  await addSessionCookies(context, api);
  await context.addInitScript((value) => localStorage.setItem('ls-theme', value), theme);
  return context;
}

async function waitForTextReady(page, loadingText) {
  await page.waitForFunction((text) => !document.body.innerText.includes(text), loadingText);
  await page.evaluate(async () => {
    if (document.fonts) await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

async function geometry(page) {
  return page.evaluate(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const smallTargets = [...document.querySelectorAll('button,input,select,textarea,a[href]')]
      .filter(visible)
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
    return {
      screen: document.querySelector('[data-screen]')?.getAttribute('data-screen'),
      bodyOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      contentOverflowX: content ? content.scrollWidth - content.clientWidth : -1,
      contentOverflowY: content ? content.scrollHeight - content.clientHeight : -1,
      smallTargets,
    };
  });
}

async function verifyVisualPage(page, screen, viewport, theme, screenshotPath) {
  const probe = await geometry(page);
  const prefix = `${screen}__${viewport.name}__${theme}`;
  record(`${prefix}:screen`, screen, probe.screen, probe.screen === screen);
  record(`${prefix}:overflow-x`, '0px', { body: probe.bodyOverflowX, content: probe.contentOverflowX },
    probe.bodyOverflowX === 0 && probe.contentOverflowX <= 1);
  record(`${prefix}:targets`, 'all visible controls >=44x44', probe.smallTargets, probe.smallTargets.length === 0);
  if (viewport.width <= 430) {
    const budget = mobileScrollBudget[screen];
    record(`${prefix}:mobile-scroll`, `<=${budget}px`, probe.contentOverflowY, probe.contentOverflowY <= budget);
  }
  if (viewport.width === 390 || viewport.width === 1440) {
    await page.addScriptTag({ content: axe.source });
    const violations = await page.evaluate(async () => {
      const result = await globalThis.axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
      });
      return result.violations.map((violation) => ({ id: violation.id, impact: violation.impact }));
    });
    record(`${prefix}:axe`, '0 WCAG A/AA violations', violations, violations.length === 0);
  }
  await page.screenshot({ path: screenshotPath, fullPage: false });
  report.screenshots += 1;
}

const browser = await chromium.launch({ headless: true });
const api = await playwrightRequest.newContext({
  baseURL: API.origin,
  extraHTTPHeaders: { Accept: 'application/json', 'Content-Type': 'application/json' },
});

try {
  const mobile = `8${String(Date.now() % 1_000_000_000).padStart(9, '0')}`;
  secrets.add(mobile);
  await resetOtp();
  const registration = await apiJson(api, 'POST', '/api/v1/auth/student/register', {
    first_name: 'QA',
    last_name: 'Student',
    mobile,
    dob: '2004-03-14',
    consent: { accepted: true },
  });
  requireRow('registration:start', 'HTTP 201', registration.status, registration.status === 201);
  const registrationId = registration.body?.registration_id;
  if (typeof registrationId !== 'string') throw new Error('registration_id missing');
  const registrationCode = await latestOtp();
  const registrationVerify = await apiJson(api, 'POST', '/api/v1/auth/student/otp/verify', {
    registration_id: registrationId,
    code: registrationCode,
  });
  requireRow('registration:verify', 'HTTP 200', registrationVerify.status, registrationVerify.status === 200);

  await resetOtp();
  const loginStart = await apiJson(api, 'POST', '/api/v1/auth/student/login/otp/start', { mobile });
  requireRow('login:start', 'non-enumerating HTTP 202', loginStart.status, loginStart.status === 202);
  const loginId = loginStart.body?.login_id;
  if (typeof loginId !== 'string') throw new Error('login_id missing');
  const loginCode = await latestOtp();
  const loginVerify = await apiJson(api, 'POST', '/api/v1/auth/student/login/otp/verify', {
    login_id: loginId,
    code: loginCode,
  });
  requireRow('login:verify', 'HTTP 200 and authenticated session', loginVerify.status, loginVerify.status === 200);
  const session = await apiJson(api, 'GET', '/api/v1/auth/student/session');
  requireRow('login:session', 'cookie-backed student actor', session.body,
    session.status === 200 && session.body?.authenticated === true && session.body?.actor?.roles?.includes('student'));

  const context = await newAuthenticatedContext(api, { width: 1440, height: 900 }, 'light');
  const page = await context.newPage();
  const runtime = watchRuntime(page);
  const catalogueGet = page.waitForResponse((response) => responseMatches(response, 'GET', '/api/v1/internships'));
  const savedGet = page.waitForResponse((response) => responseMatches(response, 'GET', '/api/v1/student/internships/saved'));
  await page.goto(new URL('/s-20', WEB).href, { waitUntil: 'domcontentloaded' });
  await Promise.all([finishedResponse(catalogueGet), finishedResponse(savedGet)]);
  await waitForTextReady(page, 'Loading internships');
  const shownCount = page.locator('section[aria-label="Open listings"] .st-metatag');
  requireRow('catalogue:count', '3 shown', (await shownCount.textContent())?.trim(),
    (await shownCount.textContent())?.trim() === '3 shown');
  await page.getByRole('button', { name: 'Verified only' }).click();
  requireRow('catalogue:verified-only', 'exactly CAM', await page.locator('section[aria-label="Open listings"]').innerText(),
    (await shownCount.textContent())?.trim() === '1 shown'
      && await page.getByText(/Summer Associate, disputes — Cyril Amarchand Mangaldas/).isVisible()
      && !(await page.getByText(/Judicial research assistant — Chambers/).isVisible().catch(() => false)));
  await page.getByRole('button', { name: 'Verified only' }).click();
  const disclosure = page.locator('details.v34c-mobile-disclosure');
  const disclosureSummary = disclosure.locator('summary');
  if (await disclosureSummary.isVisible() && !(await disclosure.getAttribute('open'))) {
    await disclosureSummary.click();
  }
  const menonRow = page.getByRole('listitem').filter({ hasText: 'Chambers of Sr. Adv. R. Menon' });
  await Promise.all([
    finishedResponse(page.waitForResponse((response) => responseMatches(response, 'GET', '/api/v1/internships/menon'))),
    menonRow.getByRole('button', { name: 'View' }).click(),
  ]);
  await waitForTextReady(page, 'Loading internship');
  requireRow('identity:view-menon', '/s-21?listing=menon and Menon heading', {
    url: page.url(),
    heading: await page.getByRole('heading', { level: 1 }).innerText(),
  }, new URL(page.url()).pathname === '/s-21'
      && new URL(page.url()).searchParams.get('listing') === 'menon'
      && (await page.getByRole('heading', { level: 1 }).innerText()) === 'Judicial research assistant');

  const savePut = page.waitForResponse((response) => responseMatches(response, 'PUT', '/api/v1/student/internships/menon/saved'));
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await finishedResponse(savePut);
  await page.getByText('Saved privately to your account. The organisation is not notified.').waitFor();

  const savedPageGet = page.waitForResponse((response) => responseMatches(response, 'GET', '/api/v1/student/internships/saved'));
  await page.goto(new URL('/s-25', WEB).href, { waitUntil: 'domcontentloaded' });
  await finishedResponse(savedPageGet);
  await waitForTextReady(page, 'Loading saved internships');
  requireRow('saved:first-context', 'Menon persisted', await page.locator('main').innerText(),
    await page.getByText(/Judicial research assistant — Chambers of Sr. Adv. R. Menon/).isVisible());
  record('runtime:primary', '0 console/page/request/HTTP errors', runtime, runtimeClean(runtime));
  await context.close();

  const secondContext = await newAuthenticatedContext(api, { width: 1024, height: 768 }, 'light');
  const secondPage = await secondContext.newPage();
  const secondRuntime = watchRuntime(secondPage);
  const secondSavedGet = secondPage.waitForResponse((response) => responseMatches(response, 'GET', '/api/v1/student/internships/saved'));
  await secondPage.goto(new URL('/s-25', WEB).href, { waitUntil: 'domcontentloaded' });
  await finishedResponse(secondSavedGet);
  await waitForTextReady(secondPage, 'Loading saved internships');
  requireRow('saved:fresh-browser-context', 'same account still contains Menon', await secondPage.locator('main').innerText(),
    await secondPage.getByText(/Judicial research assistant — Chambers of Sr. Adv. R. Menon/).isVisible());
  record('runtime:fresh-context', '0 console/page/request/HTTP errors', secondRuntime, runtimeClean(secondRuntime));
  await secondContext.close();

  for (const viewport of viewports) {
    for (const theme of themes) {
      const visualContext = await newAuthenticatedContext(api, viewport, theme);
      const visualPage = await visualContext.newPage();
      const visualRuntime = watchRuntime(visualPage);

      for (const screen of [
        { id: 'S-20', path: '/s-20', loading: 'Loading internships', responses: ['/api/v1/internships', '/api/v1/student/internships/saved'] },
        { id: 'S-21', path: '/s-21?listing=menon', loading: 'Loading internship', responses: ['/api/v1/internships/menon', '/api/v1/student/internships/saved'] },
        { id: 'S-25', path: '/s-25', loading: 'Loading saved internships', responses: ['/api/v1/student/internships/saved'] },
      ]) {
        const pending = screen.responses.map((pathname) => visualPage.waitForResponse(
          (response) => responseMatches(response, 'GET', pathname),
        ));
        await visualPage.goto(new URL(screen.path, WEB).href, { waitUntil: 'domcontentloaded' });
        await Promise.all(pending.map((promise) => finishedResponse(promise)));
        await waitForTextReady(visualPage, screen.loading);
        await verifyVisualPage(
          visualPage,
          screen.id,
          viewport,
          theme,
          path.join(SCREENSHOTS, `${screen.id.toLowerCase()}__${viewport.name}__${theme}.png`),
        );
      }
      record(`runtime:${viewport.name}:${theme}`, '0 console/page/request/HTTP errors', visualRuntime, runtimeClean(visualRuntime));
      await visualContext.close();
    }
  }

  const removalContext = await newAuthenticatedContext(api, { width: 1440, height: 900 }, 'light');
  const removalPage = await removalContext.newPage();
  const removalGet = removalPage.waitForResponse((response) => responseMatches(response, 'GET', '/api/v1/student/internships/saved'));
  await removalPage.goto(new URL('/s-25', WEB).href, { waitUntil: 'domcontentloaded' });
  await finishedResponse(removalGet);
  await waitForTextReady(removalPage, 'Loading saved internships');
  const removeDelete = removalPage.waitForResponse((response) => responseMatches(response, 'DELETE', '/api/v1/student/internships/menon/saved'));
  await removalPage.getByRole('button', { name: 'Remove', exact: true }).click();
  await finishedResponse(removeDelete);
  await removalPage.getByText('Removed from your saved internships.').waitFor();
  await removalContext.close();

  for (const viewport of viewports) {
    for (const theme of themes) {
      const emptyContext = await newAuthenticatedContext(api, viewport, theme);
      const emptyPage = await emptyContext.newPage();
      const emptyRuntime = watchRuntime(emptyPage);
      const emptyGet = emptyPage.waitForResponse((response) => responseMatches(response, 'GET', '/api/v1/student/internships/saved'));
      await emptyPage.goto(new URL('/s-26', WEB).href, { waitUntil: 'domcontentloaded' });
      await finishedResponse(emptyGet);
      await waitForTextReady(emptyPage, 'Loading saved internships');
      requireRow(`empty:${viewport.name}:${theme}`, 'truthful empty server state', await emptyPage.locator('main').innerText(),
        await emptyPage.getByText('No saved internships yet').isVisible());
      await verifyVisualPage(
        emptyPage,
        'S-26',
        viewport,
        theme,
        path.join(SCREENSHOTS, `s-26__${viewport.name}__${theme}.png`),
      );
      const storage = await emptyPage.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, cookies: document.cookie }));
      const serialized = JSON.stringify(storage).toLowerCase();
      record(`privacy:${viewport.name}:${theme}`, 'no saved-list cache, OTP, mobile, or readable session cookie', storage,
        !Object.hasOwn(storage.local, 'legalsaathi.internship.saved.v1')
          && !serialized.includes('otp')
          && !serialized.includes('mobile')
          && !serialized.includes('nyayone_session'));
      record(`runtime:empty:${viewport.name}:${theme}`, '0 console/page/request/HTTP errors', emptyRuntime, runtimeClean(emptyRuntime));
      await emptyContext.close();
    }
  }

  const negativeContext = await newAuthenticatedContext(api, { width: 390, height: 844 }, 'light');
  const negativePage = await negativeContext.newPage();
  await negativePage.goto(new URL('/s-21', WEB).href, { waitUntil: 'domcontentloaded' });
  requireRow('negative:missing-identity', 'truthful unavailable; no CAM fallback', await negativePage.locator('main').innerText(),
    await negativePage.getByText('Listing unavailable').isVisible()
      && !(await negativePage.getByText('Cyril Amarchand Mangaldas').isVisible().catch(() => false)));
  const unknownGet = negativePage.waitForResponse((response) => responseMatches(response, 'GET', '/api/v1/internships/not-a-listing'));
  await negativePage.goto(new URL('/s-21?listing=not-a-listing', WEB).href, { waitUntil: 'domcontentloaded' });
  await finishedResponse(unknownGet, 404);
  requireRow('negative:unknown-identity', '404 produces unavailable state; no fallback', await negativePage.locator('main').innerText(),
    await negativePage.getByText('Listing unavailable').isVisible()
      && !(await negativePage.getByText('Cyril Amarchand Mangaldas').isVisible().catch(() => false)));
  await negativeContext.close();
} catch (error) {
  fatalError = sanitize(error instanceof Error ? `${error.name}: ${error.message}\n${error.stack ?? ''}` : String(error));
  report.failures.push(fatalError);
} finally {
  report.completedAt = new Date().toISOString();
  report.fatalError = fatalError;
  report.total = report.rows.length;
  report.passed = report.rows.filter((row) => row.pass).length;
  report.failed = report.rows.filter((row) => !row.pass).length + (fatalError ? 1 : 0);
  await writeFile(path.join(OUT, 'results.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  await writeFile(path.join(OUT, 'summary.txt'), [
    'SAATHI-60 real target-runtime internship gate',
    `total=${report.total}`,
    `passed=${report.passed}`,
    `failed=${report.failed}`,
    `screenshots=${report.screenshots}`,
  ].join('\n') + '\n', 'utf8');
  await api.dispose();
  await browser.close();

  const files = ['results.json', 'summary.txt', ...(await readdir(SCREENSHOTS)).sort().map((name) => `screenshots/${name}`)];
  const checksums = [];
  for (const relative of files) {
    const digest = createHash('sha256').update(await readFile(path.join(OUT, relative))).digest('hex');
    checksums.push(`${digest}  ${relative}`);
  }
  await writeFile(path.join(OUT, 'SHA256SUMS.txt'), `${checksums.join('\n')}\n`, 'utf8');
}

console.log(JSON.stringify({
  total: report.total,
  passed: report.passed,
  failed: report.failed,
  screenshots: report.screenshots,
  evidenceDir: OUT,
}, null, 2));
if (report.failed > 0) process.exitCode = 1;
