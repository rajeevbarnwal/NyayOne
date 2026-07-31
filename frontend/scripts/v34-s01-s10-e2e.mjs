import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { chromium } from 'playwright';

const base = process.env.V34_BASE_URL ?? 'http://127.0.0.1:4174';
const evidenceDir = resolve(process.env.V34_EVIDENCE_DIR ?? 'test-results/v34-s01-s10');
const screenshotsDir = resolve(evidenceDir, 'screenshots');
await mkdir(screenshotsDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const rows = [];
const record = (area, expected, actual, pass, detail = '') => rows.push({ area, expected, actual, pass, detail });

try {
  for (const viewport of [{ name: 'mobile', width: 390, height: 844 }, { name: 'desktop', width: 1440, height: 900 }]) {
    for (const theme of ['light', 'dark']) {
      const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, colorScheme: theme });
      await context.addInitScript(({ themeValue }) => localStorage.setItem('ls-theme', themeValue), { themeValue: theme });
      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
      page.on('pageerror', (error) => pageErrors.push(error.message));

      for (let number = 1; number <= 10; number += 1) {
        const id = `S-${String(number).padStart(2, '0')}`;
        const path = `/s-${String(number).padStart(2, '0')}`;
        await page.goto(`${base}${path}`, { waitUntil: 'domcontentloaded' });
        const feature = page.locator(`[data-screen="${id}"]`);
        await feature.waitFor({ state: 'visible' });
        const geometry = await page.evaluate(() => {
          const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const smallTargets = [...document.querySelectorAll('button,input,select,a[href]')]
            .filter((element) => visible(element) && !element.closest('.v34-actions__hint'))
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
        });
        record(`${id}_${viewport.name}_${theme}_overflow`, '0 horizontal px', geometry.horizontalOverflow, geometry.horizontalOverflow === 0);
        record(`${id}_${viewport.name}_${theme}_shell`, '0 legacy shell nodes', geometry.legacyShells, geometry.legacyShells === 0);
        record(`${id}_${viewport.name}_${theme}_targets`, 'all visible targets >=44x44', geometry.smallTargets, geometry.smallTargets.length === 0);
        await page.screenshot({ path: resolve(screenshotsDir, `${id}__${viewport.name}__${theme}.png`), fullPage: true });
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
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ registration_id: '00000000-0000-4000-8000-000000000001' }) });
  });

  const loadRegistration = async () => {
    await page.goto(`${base}/s-08`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Create your student account' }).waitFor();
  };
  const fillRequired = async ({ first = 'Rajeev', last = 'Barnwal', mobile = '9876543210', dob = '2000-01-01' } = {}) => {
    await page.getByLabel('FIRST NAME').fill(first);
    await page.getByLabel('LAST NAME').fill(last);
    await page.getByLabel('MOBILE NUMBER').fill(mobile);
    await page.getByLabel('INSTITUTIONAL EMAIL').fill('student@nls.ac.in');
    await page.getByLabel('DATE OF BIRTH').fill(dob);
    await page.getByLabel('COLLEGE OR UNIVERSITY').selectOption('NLSIU');
    await page.getByLabel('YEAR OF STUDY').selectOption('4');
    await page.getByRole('checkbox', { name: /enrolled in, or applying to/ }).check();
    await page.getByRole('checkbox', { name: /accept the terms/ }).check();
  };
  const submit = () => page.getByRole('button', { name: 'Send one time code' }).click();

  await loadRegistration();
  await fillRequired({ mobile: '123456789' });
  await submit();
  record('mobile_9_digits', 'typed exact-length error and remain S-08', await page.getByRole('alert').allTextContents(), await page.getByText('Mobile number must be exactly 10 digits.').isVisible() && new URL(page.url()).pathname === '/s-08');

  await loadRegistration();
  await fillRequired({ mobile: '12345678901' });
  await submit();
  record('mobile_11_digits', 'typed exact-length error and remain S-08', await page.getByRole('alert').allTextContents(), await page.getByText('Mobile number must be exactly 10 digits.').isVisible() && new URL(page.url()).pathname === '/s-08');

  await loadRegistration();
  await fillRequired({ dob: '2030-01-01' });
  await submit();
  record('future_dob', 'future date rejected with clear error', await page.getByRole('alert').allTextContents(), await page.getByText(/not in the future/i).isVisible());

  await loadRegistration();
  await fillRequired({ first: 'Rajeev!', last: 'Barnwal1' });
  await submit();
  const specialAlerts = await page.getByRole('alert').allTextContents();
  record('special_name_characters', 'first and last names rejected', specialAlerts, specialAlerts.filter((text) => /characters that aren't allowed/i.test(text)).length === 2);

  await loadRegistration();
  await submit();
  const emptyAlerts = await page.getByRole('alert').allTextContents();
  record('empty_required_fields', 'all required inputs rejected', emptyAlerts, emptyAlerts.length >= 8);

  await loadRegistration();
  const sixty = 'A'.repeat(60);
  await fillRequired({ first: sixty, last: sixty });
  await submit();
  await page.waitForURL('**/s-09');
  record('name_60_boundary', '60 characters accepted', { firstLength: capturedPayload?.first_name?.length, lastLength: capturedPayload?.last_name?.length }, capturedPayload?.first_name?.length === 60 && capturedPayload?.last_name?.length === 60);
  record('split_name_payload', 'first/middle/last mapped independently', capturedPayload, capturedPayload?.first_name === sixty && capturedPayload?.middle_name === null && capturedPayload?.last_name === sixty);

  await loadRegistration();
  await page.getByLabel('FIRST NAME').fill('B'.repeat(61));
  const maxLengthActual = await page.getByLabel('FIRST NAME').inputValue();
  record('name_61_boundary', 'input capped at 60', maxLengthActual.length, maxLengthActual.length === 60);

  const criticalSelectors = {
    'INSTITUTIONAL EMAIL': '#v34-email',
    'COLLEGE OR UNIVERSITY': '#v34-college',
    'YEAR OF STUDY': '#v34-year',
    'BAR ENROLMENT': '#v34-bar',
    'DATE OF BIRTH': '#v34-dob',
  };
  const criticalVisibility = Object.fromEntries(await Promise.all(Object.entries(criticalSelectors).map(async ([label, selector]) => [label, await page.locator(selector).isVisible()])));
  record('legacy_schema_parity', 'all critical legacy fields visible', criticalVisibility, Object.values(criticalVisibility).every(Boolean));

  await page.goto(`${base}/s-03`);
  const iconContract = await page.evaluate(() => [...document.querySelectorAll('.v34-iconbtn')].map((button) => ({ aria: button.getAttribute('aria-label'), tip: button.getAttribute('data-tip'), svg: button.querySelectorAll('svg').length })));
  record('icon_tooltip_contract', 'every icon CTA has SVG, aria-label and visible-tooltip text', iconContract, iconContract.length > 0 && iconContract.every((item) => item.aria && item.tip === item.aria && item.svg === 1));

  await page.goto(`${base}/s-04`);
  await page.getByRole('button', { name: 'Use a one time code' }).click();
  await page.getByLabel('MOBILE NUMBER').fill('9876543210');
  await page.getByRole('button', { name: 'Send one time code' }).click();
  const loginStorage = await page.evaluate(() => ({ ...localStorage, ...sessionStorage }));
  record('no_login_otp_stub', 'no simulated login success or browser OTP challenge', { alert: await page.getByRole('alert').innerText(), path: new URL(page.url()).pathname, loginStorage },
    await page.getByText(/one time code sign-in is not available yet/i).isVisible()
      && new URL(page.url()).pathname === '/s-04'
      && !JSON.stringify(loginStorage).includes('429016'));
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
