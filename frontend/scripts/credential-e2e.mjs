/**
 * SAATHI-253 / SAATHI-258 real-browser closure gate.
 *
 * Preconditions: real frontend + backend + PostgreSQL 16 are running and the
 * deterministic Wave 3 actors/issuer were provisioned. All assertions use
 * public HTTP/browser boundaries; no React state or database shortcut.
 */
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const WEB = (process.env.E2E_WEB_URL ?? 'http://127.0.0.1:1170').replace(/\/$/, '');
const API = (process.env.E2E_API_URL ?? 'http://127.0.0.1:1171').replace(/\/$/, '');
const OUT = path.resolve(process.env.E2E_OUTPUT_DIR ?? 'test-results/credential-e2e');
const STUDENT_ID = '00000000-0000-4000-8000-0000000000de';
const ISSUER_ID = '00000000-0000-4000-8000-000000000253';
const STUDENT_HEADERS = {
  'X-Actor-Claims': JSON.stringify({ sub: STUDENT_ID, roles: ['student'] }),
};
const VIEWPORTS = [
  [390, 844],
  [430, 932],
  [768, 1024],
  [1024, 768],
  [1440, 900],
];
const THEMES = ['light', 'dark'];
const report = {
  webUrl: WEB,
  apiUrl: API,
  startedAt: new Date().toISOString(),
  functional: [],
  negative: [],
  geometry: [],
  privacy: {},
  failures: [],
};

function record(group, name, expected, actual, pass, extra = {}) {
  const row = { name, expected, actual, pass, ...extra };
  report[group].push(row);
  if (!pass) report.failures.push(`${group}:${name}: expected ${expected}; actual ${actual}`);
  return row;
}

function check(group, name, condition, expected, actual, extra) {
  record(group, name, expected, actual, Boolean(condition), extra);
  if (!condition) throw new Error(`${name}: expected ${expected}; actual ${actual}`);
}

async function apiCase(request, {
  name, method = 'post', route, headers = STUDENT_HEADERS, data, multipart,
  expectedStatus, expectedCode,
}) {
  const response = await request[method](`${API}${route}`, {
    headers,
    data,
    multipart,
  });
  const body = await response.json().catch(() => ({}));
  const code = body?.detail?.code;
  const pass = response.status() === expectedStatus
    && (expectedCode === undefined || code === expectedCode)
    && !JSON.stringify(body).includes('"input"');
  record(
    'negative',
    name,
    `${expectedStatus}${expectedCode ? ` ${expectedCode}` : ''}`,
    `${response.status()}${code ? ` ${code}` : ''}`,
    pass,
  );
  if (!pass) throw new Error(`${name} failed: ${response.status()} ${JSON.stringify(body)}`);
  return { response, body };
}

async function clearWallet(request) {
  const listed = await request.get(`${API}/api/v1/credentials?page=1&page_size=50`, {
    headers: STUDENT_HEADERS,
  });
  if (!listed.ok()) throw new Error(`wallet cleanup list failed: ${listed.status()}`);
  for (const item of (await listed.json()).items) {
    const removed = await request.delete(`${API}/api/v1/credentials/${item.id}`, {
      headers: STUDENT_HEADERS,
    });
    if (!removed.ok()) throw new Error(`wallet cleanup delete failed: ${removed.status()}`);
  }
}

async function runApiNegativeMatrix(request) {
  const base = {
    title: 'Valid credential',
    credential_type: 'certificate',
    issue_date: '2026-01-15',
    expiry_date: '2028-01-15',
    issuer_id: ISSUER_ID,
  };
  const create = (
    name,
    patch,
    status = 422,
    code = status === 422 ? 'validation_error' : undefined,
  ) => apiCase(request, {
    name,
    route: '/api/v1/credentials',
    headers: { ...STUDENT_HEADERS, 'Idempotency-Key': `negative-${name.replace(/\W+/g, '-')}` },
    data: { ...base, ...patch },
    expectedStatus: status,
    expectedCode: code,
  });
  await create('title whitespace', { title: '   ' });
  await create('title one below minimum', { title: 'A' });
  const atMinimum = await create('title at minimum', { title: 'AB' }, 201, undefined);
  await create('title at maximum', { title: 'T'.repeat(160) }, 201, undefined);
  await create('title above maximum', { title: 'T'.repeat(161) });
  await create('title unsafe markup', { title: '<script>alert(1)</script>' });
  await create('title control character', { title: 'Good\u0007Title' });
  await create('future issue date', { issue_date: '2030-01-01' });
  await create('expiry before issue', { expiry_date: '2025-01-01' });
  await create('unsupported credential type', { credential_type: 'wizard_badge' });
  await create('identifier above maximum', { identifier: 'I'.repeat(121) });
  await create('malformed issuer UUID', { issuer_id: 'not-a-uuid' });
  await create(
    'unknown issuer UUID',
    { issuer_id: '00000000-0000-4000-8000-000000000999' },
    422,
    'issuer_not_found',
  );
  await apiCase(request, {
    name: 'wallet anonymous',
    method: 'get',
    route: '/api/v1/credentials',
    headers: {},
    expectedStatus: 401,
    expectedCode: 'authentication_required',
  });
  await apiCase(request, {
    name: 'wallet wrong role',
    method: 'get',
    route: '/api/v1/credentials',
    headers: {
      'X-Actor-Claims': JSON.stringify({
        sub: '00000000-0000-4000-8000-0000000000c3',
        roles: ['lawyer'],
      }),
    },
    expectedStatus: 403,
    expectedCode: 'student_role_required',
  });
  await apiCase(request, {
    name: 'malformed public token',
    method: 'get',
    route: '/api/v1/public/credential-verifications/not-a-token',
    headers: {},
    expectedStatus: 404,
    expectedCode: 'verification_not_found',
  });
  await apiCase(request, {
    name: 'unknown well-formed public token',
    method: 'get',
    route: `/api/v1/public/credential-verifications/${'A'.repeat(43)}`,
    headers: {},
    expectedStatus: 404,
    expectedCode: 'verification_not_found',
  });

  // Remove the two valid boundary records so the UI happy path starts empty.
  for (const id of [atMinimum.body.id]) {
    await request.delete(`${API}/api/v1/credentials/${id}`, { headers: STUDENT_HEADERS });
  }
  const remaining = await request.get(`${API}/api/v1/credentials?page=1&page_size=50`, {
    headers: STUDENT_HEADERS,
  });
  for (const item of (await remaining.json()).items) {
    await request.delete(`${API}/api/v1/credentials/${item.id}`, {
      headers: STUDENT_HEADERS,
    });
  }
}

async function positiveJourney(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  const badResponses = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  page.on('response', (response) => {
    if (response.status() >= 400) badResponses.push({
      status: response.status(),
      url: response.url(),
    });
  });
  await clearWallet(context.request);
  await runApiNegativeMatrix(context.request);

  await page.goto(`${WEB}/s-82`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Build a credible portfolio' }).waitFor();
  record('functional', 'S-82 empty wallet', 'empty state visible', 'visible', true);

  await page.getByRole('link', { name: 'Add first credential' }).click();
  await page.getByRole('heading', { name: 'Add a credential' }).waitFor();
  await page.getByRole('button', { name: 'Save credential' }).click();
  await page.getByRole('alert').filter({ hasText: 'Title must contain 2–160 characters.' }).waitFor();
  record('functional', 'S-83 empty title', 'blocked with 2–160 error', 'blocked', true);

  await page.getByLabel('Credential title').fill('A');
  await page.getByRole('button', { name: 'Save credential' }).click();
  await page.getByRole('alert').filter({ hasText: 'Title must contain 2–160 characters.' }).waitFor();
  record('functional', 'S-83 one-character title', 'blocked', 'blocked', true);

  await page.getByLabel('Credential title').fill('Advanced Moot Court Certificate');
  await page.getByLabel('Credential type').selectOption('moot_achievement');
  await page.getByLabel('Issue date').fill('2030-01-01');
  await page.getByRole('button', { name: 'Save credential' }).click();
  await page.getByRole('alert').filter({ hasText: 'Issue date must be today or earlier.' }).waitFor();
  record('functional', 'S-83 future issue date', 'blocked', 'blocked', true);

  await page.getByLabel('Issue date').fill('2026-01-15');
  await page.getByLabel('Expiry date').fill('2028-01-15');
  await page.getByLabel('Issuer').selectOption(ISSUER_ID);
  await page.getByLabel('Credential identifier').fill('CERT-PRIVATE-2026-0007');
  await page.getByLabel('Choose evidence').setInputFiles({
    name: 'moot-certificate.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.7\ncredential-e2e-private-marker'),
  });
  await page.getByRole('button', { name: 'Save credential' }).click();
  await page.waitForURL(/\/s-84\?credential=/);
  const credentialId = new URL(page.url()).searchParams.get('credential');
  check('functional', 'S-83 persisted ID', Boolean(credentialId), 'opaque credential ID', String(credentialId));
  await page.getByText('pending verification', { exact: true }).waitFor();

  const verifyResponse = page.waitForResponse(
    (response) => response.url().includes(`/issuer/credentials/${credentialId}/verify`)
      && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Verify credential' }).click();
  check('functional', 'issuer verify HTTP', (await verifyResponse).status() === 200, 'HTTP 200', 'HTTP 200');
  await page.getByText('verified', { exact: true }).waitFor();

  await page.getByRole('link', { name: 'Create share link' }).click();
  await page.waitForURL(/\/s-85\?credential=/);
  await page.getByLabel('Include my name (explicit consent)').check();
  const tokenResponsePromise = page.waitForResponse(
    (response) => response.url().includes('/verification-tokens')
      && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create QR & secure link' }).click();
  const tokenResponse = await tokenResponsePromise;
  const tokenBody = await tokenResponse.json();
  await page.getByRole('img', { name: /QR code for https:/ }).waitFor();
  check(
    'functional',
    'S-85 HTTPS opaque QR URL',
    /^https:\/\/.+\/verify\/[A-Za-z0-9_-]{43}$/.test(tokenBody.verification_url),
    'HTTPS /verify/{43-char opaque token}',
    'HTTPS /verify/[REDACTED-43-CHAR-OPAQUE-TOKEN]',
  );

  const publicPath = new URL(tokenBody.verification_url).pathname;
  await page.goto(`${WEB}${publicPath}`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Advanced Moot Court Certificate' }).waitFor();
  check(
    'functional',
    'public route excludes authenticated shell',
    (await page.locator('.ls-shell').count()) === 0,
    'no authenticated navigation',
    `${await page.locator('.ls-shell').count()} shells`,
  );
  const publicText = await page.locator('body').innerText();
  check(
    'functional',
    'public projection privacy',
    !/CERT-PRIVATE|credential-e2e-private-marker/i.test(publicText)
      && (await page.getByRole('link', { name: /download evidence/i }).count()) === 0,
    'no private evidence/identifier',
    'private values absent',
  );

  const storage = await page.evaluate(() => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }));
  const storageDump = JSON.stringify(storage);
  const forbidden = [
    'Advanced Moot Court Certificate',
    'CERT-PRIVATE-2026-0007',
    tokenBody.token,
    'credential-e2e-private-marker',
  ];
  const storageClean = forbidden.every((value) => !storageDump.includes(value));
  report.privacy.browserStorage = {
    pass: storageClean,
    keys: {
      local: Object.keys(storage.local),
      session: Object.keys(storage.session),
    },
  };
  if (!storageClean) report.failures.push('privacy:browser storage contains credential data');

  check(
    'functional',
    'positive browser console',
    consoleErrors.length === 0 && pageErrors.length === 0,
    'zero console/page errors',
    `${consoleErrors.length} console, ${pageErrors.length} page`,
    { consoleErrors, pageErrors },
  );
  const unexpected = badResponses.filter(({ url }) => !url.includes('not-a-token'));
  // Negative API calls use APIRequestContext and therefore do not enter page events.
  check(
    'functional',
    'positive browser network',
    unexpected.length === 0,
    'zero unexpected 4xx/5xx',
    JSON.stringify(unexpected),
  );

  await context.tracing.stop({ path: path.join(OUT, 'positive-journey-trace.zip') });
  await context.close();
  return { credentialId, tokenBody, publicPath };
}

async function geometryMatrix(browser, credentialId) {
  for (const [width, height] of VIEWPORTS) {
    for (const theme of THEMES) {
      const context = await browser.newContext({ viewport: { width, height } });
      await context.addInitScript((mode) => localStorage.setItem('ls-theme', mode), theme);
      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      });
      page.on('pageerror', (error) => pageErrors.push(String(error)));
      const routes = [
        ['s82', '/s-82'],
        ['s83', '/s-83'],
        ['s84', `/s-84?credential=${credentialId}`],
      ];
      for (const [name, route] of routes) {
        await page.goto(`${WEB}${route}`, { waitUntil: 'networkidle' });
        await assertGeometry(page, name, width, height, theme, consoleErrors, pageErrors);
      }
      await page.goto(`${WEB}/s-85?credential=${credentialId}`, { waitUntil: 'networkidle' });
      const tokenResponsePromise = page.waitForResponse(
        (response) => response.url().includes('/verification-tokens')
          && response.request().method() === 'POST',
      );
      await page.getByRole('button', { name: 'Create QR & secure link' }).click();
      const tokenBody = await (await tokenResponsePromise).json();
      await page.getByRole('img', { name: /QR code for https:/ }).waitFor();
      await assertGeometry(page, 's85-issued', width, height, theme, consoleErrors, pageErrors);
      await page.goto(`${WEB}${new URL(tokenBody.verification_url).pathname}`, {
        waitUntil: 'networkidle',
      });
      await assertGeometry(page, 'public-verify', width, height, theme, consoleErrors, pageErrors);
      await context.close();
    }
  }
}

async function assertGeometry(page, screen, width, height, theme, consoleErrors, pageErrors) {
  const metrics = await page.evaluate(() => {
    const root = document.documentElement;
    const badTargets = [];
    const selector = [
      'button',
      'a.btn',
      '.cw-tabs a',
      'input:not([type="file"]):not([type="checkbox"])',
      'select',
      'label.st-check',
      'label.cw-drop',
    ].join(',');
    for (const element of document.querySelectorAll(selector)) {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      if (
        style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number(style.opacity) !== 0
        && rect.width > 0
        && rect.height > 0
        && (rect.width < 44 || rect.height < 44)
      ) {
        badTargets.push({
          tag: element.tagName,
          text: element.textContent?.trim().slice(0, 50),
          width: rect.width,
          height: rect.height,
        });
      }
    }
    return {
      clientWidth: root.clientWidth,
      scrollWidth: root.scrollWidth,
      badTargets,
      theme: root.dataset.theme,
    };
  });
  const pass = metrics.scrollWidth <= metrics.clientWidth + 1
    && metrics.badTargets.length === 0
    && metrics.theme === theme
    && consoleErrors.length === 0
    && pageErrors.length === 0;
  record(
    'geometry',
    `${screen}-${width}x${height}-${theme}`,
    'no overflow; targets >=44; correct theme; zero console/page errors',
    JSON.stringify(metrics),
    pass,
    { consoleErrors: [...consoleErrors], pageErrors: [...pageErrors] },
  );
  await page.screenshot({
    path: path.join(OUT, `${screen}-${width}x${height}-${theme}.png`),
    fullPage: true,
  });
  if (!pass) throw new Error(`geometry failed: ${screen}-${width}x${height}-${theme}`);
}

async function freshContextPersistence(browser, credentialId) {
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } });
  const page = await context.newPage();
  await page.goto(`${WEB}/s-82`, { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Advanced Moot Court Certificate' }).waitFor();
  const href = await page.getByRole('link', { name: 'View status' }).getAttribute('href');
  check(
    'functional',
    'fresh authenticated browser context',
    href?.includes(credentialId),
    'server-persisted credential visible',
    String(href),
  );
  await context.close();
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    const { credentialId } = await positiveJourney(browser);
    await freshContextPersistence(browser, credentialId);
    await geometryMatrix(browser, credentialId);
  } catch (error) {
    report.failures.push(String(error?.stack ?? error));
  } finally {
    await browser.close();
    report.finishedAt = new Date().toISOString();
    report.summary = {
      functionalPassed: report.functional.filter((item) => item.pass).length,
      functionalFailed: report.functional.filter((item) => !item.pass).length,
      negativePassed: report.negative.filter((item) => item.pass).length,
      negativeFailed: report.negative.filter((item) => !item.pass).length,
      geometryPassed: report.geometry.filter((item) => item.pass).length,
      geometryFailed: report.geometry.filter((item) => !item.pass).length,
    };
    await writeFile(
      path.join(OUT, 'credential-e2e-report.json'),
      `${JSON.stringify(report, null, 2)}\n`,
    );
  }
  if (report.failures.length) {
    console.error(JSON.stringify(report.summary));
    process.exit(1);
  }
  console.log(JSON.stringify(report.summary));
}

await main();
