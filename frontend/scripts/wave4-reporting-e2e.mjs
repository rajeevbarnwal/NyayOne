/**
 * SAATHI-269 reporter-owned private internship reporting browser/API gate.
 * Preconditions: migrated backend, seeded E2E actors and built/served frontend.
 */
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium, request as playwrightRequest } from 'playwright';
import axe from 'axe-core';
import { validWave4StudentSession } from './lib/wave4-session-validator.mjs';

const WEB = (process.env.E2E_WEB_URL ?? 'http://127.0.0.1:1260').replace(/\/$/, '');
const API = (process.env.E2E_API_URL ?? 'http://127.0.0.1:1261').replace(/\/$/, '');
const OUT = path.resolve(process.env.E2E_OUTPUT_DIR ?? 'test-results/wave4-reporting-e2e');
const ACTOR_A = '00000000-0000-4000-8000-0000000000de';
const ACTOR_B = '00000000-0000-4000-8000-0000000000b2';
const STUDENT_SESSION_TOKEN = process.env.WAVE4_E2E_STUDENT_SESSION_TOKEN ?? '';
const COOKIE = process.env.AUTH_SESSION_COOKIE_NAME ?? 'nyayone_session';
const claims = (sub = ACTOR_A, roles = ['student']) => ({
  'X-Actor-Claims': JSON.stringify({ sub, roles }),
});
const report = {
  startedAt: new Date().toISOString(),
  web: WEB,
  api: API,
  rows: [],
  failures: [],
  failureClass: null,
  failureStage: null,
  currentPath: null,
};
let failureStage = 'environment';
let activePage = null;

function diagnosticSummary(value) {
  return {
    present: value !== null && value !== undefined && value !== '',
    kind: Array.isArray(value) ? 'array' : typeof value,
    itemCount: Array.isArray(value)
      ? value.length
      : value && typeof value === 'object'
        ? Object.keys(value).length
        : undefined,
  };
}

function record(name, expected, actual, pass, extra = {}) {
  const row = {
    name,
    expectedCategory: diagnosticSummary(expected),
    actualSummary: diagnosticSummary(actual),
    pass: Boolean(pass),
    ...extra,
  };
  report.rows.push(row);
  if (!row.pass) {
    const failure = {
      name,
      diagnostic: row.actualSummary,
      failureClass: 'assertion_failure',
      failureStage,
      currentPath: safeCurrentPath(),
    };
    report.failures.push(failure);
    if (report.failureClass === null) {
      report.failureClass = failure.failureClass;
      report.failureStage = failure.failureStage;
      report.currentPath = failure.currentPath;
    }
  }
  return row;
}

function assert(name, condition, expected, actual, extra) {
  record(name, expected, actual, condition, extra);
  if (!condition) throw new Error(`${name}: expected ${expected}; actual ${actual}`);
}

function safeFailureClass(error) {
  const name = typeof error?.name === 'string' ? error.name : '';
  if (/timeout/iu.test(name)) return 'timeout';
  return error instanceof Error ? 'runtime_error' : 'unknown_error';
}

function safeCurrentPath() {
  if (activePage === null) return null;
  try {
    const pathname = new URL(activePage.url()).pathname;
    return new Set(['/s-03', '/s-86', '/s-87']).has(pathname) ? pathname : null;
  } catch {
    return null;
  }
}

async function cookieFreeRequestContext() {
  return playwrightRequest.newContext({ baseURL: API });
}

async function authenticatedStudentContext(browser, options = {}) {
  const context = await browser.newContext(options);
  const apiUrl = new URL(API);
  await context.addCookies([{
    name: COOKIE, value: STUDENT_SESSION_TOKEN,
    domain: apiUrl.hostname, path: '/api/v1', httpOnly: true,
    secure: apiUrl.protocol === 'https:', sameSite: 'Strict',
  }]);
  const session = await context.request.get(`${API}/api/v1/auth/student/session`);
  const body = await session.json().catch(() => null);
  if (session.status() !== 200 || !validWave4StudentSession(body, ACTOR_A)) {
    await context.close();
    throw new Error('WAVE4_STUDENT_SESSION_FIXTURE_INVALID');
  }
  return context;
}

function embeddedEicarPdf() {
  const eicar = Buffer.from(
    'X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*',
    'ascii',
  );
  const objects = [
    Buffer.from('<< /Type /Catalog /Pages 4 0 R /Names << /EmbeddedFiles << /Names [(eicar.com) 2 0 R] >> >> >>', 'ascii'),
    Buffer.from('<< /Type /Filespec /F (eicar.com) /UF (eicar.com) /EF << /F 3 0 R /UF 3 0 R >> >>', 'ascii'),
    Buffer.concat([
      Buffer.from(`<< /Type /EmbeddedFile /Length ${eicar.length} >>\nstream\n`, 'ascii'),
      eicar,
      Buffer.from('\nendstream', 'ascii'),
    ]),
    Buffer.from('<< /Type /Pages /Kids [] /Count 0 >>', 'ascii'),
  ];
  const chunks = [Buffer.from('%PDF-1.7\n', 'ascii')];
  const offsets = [];
  for (const [index, body] of objects.entries()) {
    offsets.push(chunks.reduce((total, chunk) => total + chunk.length, 0));
    chunks.push(Buffer.from(`${index + 1} 0 obj\n`, 'ascii'), body, Buffer.from('\nendobj\n', 'ascii'));
  }
  const xrefOffset = chunks.reduce((total, chunk) => total + chunk.length, 0);
  chunks.push(Buffer.from(
    `xref\n0 5\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}`
      + `trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`,
    'ascii',
  ));
  return Buffer.concat(chunks);
}

async function apiCase(request, { name, method = 'post', route = '', headers = claims(), data, multipart, status, code, contains }) {
  const response = await request[method](`${API}/api/v1/internship-reports${route}`, { headers, data, multipart });
  const body = await response.json().catch(() => ({}));
  const actualCode = body?.detail?.code;
  const encoded = JSON.stringify(body);
  const pass = response.status() === status
    && (code === undefined || actualCode === code)
    && (contains === undefined || encoded.includes(contains));
  record(name, `${status}${code ? ` ${code}` : ''}`, `${response.status()}${actualCode ? ` ${actualCode}` : ''}`, pass);
  if (!pass) throw new Error(`${name}: ${response.status()} ${JSON.stringify(body)}`);
  return body;
}

async function negativeApiRequests(request) {
  await apiCase(request, { name: 'anonymous list rejected', method: 'get', headers: {}, status: 401, code: 'authentication_required' });
  await apiCase(request, { name: 'wrong role rejected', method: 'get', headers: claims(ACTOR_A, ['lawyer']), status: 403, code: 'student_role_required' });
  await apiCase(request, {
    name: 'future historical date rejected',
    headers: { ...claims(), 'Idempotency-Key': `future-${Date.now()}` },
    data: { experience_start_date: '2030-01-01' },
    status: 422,
    code: 'validation_error',
    contains: 'future_experience_start_date',
  });
  const draft = await apiCase(request, {
    name: 'minimal draft allowed',
    headers: { ...claims(), 'Idempotency-Key': `missing-${Date.now()}` },
    data: {},
    status: 201,
  });
  await apiCase(request, {
    name: 'empty submission rejected',
    route: `/${draft.id}/submit`,
    data: { expected_version: draft.version },
    status: 422,
    code: 'organisation_required',
  });
  await apiCase(request, {
    name: 'cross-user report is non-enumerating',
    method: 'get',
    route: `/${draft.id}`,
    headers: claims(ACTOR_B),
    status: 404,
    code: 'internship_report_not_found',
  });
  const infectedDraft = await apiCase(request, {
    name: 'malware-test draft created',
    headers: { ...claims(), 'Idempotency-Key': `malware-${Date.now()}` },
    data: {},
    status: 201,
  });
  const eicar = embeddedEicarPdf();
  await apiCase(request, {
    name: 'malware evidence rejected',
    route: `/${infectedDraft.id}/evidence`,
    multipart: {
      expected_version: String(infectedDraft.version),
      file: { name: 'eicar-proof.pdf', mimeType: 'application/pdf', buffer: eicar },
    },
    status: 422,
    code: 'infected_evidence',
  });
}

async function negativeApiMatrix(browser) {
  void browser;
  const negativeContext = await cookieFreeRequestContext();
  try {
    await negativeApiRequests(negativeContext);
  } finally {
    await negativeContext.dispose();
  }
}

async function positiveJourney(browser) {
  failureStage = 'positive_session';
  activePage = null;
  const context = await authenticatedStudentContext(browser, { viewport: { width: 1440, height: 900 } });
  // A browser trace would retain the private narrative and cookie-auth requests.
  // Upload only the sanitized assertion report and screenshots.
  const page = await context.newPage();
  activePage = page;
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('pageerror', (error) => pageErrors.push(String(error)));

  failureStage = 'positive_s86_mount';
  await page.goto(`${WEB}/s-86`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Share an internship experience safely' }).waitFor();
  await page.screenshot({ path: path.join(OUT, 's86-empty-1440x900-light.png'), fullPage: true });

  failureStage = 'positive_empty_validation';
  await page.getByRole('button', { name: 'Submit privately' }).click();
  await page.getByText('Enter the organisation name.').waitFor();
  await page.getByText('Enter the listing or application reference.').waitFor();
  await page.getByText('Choose at least one category.').waitFor();
  record('UI empty required fields', 'submission blocked with explicit field errors', 'blocked with errors', true);

  failureStage = 'positive_boundary_validation';
  await page.getByLabel('Organisation name').fill('Example Chambers');
  await page.getByLabel('Listing or application reference').fill('APP-W4-2026-001');
  await page.getByLabel('Experience start date').fill('2030-01-01');
  await page.getByLabel('Experience end date').fill('2030-01-02');
  await page.getByLabel('Positive experience').check();
  await page.getByLabel('Your private account').fill('x'.repeat(49));
  await page.getByLabel(/I consent to NyayOne/).check();
  await page.getByRole('button', { name: 'Submit privately' }).click();
  await page.getByText('The start date cannot be in the future.').waitFor();
  await page.getByText('Use 50–5,000 characters for the factual account.').waitFor();
  record('UI future date and 49-char narrative', 'both rejected', 'both rejected', true);

  failureStage = 'positive_submit';
  await page.getByLabel('Experience start date').fill('2026-01-01');
  await page.getByLabel('Experience end date').fill('2026-01-31');
  await page.getByLabel('Your private account').fill('The organisation provided structured supervision, timely feedback and work that matched the published internship description.');
  await page.getByLabel('ir-evidence').setInputFiles({
    name: 'private-proof.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7\nprivate-report-evidence'),
  }).catch(async () => page.locator('#ir-evidence').setInputFiles({
    name: 'private-proof.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.7\nprivate-report-evidence'),
  }));
  const submit = page.waitForResponse((response) => response.url().endsWith('/submit') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Submit privately' }).click();
  assert('submit HTTP', (await submit).status() === 200, 'HTTP 200', 'HTTP 200');
  failureStage = 'positive_s87_mount';
  await page.waitForURL(/\/s-87\?report=/);
  await page.getByText('Submitted privately for moderation.').first().waitFor();
  await page.screenshot({ path: path.join(OUT, 's87-submitted-1440x900-light.png'), fullPage: true });

  const reportId = new URL(page.url()).searchParams.get('report');
  assert('opaque report status route', /^[0-9a-f-]{36}$/.test(reportId ?? ''), 'UUID report reference', String(reportId));
  failureStage = 'positive_cross_user';
  const crossUserContext = await cookieFreeRequestContext();
  try {
    const crossUser = await crossUserContext.get(
      `${API}/api/v1/internship-reports/${reportId}/status`,
      { headers: claims(ACTOR_B) },
    );
    assert('cross-user status non-enumeration', crossUser.status() === 404, 'HTTP 404', `HTTP ${crossUser.status()}`);
  } finally {
    await crossUserContext.dispose();
  }

  failureStage = 'positive_privacy';
  const storage = await page.evaluate(() => ({
    local: Object.fromEntries(Object.entries(localStorage)),
    session: Object.fromEntries(Object.entries(sessionStorage)), cookies: document.cookie,
    horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }));
  assert('no horizontal overflow', storage.horizontalOverflow === 0, '0 px', `${storage.horizontalOverflow} px`);
  const localKeys = Object.keys(storage.local);
  const storageText = JSON.stringify({ local: storage.local, session: storage.session });
  const noPrivateData = Object.keys(storage.session).length === 0
    && localKeys.every((key) => key === 'nyayone.theme.v1')
    && !/Example Chambers|APP-W4|private-proof|organisationName|narrative|reportId/i.test(storageText);
  assert(
    'no reporting data in browser storage',
    noPrivateData,
    'theme preference only; no report fields',
    JSON.stringify({
      localKeys,
      sessionKeys: Object.keys(storage.session),
      privateDataDetected: !noPrivateData,
    }),
  );
  assert(
    'no readable auth/report cookie',
    !storage.cookies,
    'empty document.cookie',
    storage.cookies ? 'cookie-present-redacted' : 'empty',
  );
  assert('no console/page errors', consoleErrors.length === 0 && pageErrors.length === 0, '0/0', `${consoleErrors.length}/${pageErrors.length}`);
  await context.close();
  activePage = null;
}

async function geometryMatrix(browser) {
  for (const [width, height] of [[390, 844], [430, 932], [768, 1024], [1024, 768], [1440, 900]]) {
    for (const theme of ['light', 'dark']) {
      failureStage = `geometry_session_${width}x${height}_${theme}`;
      activePage = null;
      const context = await authenticatedStudentContext(
        browser,
        { viewport: { width, height }, colorScheme: theme },
      );
      const page = await context.newPage();
      activePage = page;
      failureStage = `geometry_mount_${width}x${height}_${theme}`;
      await page.goto(`${WEB}/s-86`, { waitUntil: 'networkidle' });
      await page.getByRole('heading', { name: 'Share an internship experience safely' }).waitFor();
      failureStage = `geometry_assert_${width}x${height}_${theme}`;
      const metrics = await page.evaluate(() => {
        const interactive = [...document.querySelectorAll('button,a,input,textarea')].filter((node) => {
          const style = getComputedStyle(node); return style.visibility !== 'hidden' && style.display !== 'none';
        });
        const mobileNav = document.querySelector('.ls-bnav');
        const navRect = mobileNav?.getBoundingClientRect();
        const occludedByNav = navRect && navRect.width > 0 && navRect.height > 0
          ? interactive.flatMap((node) => {
            const rect = node.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            const scrollRegion = node.closest('.ls-content');
            const scrollRect = scrollRegion?.getBoundingClientRect();
            const centerInsideScrollRegion = !scrollRect
              || (centerX >= scrollRect.left && centerX <= scrollRect.right
                && centerY >= scrollRect.top && centerY <= scrollRect.bottom);
            const centerObscured = rect.width > 0 && rect.height > 0
              && !mobileNav.contains(node)
              && centerInsideScrollRegion
              && centerX >= navRect.left && centerX <= navRect.right
              && centerY >= navRect.top && centerY <= navRect.bottom;
            return centerObscured ? [node.getAttribute('aria-label') || node.textContent?.trim() || node.id] : [];
          })
          : [];
        const tiny = interactive.map((node) => {
          const input = node instanceof HTMLInputElement ? node : null;
          const target = input && ['checkbox', 'radio', 'file'].includes(input.type)
            ? input.closest('label') ?? input
            : node;
          return { name: node.getAttribute('aria-label') || node.textContent?.trim() || node.id || input?.name, rect: target.getBoundingClientRect() };
        })
          .filter(({ rect }) => rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44));
        return {
          overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          tiny: tiny.map(({ name, rect }) => ({ name, width: rect.width, height: rect.height })),
          occludedByNav,
          publicActions: [...document.querySelectorAll('button,a')].filter((node) => /publish|public score|risk label/i.test(node.textContent ?? '')).length,
        };
      });
      record(`geometry ${width}x${height} ${theme}`, 'overflow 0, targets >=44, nav center occlusion 0, public actions 0', JSON.stringify(metrics), metrics.overflow === 0 && metrics.tiny.length === 0 && metrics.occludedByNav.length === 0 && metrics.publicActions === 0);
      if (width === 390 || width === 1440) {
        await page.addScriptTag({ content: axe.source });
        const violations = await page.evaluate(async () => {
          const feature = document.querySelector('[data-screen="S-86"]');
          if (!feature) throw new Error('S-86 feature root missing');
          const result = await globalThis.axe.run(feature, {
            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
          });
          return result.violations.map((violation) => ({
            id: violation.id,
            impact: violation.impact,
            targets: violation.nodes.slice(0, 3).map((node) => node.target),
          }));
        });
        record(`axe ${width}x${height} ${theme}`, '0 WCAG A/AA violations', JSON.stringify(violations), violations.length === 0);
      }
      await page.screenshot({ path: path.join(OUT, `s86-${width}x${height}-${theme}.png`), fullPage: true });
      await context.close();
      activePage = null;
    }
  }
}

await mkdir(OUT, { recursive: true });
let browser = null;
try {
  if (STUDENT_SESSION_TOKEN.length < 32) {
    throw new Error('WAVE4_E2E_STUDENT_SESSION_TOKEN with at least 32 characters is required');
  }
  browser = await chromium.launch({ headless: true });
  failureStage = 'negative_api_matrix';
  await negativeApiMatrix(browser);
  await positiveJourney(browser);
  await geometryMatrix(browser);
  failureStage = null;
  activePage = null;
} catch (error) {
  const failure = {
    category: 'qa-error',
    failureClass: safeFailureClass(error),
    failureStage,
    currentPath: safeCurrentPath(),
  };
  if (report.failureClass === null) {
    report.failureClass = failure.failureClass;
    report.failureStage = failure.failureStage;
    report.currentPath = failure.currentPath;
  }
  report.rows.push({
    name: 'runner completed',
    expectedCategory: diagnosticSummary('all stages completed'),
    actualSummary: diagnosticSummary(error),
    pass: false,
    ...failure,
  });
  report.failures.push(failure);
} finally {
  await browser?.close();
}
report.finishedAt = new Date().toISOString();
await writeFile(path.join(OUT, 'results.json'), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({
  rows: report.rows.length,
  failedCount: report.failures.length,
  failureClass: report.failureClass,
  failureStage: report.failureStage,
  currentPath: report.currentPath,
}, null, 2));
process.exit(report.failures.length ? 1 : 0);
