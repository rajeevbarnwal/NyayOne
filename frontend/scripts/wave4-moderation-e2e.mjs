/** SAATHI-274 isolated-loopback Chromium, a11y, privacy and workflow gate. */
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import axe from 'axe-core';

const WEB = (process.env.E2E_WEB_URL ?? 'http://127.0.0.1:1270').replace(/\/$/, '');
const API = (process.env.E2E_API_URL ?? 'http://127.0.0.1:1271').replace(/\/$/, '');
const OUT = path.resolve(process.env.E2E_OUTPUT_DIR ?? 'test-results/wave4-moderation-e2e');
const TOKEN = process.env.WAVE4_E2E_SESSION_TOKEN ?? '';
const COOKIE = process.env.AUTH_SESSION_COOKIE_NAME ?? 'legalsaathi_session';
const FIXTURE_REPORTS = Array.from(
  { length: 4 },
  (_, index) => `00000000-0000-4000-8000-${String(2740 + index).padStart(12, '0')}`,
);
const PENDING_REPORT = '00000000-0000-4000-8000-000000002743';
const UNKNOWN_ORGANISATION = '00000000-0000-4000-8000-000000002799';
const PUBLICATION_GATE_OPEN = process.env.WAVE4_E2E_PUBLICATION_GATE_OPEN === 'true';
const report = { startedAt: new Date().toISOString(), web: WEB, api: API, rows: [], failures: [] };

function assertIsolatedLoopback() {
  if (process.env.WAVE4_E2E_ALLOW_RUN !== 'true') throw new Error('WAVE4_E2E_ALLOW_RUN=true is required');
  for (const [label, raw] of [['web', WEB], ['api', API]]) {
    const value = new URL(raw);
    if (value.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(value.hostname)) {
      throw new Error(`${label} must be a loopback-only HTTP URL`);
    }
  }
  if (TOKEN.length < 32) throw new Error('WAVE4_E2E_SESSION_TOKEN with at least 32 characters is required');
}
assertIsolatedLoopback();

function record(name, expected, actual, pass) {
  const row = { name, expected, actual, pass: Boolean(pass) };
  report.rows.push(row);
  if (!row.pass) report.failures.push(`${name}: expected ${expected}; actual ${actual}`);
}
function assert(name, condition, expected, actual) {
  record(name, expected, actual, condition);
  if (!condition) throw new Error(`${name}: expected ${expected}; actual ${actual}`);
}

async function authenticatedContext(browser, viewport = { width: 1440, height: 900 }, colorScheme = 'light') {
  const context = await browser.newContext({ viewport, colorScheme });
  const apiUrl = new URL(API);
  await context.addCookies([{ name: COOKIE, value: TOKEN, domain: apiUrl.hostname, path: '/', httpOnly: true, secure: false, sameSite: 'Lax' }]);
  return context;
}

async function authAndPrivacy(browser) {
  const anonymous = await browser.newContext();
  const anonymousApi = await anonymous.request.get(`${API}/api/v1/moderation/internship-reports`);
  assert('anonymous API denied', anonymousApi.status() === 401, 'HTTP 401', `HTTP ${anonymousApi.status()}`);
  const anonymousPage = await anonymous.newPage();
  await anonymousPage.goto(`${WEB}/moderation/internship-reports`, { waitUntil: 'networkidle' });
  const denied = await anonymousPage.getByRole('heading', { name: 'Moderator sign-in required' }).isVisible();
  const deniedHtml = await anonymousPage.locator('body').innerText();
  assert('anonymous route denies before data mount', denied && !deniedHtml.includes('Nyaya Legal Foundation'), 'denial and zero private data', deniedHtml.slice(0, 160));
  await anonymous.close();

  const context = await authenticatedContext(browser);
  const forged = await context.request.get(`${API}/api/v1/moderation/internship-reports`, { headers: { 'X-Actor-Claims': JSON.stringify({ sub: '00000000-0000-4000-8000-0000000000de', roles: ['student'] }) } });
  assert('server session outranks forged claims header', forged.status() === 200, 'HTTP 200 moderator session', `HTTP ${forged.status()}`);
  const noPublic = await context.request.get(`${API}/api/v1/public/internship-risk-labels/${UNKNOWN_ORGANISATION}`);
  const noPublicBody = await noPublic.json().catch(() => ({}));
  if (PUBLICATION_GATE_OPEN) {
    assert(
      'target-runtime publication seam returns an empty projection for an unknown organisation',
      noPublic.status() === 200 && noPublicBody?.available === true && noPublicBody?.labels?.length === 0,
      'HTTP 200, available=true, labels=[]',
      `HTTP ${noPublic.status()} ${JSON.stringify(noPublicBody)}`,
    );
  } else {
    assert(
      'real public risk projection fails closed while release is disabled',
      noPublic.status() === 503 && ['risk_labels_disabled', 'risk_labels_unavailable'].includes(noPublicBody?.detail?.code) && noPublicBody?.detail?.retryable === false,
      'HTTP 503 risk_labels_disabled|risk_labels_unavailable retryable=false',
      `HTTP ${noPublic.status()} ${JSON.stringify(noPublicBody)}`,
    );
  }
  await context.close();
}

async function workflow(browser) {
  const context = await authenticatedContext(browser);
  // Do not enable Playwright tracing here. The moderator session is carried in
  // an HttpOnly cookie, and traces can serialise cookie values. Screenshots and
  // the structured fail-closed result payload are the deliberately secret-free
  // evidence for this gate.
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const requestFailures = [];
  const httpErrors = [];
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  page.on('requestfailed', (request) => requestFailures.push({ url: request.url(), error: request.failure()?.errorText }));
  page.on('response', (response) => { if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() }); });
  await page.goto(`${WEB}/moderation/internship-reports`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Internship report queue' }).waitFor();
  const fixtureCards = FIXTURE_REPORTS.map((reportId) =>
    page.locator(`.mod-card:has(a[href="/moderation/internship-reports/${reportId}"])`),
  );
  const fixtureCount = (await Promise.all(fixtureCards.map((card) => card.count())))
    .filter((count) => count === 1).length;
  const totalCards = await page.locator('.mod-card').count();
  assert(
    'queue contains all four isolated fixtures amid target-runtime probes',
    fixtureCount === 4,
    '4/4 fixture cards',
    `${fixtureCount}/4 fixtures; ${totalCards} total cards`,
  );
  const queueText = await page.locator('main.mod-shell').innerText();
  assert('queue excludes narratives and reporter identity', !/first-person account|reporter_lookup|00000000-0000-4000-8000-0000000086/i.test(queueText), 'no narrative/identity', queueText.slice(0, 180));
  await page.screenshot({ path: path.join(OUT, 'moderation-queue-1440x900-light.png'), fullPage: true });

  await page.goto(`${WEB}/moderation/internship-reports/${PENDING_REPORT}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Private report review' }).waitFor();
  await page.getByRole('button', { name: 'Claim this case' }).click();
  await page.getByText('under review', { exact: true }).waitFor();
  await page.getByLabel('Decision rationale (10–1,000 characters)').fill('A date-specific supporting record is required before an internal decision.');
  await page.getByRole('button', { name: 'Request information' }).click();
  const confirmation = page.getByRole('alertdialog', { name: 'Confirm moderation action' });
  await confirmation.waitFor();
  const stateBeforeConfirmation = await page.getByText('under review', { exact: true }).isVisible();
  const focusedBeforeConfirmation = await page.evaluate(() => document.activeElement?.textContent?.trim());
  assert('decision requires explicit confirmation before mutation', stateBeforeConfirmation, 'case remains under review before confirmation', String(stateBeforeConfirmation));
  assert('confirmation receives keyboard focus', focusedBeforeConfirmation === 'Go back', 'Go back focused', String(focusedBeforeConfirmation));
  const backgroundIsolation = await page.locator('[data-moderation-background]').evaluate((node) => {
    const target = node.querySelector('button:not(:disabled),a[href],textarea:not(:disabled),select:not(:disabled)');
    target?.focus();
    return {
      inert: node.hasAttribute('inert') && node.inert === true,
      ariaHidden: node.getAttribute('aria-hidden'),
      pointerEvents: getComputedStyle(node).pointerEvents,
      acceptedFocus: target !== null && document.activeElement === target,
    };
  });
  assert(
    'confirmation makes the background pointer- and focus-inert',
    backgroundIsolation.inert && backgroundIsolation.ariaHidden === 'true'
      && backgroundIsolation.pointerEvents === 'none' && !backgroundIsolation.acceptedFocus,
    'inert=true, aria-hidden=true, pointer-events=none, acceptedFocus=false',
    JSON.stringify(backgroundIsolation),
  );
  await page.keyboard.press('Shift+Tab');
  const wrappedBackward = await page.evaluate(() => document.activeElement?.textContent?.trim());
  assert('confirmation Shift+Tab wraps to the last action', wrappedBackward === 'Confirm request more information', 'Confirm request more information focused', String(wrappedBackward));
  await page.keyboard.press('Tab');
  const wrappedForward = await page.evaluate(() => document.activeElement?.textContent?.trim());
  assert('confirmation Tab wraps to the first action', wrappedForward === 'Go back', 'Go back focused', String(wrappedForward));
  await page.screenshot({ path: path.join(OUT, 'moderation-action-confirmation-1440x900-light.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await confirmation.waitFor({ state: 'hidden' });
  const focusReturned = await page.getByRole('button', { name: 'Request information' }).evaluate((node) => node === document.activeElement);
  assert('Escape closes confirmation and restores focus', focusReturned, 'focus returned to Request information', String(focusReturned));
  await page.getByRole('button', { name: 'Request information' }).click();
  await page.getByRole('button', { name: 'Confirm request more information' }).click();
  await page.getByText('needs information', { exact: true }).waitFor();
  record('claim and needs-information lifecycle', 'pending → under review → needs information', 'completed', true);
  await page.screenshot({ path: path.join(OUT, 'moderation-case-needs-information-1440x900-light.png'), fullPage: true });

  await page.goto(`${WEB}/moderation/internship-reports`, { waitUntil: 'networkidle' });
  const checks = FIXTURE_REPORTS.slice(0, 3).map((reportId) =>
    page.locator(
      `.mod-card:has(a[href="/moderation/internship-reports/${reportId}"]) input[type="checkbox"]`,
    ),
  );
  const availableChecks = (await Promise.all(checks.map((check) => check.count())))
    .filter((count) => count === 1).length;
  assert('three fixture aggregate-approved cluster candidates', availableChecks === 3, '3', String(availableChecks));
  for (const check of checks) await check.check();
  await page.getByRole('button', { name: /Build privacy-safe preview \(3\)/ }).click();
  await page.waitForURL(/\/moderation\/risk-clusters\//);
  await page.getByRole('heading', { name: 'Privacy-safe risk preview' }).waitFor();
  await page.getByText('Public publication kill-switch: OFF').waitFor();
  const riskText = await page.locator('main.mod-shell').innerText();
  assert('threshold three and small-count suppression', riskText.includes('3\nsource reports') && riskText.includes('Suppressed\npublic count'), '3 reports and Suppressed', riskText.slice(0, 240));
  assert(
    'publication stays false behind the truthful remaining approval boundary',
    riskText.includes('publication_ready') && riskText.includes('Not public')
      && riskText.includes('SAATHI-279 implementation and Product-approved safe defaults are complete')
      && riskText.includes('SAATHI-452 records Counsel/Policy and Security/Privacy approval')
      && !riskText.includes('until SAATHI-279 and SAATHI-452 receive'),
    'SAATHI-279/Product complete; SAATHI-452 external approvals and target gates remain',
    riskText.slice(-420),
  );
  await page.screenshot({ path: path.join(OUT, 'risk-preview-suppressed-1440x900-light.png'), fullPage: true });
  const browserState = await page.evaluate(() => ({ local: Object.fromEntries(Object.entries(localStorage)), session: Object.fromEntries(Object.entries(sessionStorage)), cookie: document.cookie, url: location.href }));
  const stateText = JSON.stringify(browserState);
  assert('no private narrative/token in browser-readable state', browserState.cookie === '' && !/first-person|opaque-e2e|session-token/i.test(stateText), 'no readable secrets/private narrative', stateText);
  assert('no console/page/request/HTTP errors', consoleErrors.length === 0 && pageErrors.length === 0 && requestFailures.length === 0 && httpErrors.length === 0, '0/0/0/0', `${consoleErrors.length}/${pageErrors.length}/${requestFailures.length}/${httpErrors.length}`);
  await context.close();
}

async function emptyQueue(browser) {
  const context = await authenticatedContext(browser);
  const page = await context.newPage();
  await page.route('**/api/v1/moderation/internship-reports', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) });
  });
  await page.goto(`${WEB}/moderation/internship-reports`, { waitUntil: 'networkidle' });
  await page.getByTestId('moderation-empty').waitFor();
  const cards = await page.locator('.mod-card').count();
  const text = await page.getByTestId('moderation-empty').innerText();
  assert('empty queue renders truthful server-empty state', cards === 0 && /No reports need moderation/.test(text), '0 cards and explicit empty copy', `${cards} cards; ${text}`);
  await page.screenshot({ path: path.join(OUT, 'moderation-queue-empty-1440x900-light.png'), fullPage: true });
  await context.close();
}

async function geometryAndA11y(browser) {
  for (const [width, height] of [[390, 844], [430, 932], [768, 1024], [1024, 768], [1440, 900]]) {
    for (const theme of ['light', 'dark']) {
      const context = await authenticatedContext(browser, { width, height }, theme);
      const page = await context.newPage();
      await page.goto(`${WEB}/moderation/internship-reports`, { waitUntil: 'networkidle' });
      await page.getByRole('heading', { name: 'Internship report queue' }).waitFor();
      const metrics = await page.evaluate(() => {
        const viewportWidth = document.documentElement.clientWidth;
        const tiny = [...document.querySelectorAll('button,a,input,select,textarea')].flatMap((node) => {
          const style = getComputedStyle(node);
          if (style.display === 'none' || style.visibility === 'hidden') return [];
          const target = node instanceof HTMLInputElement && node.type === 'checkbox' ? node.closest('label') ?? node : node;
          const rect = target.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44) ? [{ name: node.getAttribute('aria-label') || node.textContent?.trim() || node.id, width: rect.width, height: rect.height }] : [];
        });
        const culprits = [...document.querySelectorAll('body *')].flatMap((node) => {
          const rect = node.getBoundingClientRect();
          if (rect.width <= 0 || rect.height <= 0 || (rect.right <= viewportWidth + 0.5 && rect.left >= -0.5)) return [];
          return [{ tag: node.tagName.toLowerCase(), className: String(node.className).slice(0, 100), left: rect.left, right: rect.right, width: rect.width }];
        }).slice(0, 12);
        const clipped = [...document.querySelectorAll('[data-screen="MOD-01"] *')].flatMap((node) => {
          const rect = node.getBoundingClientRect();
          if (rect.width <= 0 || rect.height <= 0) return [];
          let parent = node.parentElement;
          while (parent && parent !== document.body) {
            const style = getComputedStyle(parent);
            if (/(hidden|clip)/.test(`${style.overflow}${style.overflowX}${style.overflowY}`)) {
              const boundary = parent.getBoundingClientRect();
              if (rect.left < boundary.left - 1 || rect.right > boundary.right + 1 || rect.top < boundary.top - 1 || rect.bottom > boundary.bottom + 1) {
                return [{ child: node.tagName.toLowerCase(), childClass: String(node.className).slice(0, 80), parent: parent.tagName.toLowerCase(), parentClass: String(parent.className).slice(0, 80) }];
              }
            }
            parent = parent.parentElement;
          }
          return [];
        }).slice(0, 12);
        return { overflow: document.documentElement.scrollWidth - viewportWidth, tiny, culprits, clipped };
      });
      record(`geometry ${width}x${height} ${theme}`, 'overflow 0; every target >=44px; no clipped descendants', JSON.stringify(metrics), metrics.overflow === 0 && metrics.tiny.length === 0 && metrics.clipped.length === 0);
      if (width === 390 || width === 1440) {
        await page.addScriptTag({ content: axe.source });
        const violations = await page.evaluate(async () => (await globalThis.axe.run(document.querySelector('[data-screen="MOD-01"]'), { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] } })).violations.map((item) => ({ id: item.id, impact: item.impact, targets: item.nodes.map((node) => node.target) })));
        record(`axe ${width}x${height} ${theme}`, '0 WCAG A/AA violations', JSON.stringify(violations), violations.length === 0);
      }
      await page.screenshot({ path: path.join(OUT, `moderation-queue-${width}x${height}-${theme}.png`), fullPage: true });
      await context.close();
    }
  }
}

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ headless: true });
try { await authAndPrivacy(browser); await emptyQueue(browser); await workflow(browser); await geometryAndA11y(browser); }
catch (error) { report.failures.push(String(error)); }
finally { await browser.close(); }
report.finishedAt = new Date().toISOString();
await writeFile(path.join(OUT, 'results.json'), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ rows: report.rows.length, failures: report.failures }, null, 2));
process.exit(report.failures.length ? 1 : 0);
