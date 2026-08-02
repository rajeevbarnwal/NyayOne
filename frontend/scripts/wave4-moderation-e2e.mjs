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
  const noPublic = await context.request.get(`${API}/api/v1/public/internship-risk/any-organisation`);
  assert('public risk projection absent', noPublic.status() === 404, 'HTTP 404', `HTTP ${noPublic.status()}`);
  await context.close();
}

async function workflow(browser) {
  const context = await authenticatedContext(browser);
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('pageerror', (error) => pageErrors.push(String(error)));
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
  assert('publication stays false in UI', riskText.includes('publication_ready') && riskText.includes('Not public'), 'explicit false/off copy', riskText.slice(-240));
  await page.screenshot({ path: path.join(OUT, 'risk-preview-suppressed-1440x900-light.png'), fullPage: true });
  const browserState = await page.evaluate(() => ({ local: Object.fromEntries(Object.entries(localStorage)), session: Object.fromEntries(Object.entries(sessionStorage)), cookie: document.cookie, url: location.href }));
  const stateText = JSON.stringify(browserState);
  assert('no private narrative/token in browser-readable state', browserState.cookie === '' && !/first-person|opaque-e2e|session-token/i.test(stateText), 'no readable secrets/private narrative', stateText);
  assert('no console/page errors', consoleErrors.length === 0 && pageErrors.length === 0, '0/0', `${consoleErrors.length}/${pageErrors.length}`);
  await context.tracing.stop({ path: path.join(OUT, 'moderation-workflow.zip') });
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
        return { overflow: document.documentElement.scrollWidth - viewportWidth, tiny, culprits };
      });
      record(`geometry ${width}x${height} ${theme}`, 'overflow 0; every target >=44px', JSON.stringify(metrics), metrics.overflow === 0 && metrics.tiny.length === 0);
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
try { await authAndPrivacy(browser); await workflow(browser); await geometryAndA11y(browser); }
catch (error) { report.failures.push(String(error)); }
finally { await browser.close(); }
report.finishedAt = new Date().toISOString();
await writeFile(path.join(OUT, 'results.json'), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ rows: report.rows.length, failures: report.failures }, null, 2));
process.exit(report.failures.length ? 1 : 0);
