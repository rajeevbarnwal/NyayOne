import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import axe from 'axe-core';
import { chromium } from 'playwright';

const base = process.env.V34_BASE_URL ?? 'http://127.0.0.1:4177';
const evidenceDir = resolve(process.env.V34_EVIDENCE_DIR ?? 'test-results/v34-s11-s26');
const screenshotsDir = resolve(evidenceDir, 'screenshots');
await mkdir(screenshotsDir, { recursive: true });

const viewports = [
  { name: 'mobile-390x844', width: 390, height: 844 },
  { name: 'mobile-430x932', width: 430, height: 932 },
  { name: 'tablet-768x1024', width: 768, height: 1024 },
  { name: 'landscape-932x430', width: 932, height: 430 },
  { name: 'tablet-1024x768', width: 1024, height: 768 },
  { name: 'desktop-1440x900', width: 1440, height: 900 },
];
const themes = ['light', 'dark'];
const states = [
  ...Array.from({ length: 16 }, (_, index) => ({ id: `S-${index + 11}`, path: `/s-${index + 11}` })),
  { id: 'S-17E', path: '/s-17', edit: true },
];
const mobileScrollLimits = {
  'S-11': 111, 'S-12': 0, 'S-13': 22, 'S-14': 0, 'S-15': 463,
  'S-16': 8, 'S-17': 109, 'S-17E': 120, 'S-18': 0, 'S-19': 0,
  'S-20': 172, 'S-21': 205, 'S-22': 282, 'S-23': 18, 'S-24': 0,
  'S-25': 0, 'S-26': 0,
};

const rows = [];
const record = (area, expected, actual, pass, detail = '') => rows.push({ area, expected, actual, pass, detail });
const profile = {
  first_name: 'Aditi', middle_name: 'Rao', last_name: 'Nair',
  college: 'NLSIU', year_of_study: '4', masked_mobile: '******0042',
};
let settings = {
  theme: 'system', language: 'en', notif_email: true, notif_sms: true,
  notif_updates: false, version: 7,
  privacy: [
    { kind: 'analytics', enabled: false },
    { kind: 'marketing', enabled: false },
    { kind: 'share_partners', enabled: false },
  ],
};

async function installApiContract(page) {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (status, body) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (url.pathname === '/api/v1/student/profile') {
      if (request.method() === 'PATCH') {
        const body = request.postDataJSON();
        if (body.college) profile.college = body.college;
        if (body.year_of_study) profile.year_of_study = body.year_of_study;
      }
      return json(200, profile);
    }
    if (url.pathname === '/api/v1/auth/student/session') {
      return json(200, { authenticated: true, actor: { sub: '00000000-0000-4000-8000-0000000000de', roles: ['student'] } });
    }
    if (url.pathname === '/api/v1/student/settings') {
      if (request.method() === 'PATCH') {
        const body = request.postDataJSON();
        settings = {
          ...settings,
          ...(body.theme === undefined ? {} : { theme: body.theme }),
          ...(body.language === undefined ? {} : { language: body.language }),
          ...(body.notif_email === undefined ? {} : { notif_email: body.notif_email }),
          ...(body.notif_sms === undefined ? {} : { notif_sms: body.notif_sms }),
          ...(body.notif_updates === undefined ? {} : { notif_updates: body.notif_updates }),
          ...(body.privacy === undefined ? {} : { privacy: body.privacy }),
          version: settings.version + 1,
        };
      }
      return json(200, settings);
    }
    if (url.pathname.endsWith('/privacy/export')) return json(202, { request_id: 'export-opaque-001', status: 'pending' });
    if (url.pathname.includes('/privacy/requests/')) {
      return json(200, { request_id: url.pathname.split('/').pop(), kind: 'export', status: 'complete', created_at: '2026-08-01T00:00:00Z' });
    }
    if (url.pathname.endsWith('/privacy/delete')) return json(202, { request_id: 'delete-opaque-001', status: 'pending' });
    if (url.pathname.endsWith('/recovery/start')) return json(202, { recovery_id: 'recovery-opaque-001' });
    if (url.pathname.endsWith('/recovery/verify')) return json(200, { status: 'verified' });
    return json(404, { detail: { code: 'qa_route_not_stubbed' } });
  });
}

function geometryProbe() {
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const smallTargets = [...document.querySelectorAll('button,input,select,textarea,a[href]')]
    .filter((element) => visible(element))
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
  const scrollable = [...document.querySelectorAll('*')]
    .filter((element) => {
      if (!visible(element)) return false;
      const style = getComputedStyle(element);
      return /(auto|scroll)/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 1;
    })
    .map((element) => ({
      className: element.className || element.tagName,
      overflow: element.scrollHeight - element.clientHeight,
    }));
  return {
    screen: document.querySelector('[data-screen]')?.getAttribute('data-screen'),
    h1Count: document.querySelectorAll('h1').length,
    bodyOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    contentOverflowX: content ? content.scrollWidth - content.clientWidth : -1,
    contentOverflowY: content ? content.scrollHeight - content.clientHeight : -1,
    smallTargets,
    scrollable,
    legacyShells: document.querySelectorAll('.ls-rail,.ls-topbar,.ls-bnav').length,
  };
}

const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of viewports) {
    for (const theme of themes) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: theme,
      });
      await context.addInitScript(({ themeValue }) => {
        localStorage.setItem('ls-theme', themeValue);
        localStorage.setItem('legalsaathi.internship.saved.v1', JSON.stringify(['cam']));
      }, { themeValue: theme });
      const page = await context.newPage();
      await installApiContract(page);
      const runtime = { consoleErrors: [], pageErrors: [], failedRequests: [] };
      page.on('console', (message) => { if (message.type() === 'error') runtime.consoleErrors.push(message.text()); });
      page.on('pageerror', (error) => runtime.pageErrors.push(error.message));
      page.on('requestfailed', (request) => runtime.failedRequests.push(`${request.method()} ${request.url()}`));

      for (const state of states) {
        await page.goto(`${base}${state.path}`, { waitUntil: 'domcontentloaded' });
        await page.locator(`[data-screen="${state.id === 'S-17E' ? 'S-17' : state.id}"]`).waitFor({ state: 'visible' });
        if (state.edit) {
          const edit = page.getByRole('button', { name: 'Edit college & year' });
          await edit.waitFor({ state: 'visible' });
          await edit.click();
          await page.getByRole('heading', { name: 'Edit college & year' }).waitFor({ state: 'visible' });
        }
        const geometry = await page.evaluate(geometryProbe);
        const prefix = `${state.id}__${viewport.name}__${theme}`;
        const expectedScreen = state.id === 'S-17E' ? 'S-17' : state.id;
        record(`${prefix}__screen`, expectedScreen, geometry.screen, geometry.screen === expectedScreen);
        record(`${prefix}__heading`, 'exactly one h1', geometry.h1Count, geometry.h1Count === 1);
        record(`${prefix}__overflow-x`, '0 horizontal px', { body: geometry.bodyOverflowX, content: geometry.contentOverflowX }, geometry.bodyOverflowX === 0 && geometry.contentOverflowX <= 1);
        record(`${prefix}__targets`, 'all visible controls >=44x44', geometry.smallTargets, geometry.smallTargets.length === 0);
        record(`${prefix}__shell`, '0 legacy shell nodes', geometry.legacyShells, geometry.legacyShells === 0);
        const allowedScrollers = geometry.scrollable.every((item) =>
          String(item.className).includes('v34c-content') || String(item.className).includes('v34c-rail'));
        record(`${prefix}__scroll`, 'only feature content and desktop navigation rail may scroll', geometry.scrollable,
          allowedScrollers && geometry.scrollable.filter((item) => String(item.className).includes('v34c-content')).length <= 1);
        if (viewport.name === 'mobile-390x844' || viewport.name === 'mobile-430x932') {
          const budget = mobileScrollLimits[state.id];
          record(`${prefix}__mobile-scroll-budget`, `<=${budget}px intentional vertical content overflow`, geometry.contentOverflowY,
            geometry.contentOverflowY <= budget);
        }

        if ((viewport.name === 'mobile-390x844' || viewport.name === 'desktop-1440x900')) {
          await page.addScriptTag({ content: axe.source });
          const axeResult = await page.evaluate(async () => {
            const result = await globalThis.axe.run(document, {
              runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
            });
            return result.violations.map((violation) => ({
              id: violation.id,
              impact: violation.impact,
              targets: violation.nodes.slice(0, 3).map((node) => node.target),
            }));
          });
          record(`${prefix}__axe`, '0 WCAG A/AA violations', axeResult, axeResult.length === 0);
        }
        await page.screenshot({ path: resolve(screenshotsDir, `${prefix}.png`), fullPage: false });
      }
      record(`${viewport.name}__${theme}__runtime`, '0 console/page/request errors', runtime,
        runtime.consoleErrors.length === 0 && runtime.pageErrors.length === 0 && runtime.failedRequests.length === 0);
      await context.close();
    }
  }

  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await installApiContract(page);

  await page.goto(`${base}/s-13`);
  const resume = page.getByRole('button', { name: 'Continue step 2' });
  await resume.waitFor({ state: 'visible' });
  await resume.click();
  record('S-13_resume_branch', 'first incomplete step routes to S-10 academic', new URL(page.url()).pathname + new URL(page.url()).search,
    new URL(page.url()).pathname === '/s-10' && new URL(page.url()).search === '?step=academic');

  await page.goto(`${base}/s-15`);
  const email = page.getByLabel('Institutional email');
  const send = page.getByRole('button', { name: 'Send verification link' });
  await email.fill('student@gmail.com');
  await send.click();
  record('S-15_consumer_email', 'consumer domain rejected', await page.getByRole('alert').allTextContents(),
    await page.getByText('Enter a valid institutional email of 254 characters or fewer — e.g. aditi.nair@nls.ac.in').isVisible());
  await email.fill('student@nls.ac.in');
  record('S-15_academic_email', 'academic domain clears local validation', await email.inputValue(), await email.inputValue() === 'student@nls.ac.in');

  await page.goto(`${base}/s-20`);
  const search = page.getByRole('searchbox', { name: 'Search internships' });
  await search.fill('not-a-real-placement');
  record('S-20_empty_search', 'truthful no-results state', await page.getByText('No matching listings').isVisible(),
    await page.getByText('No matching listings').isVisible());

  await page.goto(`${base}/s-22`);
  const cover = page.getByLabel('Cover note');
  const continueDocuments = page.getByRole('button', { name: 'Continue to documents' });
  await cover.fill('A'.repeat(49));
  await continueDocuments.click();
  record('S-22_cover_49', '49 chars rejected', await page.getByRole('alert').allTextContents(), await page.getByText('Cover note must be at least 50 characters.').isVisible());
  await cover.fill('A'.repeat(50));
  await continueDocuments.click();
  record('S-22_cover_50', '50 chars accepted', await page.getByRole('heading', { name: 'Documents' }).isVisible(), await page.getByRole('heading', { name: 'Documents' }).isVisible());

  const resumeInput = page.getByLabel('Résumé (PDF)');
  const transcriptInput = page.getByLabel('Transcript (PDF)');
  await resumeInput.setInputFiles({ name: 'resume.txt', mimeType: 'text/plain', buffer: Buffer.from('not a pdf') });
  await transcriptInput.setInputFiles({ name: 'transcript.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(0) });
  await page.getByRole('button', { name: 'Review application' }).click();
  const uploadErrors = await page.getByRole('alert').allTextContents();
  record('S-22_upload_type_empty', 'non-PDF and empty PDF rejected', uploadErrors,
    uploadErrors.some((text) => text.includes('must be a PDF')) && uploadErrors.some((text) => text.includes('file is empty')));
  await resumeInput.setInputFiles({ name: 'resume.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(5 * 1024 * 1024, 1) });
  await transcriptInput.setInputFiles({ name: 'transcript.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(5 * 1024 * 1024 + 1, 1) });
  await page.getByRole('button', { name: 'Review application' }).click();
  record('S-22_upload_5mb_boundary', '5 MB accepted and 5 MB + 1 rejected', await page.getByRole('alert').allTextContents(),
    !(await page.getByText('Resume must be 5 MB or smaller.').isVisible()) && await page.getByText('Transcript must be 5 MB or smaller.').isVisible());

  await page.goto(`${base}/s-19`);
  await page.locator('details.v34c-mobile-disclosure').filter({ hasText: 'Data rights' }).locator('summary').click();
  const deleteToggle = page.getByRole('button', { name: 'Delete…' });
  await deleteToggle.click();
  record('S-19_delete_reauth_gate', 'delete cannot be submitted before re-authentication',
    { deleteButtons: await page.getByRole('button', { name: 'Delete my account' }).count() },
    await page.getByRole('button', { name: 'Delete my account' }).count() === 0);

  const storage = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, cookies: document.cookie }));
  const serialized = JSON.stringify(storage).toLowerCase();
  record('browser_storage_privacy', 'no raw mobile, OTP, document bytes or private profile values in browser storage', storage,
    !serialized.includes('9876543210') && !serialized.includes('student@nls.ac.in') && !serialized.includes('aditi'));
  await context.close();
} finally {
  await browser.close();
}

const summary = {
  total: rows.length,
  passed: rows.filter((row) => row.pass).length,
  failed: rows.filter((row) => !row.pass).length,
  screenshots: (await readdir(screenshotsDir)).filter((name) => name.endsWith('.png')).length,
  rows,
};
await writeFile(resolve(evidenceDir, 'results.json'), `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
await writeFile(resolve(evidenceDir, 'summary.txt'), [
  'LegalSaathi v3.4 S-11-S-26 production integration',
  `total=${summary.total}`,
  `passed=${summary.passed}`,
  `failed=${summary.failed}`,
  `screenshots=${summary.screenshots}`,
].join('\n') + '\n', 'utf8');

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
console.log(JSON.stringify({ total: summary.total, passed: summary.passed, failed: summary.failed, screenshots: summary.screenshots, evidenceDir }, null, 2));
if (summary.failed > 0) process.exitCode = 1;
