import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:1055';
const OUT = process.env.QA_OUT ?? path.resolve('../../JiraReports/Returned_To_Do_Remediation_2026-07-18');
const widths = [390, 430, 768, 1024, 1440];
const themes = ['light', 'dark'];
const runMatrix = process.env.QA_MATRIX !== '0';
const routeMap = {
  'SAATHI-2': '/auth/lawyer',
  'SAATHI-52': '/s-03',
  'SAATHI-53': '/s-05',
  'SAATHI-55': '/s-09',
  'SAATHI-57': '/s-14',
  'SAATHI-60': '/s-20',
  'SAATHI-61': '/s-22',
  'SAATHI-74': '/s-51',
  'SAATHI-104': '/s-20',
  'SAATHI-108': '/s-17',
  'SAATHI-112': '/s-20',
  'SAATHI-116': '/s-22',
  'SAATHI-144': '/s-51',
  'SAATHI-147': '/s-55',
  'SAATHI-173': '/s-61',
  'SAATHI-185': '/s-65',
};

await mkdir(path.join(OUT, 'screenshots'), { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ acceptDownloads: true });
const page = await context.newPage();
const consoleErrors = [];
const networkErrors = [];
page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
page.on('response', (response) => {
  if (response.status() >= 400) networkErrors.push(`${response.status()} ${response.url()}`);
});

const checks = [];
function check(name, pass, detail = '') {
  checks.push({ name, pass: Boolean(pass), detail });
  if (!pass) console.error(`FAIL ${name}: ${detail}`);
}

async function reset() {
  await page.goto(`${BASE}/s-03`, { waitUntil: 'networkidle' });
  await page.evaluate(() => localStorage.clear());
}

await reset();

// Functional: lawyer validation, secret removal and reviewer-only override isolation.
await page.goto(`${BASE}/auth/lawyer`, { waitUntil: 'networkidle' });
await page.getByLabel('Full name').fill('Rajeev Barnwal');
await page.getByLabel('Mobile number').fill('98765432101');
await page.getByRole('button', { name: 'Send OTP' }).click();
check('SAATHI-2 rejects >10-digit lawyer phone', await page.getByText('Enter a valid 10-digit mobile number.').isVisible());
await page.getByLabel('Mobile number').fill('9876543210');
await page.getByRole('button', { name: 'Send OTP' }).click();
check('SAATHI-2 OTP secret absent from UI', !(await page.locator('body').innerText()).includes('429016'));
await page.getByLabel('6-digit code').fill('429016');
await page.getByRole('button', { name: 'Verify', exact: true }).click();
await page.getByLabel(/Privacy Notice/).check({ force: true });
await page.getByRole('button', { name: /Record consent/ }).click();
await page.getByLabel('Full name (as enrolled)').fill('Rajeev Barnwal');
await page.getByLabel('Enrolment number').fill('D/1235/2015');
await page.getByLabel('State Bar Council').selectOption({ label: 'Bar Council of Delhi' });
await page.getByRole('button', { name: 'Submit for verification' }).click();
check('SAATHI-2 rejected user has no manual override control', await page.getByLabel('Authorised reviewer override reason').count() === 0);
check('SAATHI-2 rejected user remains restricted', await page.getByText(/Enrolment could not be verified/).isVisible());

// Functional: student exact-phone + future DOB + profile hand-off + secret removal.
await page.goto(`${BASE}/s-05`, { waitUntil: 'networkidle' });
await page.getByLabel('Full name').fill('Rajeev Barnwal');
await page.getByLabel('Mobile number').fill('98765432101');
await page.getByLabel('Date of birth').fill('2099-01-01');
for (const id of ['reg-terms', 'reg-privacy', 'reg-law']) await page.locator(`#${id}`).check({ force: true });
await page.getByRole('button', { name: /Create account/ }).click();
check('SAATHI-52 rejects >10-digit student phone', await page.getByText('Enter a valid 10-digit mobile number.').isVisible());
check('SAATHI-55 rejects future registration DOB', await page.getByText(/not in the future/).isVisible());
await page.getByLabel('Mobile number').fill('9876543210');
await page.getByLabel('Date of birth').fill('2000-01-01');
await page.getByRole('button', { name: /Create account/ }).click();
check('SAATHI-53 reviewer OTP secret absent', !(await page.locator('body').innerText()).includes('429016'));
await page.getByLabel('OTP').fill('429016');
await page.getByRole('button', { name: /Verify & continue/ }).click();
check('SAATHI-55 registration name reaches profile', await page.getByLabel('Full name').inputValue() === 'Rajeev Barnwal');
check('SAATHI-55 registration DOB reaches profile', await page.getByLabel('Date of birth').inputValue() === '2000-01-01');
await page.reload({ waitUntil: 'networkidle' });
check('SAATHI-108 profile data survives refresh', await page.getByLabel('Full name').inputValue() === 'Rajeev Barnwal');

// Functional: shell navigation and dashboard data are not fabricated.
await page.goto(`${BASE}/s-20`, { waitUntil: 'networkidle' });
check('SAATHI-104 desktop Home targets dashboard', await page.locator('.ls-rail a', { hasText: 'Home' }).getAttribute('href') === '/s-14');
check('SAATHI-108 desktop Profile targets profile view', await page.locator('.ls-rail a', { hasText: 'Profile' }).getAttribute('href') === '/s-17');
await page.goto(`${BASE}/s-14`, { waitUntil: 'networkidle' });
const dashboardText = await page.locator('main').innerText();
check('SAATHI-57 dashboard uses persisted name', dashboardText.includes('Rajeev'));
check('SAATHI-57 removes hardcoded Aditi metrics', !dashboardText.includes('Aditi') && !dashboardText.includes('62 clinical'));
check('SAATHI-57 canonical Calendar/Explore labels', dashboardText.includes('Calendar · this week') && dashboardText.includes('Explore'));

// Functional: verified-only filter is independent (PO observation was not reproduced).
await page.goto(`${BASE}/s-20`, { waitUntil: 'networkidle' });
await page.getByRole('button', { name: 'Verified only' }).click();
check('SAATHI-60/112 verified-only independently yields one listing', (await page.getByText('1 shown').count()) === 1);
await page.getByRole('button', { name: 'Unpaid' }).click();
check('SAATHI-60/112 combined verified+unpaid yields empty state', await page.getByText('No matching listings').isVisible());
await page.getByRole('button', { name: 'All stipends' }).click();
check('SAATHI-60/112 clearing stipend retains verified-only', (await page.getByText('1 shown').count()) === 1);

// Functional: real PDF inputs, validation and persisted tracker entry.
await page.goto(`${BASE}/s-22`, { waitUntil: 'networkidle' });
await page.getByRole('button', { name: 'Submit application' }).click();
check('SAATHI-61/116 requires résumé PDF', await page.getByText('Résumé PDF is required.').isVisible());
check('SAATHI-61/116 requires transcript PDF', await page.getByText('Transcript PDF is required.').isVisible());
await page.setInputFiles('#app-resume', { name: 'resume.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 resume') });
await page.setInputFiles('#app-transcript', { name: 'transcript.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 transcript') });
await page.getByRole('button', { name: 'Submit application' }).click();
check('SAATHI-61/116 submission reaches confirmation', page.url().endsWith('/s-23'));
const storedApplications = await page.evaluate(() => localStorage.getItem('legalsaathi.internship.applications.v1'));
check('SAATHI-61/116 submission stored', Boolean(storedApplications), storedApplications ?? 'missing');
await page.getByRole('button', { name: 'Open tracker' }).click();
await page.getByRole('heading', { name: 'Your applications' }).waitFor();
const trackerCount = await page.locator('section[aria-label="Your applications"] li').count();
check('SAATHI-61/116 tracker route opens', page.url().endsWith('/s-24'), page.url());
check('SAATHI-61/116 submitted application persists in tracker', trackerCount > 5, `application rows=${trackerCount}`);

// Functional: reply posting/validation.
await page.goto(`${BASE}/s-51`, { waitUntil: 'networkidle' });
await page.getByRole('button', { name: 'Post reply' }).click();
check('SAATHI-74/144 blank reply blocked', await page.getByText('Enter a reply before posting.').isVisible());
await page.getByLabel('Add to the discussion').fill('The judgment distinguishes the earlier ratio.');
await page.getByRole('button', { name: 'Post reply' }).click();
check('SAATHI-74/144 valid reply appears', await page.getByText('The judgment distinguishes the earlier ratio.').isVisible());

// Functional: exam navigation actions.
await page.goto(`${BASE}/s-55`, { waitUntil: 'networkidle' });
await page.getByRole('tab', { name: 'Analytics' }).click();
check('SAATHI-147 Analytics action routes to S-59', page.url().endsWith('/s-59'));
await page.goto(`${BASE}/s-55`, { waitUntil: 'networkidle' });
await page.getByRole('button', { name: 'Start timed mock' }).click();
check('SAATHI-147 Start timed mock routes to S-56', page.url().endsWith('/s-56'));

// Functional: export controls produce downloads/status and audit events.
await page.goto(`${BASE}/s-65`, { waitUntil: 'networkidle' });
const csvDownload = page.waitForEvent('download');
await page.getByRole('button', { name: 'CSV', exact: true }).click();
const csv = await csvDownload;
check('SAATHI-185 CSV download created', (await csv.suggestedFilename()).endsWith('.csv'));
check('SAATHI-185 CSV audit status visible', await page.getByText(/CSV export downloaded/).isVisible());
await page.getByRole('button', { name: 'On' }).click().catch(async () => page.getByRole('button', { name: 'Off' }).click());
const evidenceOn = (await page.getByRole('button', { name: /On|Off/ }).getAttribute('aria-pressed')) === 'true';
if (!evidenceOn) await page.getByRole('button', { name: 'Off' }).click();
check('SAATHI-185 evidence export requires re-authentication', await page.getByRole('button', { name: 'PDF report' }).isDisabled());
await page.getByRole('button', { name: 'Re-authenticate' }).click();
check('SAATHI-185 re-authentication enables evidence export', !(await page.getByRole('button', { name: 'PDF report' }).isDisabled()));
await page.getByRole('button', { name: 'Send to institution' }).click();
check('SAATHI-185 institution action reports no external transfer', await page.getByText(/No external transfer occurs/).isVisible());

// Responsive/theme matrix with production shell, no internal reviewer banner.
if (runMatrix) for (const [ticket, route] of Object.entries(routeMap)) {
  for (const theme of themes) {
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' });
      await page.evaluate((t) => {
        localStorage.removeItem('ls-reviewer');
        localStorage.setItem('ls-theme', t);
      }, theme);
      await page.reload({ waitUntil: 'networkidle' });
      const metrics = await page.evaluate(() => {
        const targets = [...document.querySelectorAll('a,button,input,textarea,select')]
          .filter((node) => node instanceof HTMLElement && node.offsetParent !== null)
          .map((node) => {
            const box = node.getBoundingClientRect();
            return { tag: node.tagName, text: (node.getAttribute('aria-label') || node.textContent || '').trim().slice(0, 60), width: box.width, height: box.height };
          })
          .filter((box) => box.width > 0 && (box.width < 44 || box.height < 44));
        return {
          overflow: document.documentElement.scrollWidth > window.innerWidth,
          targets,
          trace: document.querySelectorAll('.ls-trace').length,
          theme: document.documentElement.getAttribute('data-theme'),
        };
      });
      check(`${ticket} ${route} ${width}px ${theme} no overflow`, !metrics.overflow, JSON.stringify(metrics));
      check(`${ticket} ${route} ${width}px ${theme} 44px targets`, metrics.targets.length === 0, JSON.stringify(metrics.targets));
      check(`${ticket} ${route} ${width}px ${theme} no reviewer banner`, metrics.trace === 0, `trace=${metrics.trace}`);
      check(`${ticket} ${route} ${width}px ${theme} theme applied`, metrics.theme === theme, `theme=${metrics.theme}`);
      await page.screenshot({
        path: path.join(OUT, 'screenshots', `${ticket}_${route.replaceAll('/', '')}_${width}_${theme}.png`),
        fullPage: true,
      });
    }
  }
}

check('No console errors', consoleErrors.length === 0, consoleErrors.join('\n'));
check('No 4xx/5xx responses', networkErrors.length === 0, networkErrors.join('\n'));

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl: BASE,
  commit: process.env.QA_COMMIT ?? 'working-tree',
  tickets: Object.keys(routeMap),
  matrix: { routes: Object.keys(routeMap).length, widths, themes, captures: Object.keys(routeMap).length * widths.length * themes.length },
  totals: { checks: checks.length, passed: checks.filter((item) => item.pass).length, failed: checks.filter((item) => !item.pass).length },
  consoleErrors,
  networkErrors,
  checks,
};
await writeFile(path.join(OUT, 'returned_todo_qa_report.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log(JSON.stringify(report.totals));
process.exit(report.totals.failed ? 1 : 0);
