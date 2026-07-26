import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const base = process.env.QA_BASE_URL ?? 'http://127.0.0.1:1043';
const capture = process.env.QA_OTP_CAPTURE_URL ?? 'http://127.0.0.1:1099';
const evidence = process.env.QA_EVIDENCE_DIR ?? path.resolve('../QA/registration_closure');
await fs.mkdir(evidence, { recursive: true });

const results = [];
const record = (name, expected, actual, pass, evidenceFile = null) => {
  results.push({ name, expected, actual, pass, evidence: evidenceFile });
  if (!pass) throw new Error(`${name}: expected ${expected}; actual ${actual}`);
};
const latestOtp = async () => {
  for (let i = 0; i < 30; i += 1) {
    const response = await fetch(`${capture}/latest`);
    const value = await response.json();
    if (/^\d{6}$/.test(value.code ?? '')) return value.code;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('OTP provider did not receive a code');
};
const resetOtp = async () => {
  const response = await fetch(`${capture}/reset`, { method: 'POST' });
  if (!response.ok) throw new Error('OTP capture reset failed');
};
const browser = await chromium.launch({ headless: true });

async function fresh(viewport = { width: 1440, height: 1000 }) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const consoleErrors = [];
  const networkErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('response', (r) => { if (r.status() >= 400) networkErrors.push(`${r.status()} ${r.url()}`); });
  return { context, page, consoleErrors, networkErrors };
}

async function fillBase(page, {
  first = 'Aditi', middle = '', last = 'Nair', mobile = '9876543210', dob = '2004-03-14',
} = {}) {
  await page.goto(`${base}/s-05`);
  await page.getByLabel('First name').fill(first);
  await page.getByLabel('Middle name').fill(middle);
  await page.getByLabel('Last name').fill(last);
  await page.getByLabel('Mobile number').fill(mobile);
  await page.getByLabel('Date of birth').fill(dob);
  await page.getByLabel('I accept the Terms of Use.').check();
  await page.getByLabel(/Privacy notice/).check();
  await page.getByLabel(/law student or aspiring/).check();
}

// Explicit negative/boundary cases.
for (const [name, values, expected] of [
  ['mobile_9_digits', { mobile: '987654321' }, 'Mobile number must be exactly 10 digits.'],
  ['mobile_11_digits', { mobile: '98765432101' }, 'Mobile number must be exactly 10 digits.'],
  ['mobile_12_digits', { mobile: '987654321012' }, 'Mobile number must be exactly 10 digits.'],
  ['future_dob', { mobile: '9000000001', dob: '2030-01-01' }, 'Enter a valid date of birth that is not in the future.'],
  ['empty_first_name', { mobile: '9000000002', first: '' }, 'Enter your first name.'],
  ['special_name', { mobile: '9000000003', first: '<script>' }, 'contains characters'],
  ['name_61_chars', { mobile: '9000000004', first: 'A'.repeat(61) }, '60 characters or fewer'],
]) {
  const { context, page } = await fresh();
  await fillBase(page, values);
  await page.getByRole('button', { name: /Create account/ }).click();
  const text = await page.locator('body').innerText();
  record(name, expected, text.includes(expected), text.includes(expected));
  record(`${name}_blocked`, 'remain /s-05', new URL(page.url()).pathname, new URL(page.url()).pathname === '/s-05');
  await context.close();
}

// Maximum allowed boundary: exactly 60 characters is accepted.
{
  const { context, page } = await fresh();
  await fillBase(page, { first: 'A'.repeat(60), mobile: '9000000005' });
  await page.getByRole('button', { name: /Create account/ }).click();
  await page.waitForURL('**/s-06');
  record('name_60_chars', 'accepted and routed to /s-06', new URL(page.url()).pathname, true);
  await context.close();
}

// Full S-05 -> server OTP -> S-10 backend profile persistence.
{
  const { context, page, consoleErrors, networkErrors } = await fresh();
  const requests = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/auth/student/')) requests.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  await fillBase(page, { first: 'Aditi', middle: 'Rani', last: 'Nair', mobile: '9000000006' });
  await resetOtp();

  const info = page.getByRole('button', { name: 'Information about name and guardian consent' });
  await info.focus();
  const tooltip = page.getByRole('tooltip');
  await tooltip.waitFor({ state: 'visible' });
  const tooltipBox = await tooltip.boundingBox();
  record('info_tooltip', 'visible exact DPDP copy', await tooltip.innerText(),
    (await tooltip.innerText()).includes('Under-18 accounts need verified guardian consent'));
  record('info_tooltip_viewport', 'inside viewport', tooltipBox,
    !!tooltipBox && tooltipBox.x >= 0 && tooltipBox.y >= 0 && tooltipBox.x + tooltipBox.width <= 1440);

  await page.getByRole('button', { name: /Create account/ }).click();
  await page.waitForURL('**/s-06');
  record('single_otp_control', 'no duplicate decorative OTP slots',
    await page.locator('.st-otp').count(), await page.locator('.st-otp').count() === 0);
  const otp = await latestOtp();
  await page.getByLabel('OTP').fill(otp);
  await page.getByRole('button', { name: /Verify & continue/ }).click();
  await page.waitForURL('**/s-09');
  record('profile_name_split', 'First/Middle/Last fields present; no Full name field',
    {
      first: await page.getByLabel('First name').count(),
      middle: await page.getByLabel('Middle name').count(),
      last: await page.getByLabel('Last name').count(),
      full: await page.getByLabel('Full name').count(),
    },
    await page.getByLabel('First name').count() === 1
      && await page.getByLabel('Middle name').count() === 1
      && await page.getByLabel('Last name').count() === 1
      && await page.getByLabel('Full name').count() === 0);
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.waitForURL('**/s-10');

  for (const label of [
    'College / University',
    'Year of study',
    'College enrolment number',
    'Institutional email',
    'Bar enrolment number',
  ]) {
    record(`legacy_field_${label}`, 'present and interactable', label, await page.getByLabel(label).isEnabled());
  }
  await page.getByLabel('College / University').selectOption({ label: 'National Law School of India University (NLSIU)' });
  await page.getByLabel('Year of study').selectOption({ label: '3rd year' });
  await page.getByLabel('College enrolment number').fill('KA/1234/2023');
  await page.getByLabel('Institutional email').fill('aditi@nls.ac.in');
  await page.getByLabel('Bar enrolment number').fill('D/1234/2024');
  await page.screenshot({ path: path.join(evidence, 's10_academic_fields.png'), fullPage: true });
  await page.getByRole('button', { name: /Save & continue/ }).click();
  await page.waitForURL('**/s-11');

  const storage = await page.evaluate(() => ({
    local: Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])),
    session: Object.fromEntries(Object.keys(sessionStorage).map((k) => [k, sessionStorage.getItem(k)])),
  }));
  const serialized = JSON.stringify(storage);
  record('no_browser_pii', 'no names/mobile/DOB/academic PII in browser storage', serialized,
    !['Aditi', '9000000006', '2004-03-14', 'KA/1234/2023', 'aditi@nls.ac.in'].some((v) => serialized.includes(v)));
  record('opaque_session_only', 'opaque registration state present',
    storage.session['legalsaathi.student.registration.v2'],
    !!storage.session['legalsaathi.student.registration.v2']);
  record('registration_api_called', 'POST /register', requests, requests.some((r) => r.includes('POST /api/v1/auth/student/register')));
  record('otp_api_called', 'POST /otp/verify', requests, requests.some((r) => r.includes('POST /api/v1/auth/student/otp/verify')));
  record('profile_api_called', 'PATCH /profile', requests, requests.some((r) => r.includes('PATCH /api/v1/auth/student/profile')));
  record('console_errors', 'none', consoleErrors, consoleErrors.length === 0);
  record('network_errors', 'none', networkErrors, networkErrors.length === 0);
  const file = 's05_s10_full_flow.png';
  await page.screenshot({ path: path.join(evidence, file), fullPage: true });
  await context.close();
}

// S-08 recovery is mobile/OTP based and server-authoritative (not S-15 email).
{
  const { context, page } = await fresh();
  const calls = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/auth/student/recovery/')) calls.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  await page.goto(`${base}/s-08`);
  await page.getByLabel('Mobile number').fill('9000000006');
  await resetOtp();
  await page.getByRole('button', { name: 'Start account recovery' }).click();
  await page.getByText('If an account matches, a recovery code has been sent.').waitFor();
  await page.getByLabel('6-digit recovery code').fill(await latestOtp());
  await page.getByRole('button', { name: 'Verify recovery code' }).click();
  await page.getByText('Recovery verified. You may now sign in again.').waitFor();
  record('recovery_server_start', 'POST /recovery/start', calls,
    calls.some((r) => r.includes('POST /api/v1/auth/student/recovery/start')));
  record('recovery_server_verify', 'POST /recovery/verify', calls,
    calls.some((r) => r.includes('POST /api/v1/auth/student/recovery/verify')));
  record('recovery_server_complete', 'POST /recovery/complete', calls,
    calls.some((r) => r.includes('POST /api/v1/auth/student/recovery/complete')));
  record('recovery_no_email_redirect', 'remain /s-08', new URL(page.url()).pathname,
    new URL(page.url()).pathname === '/s-08');
  await page.screenshot({ path: path.join(evidence, 's08_recovery_complete.png'), fullPage: true });
  await context.close();
}

// Responsive/theme and tooltip matrix.
for (const width of [390, 430, 768, 1024, 1440]) {
  for (const theme of ['light', 'dark']) {
    const { context, page, consoleErrors } = await fresh({ width, height: 1000 });
    await page.addInitScript((value) => localStorage.setItem('ls-theme', value), theme);
    await fillBase(page, { mobile: `91${String(width).padStart(8, '0')}`.slice(0, 10) });
    await page.getByRole('button', { name: 'Information about name and guardian consent' }).click();
    const tooltipBox = await page.getByRole('tooltip').boundingBox();
    const metrics = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      button: (() => {
        const element = document.querySelector('.st-info__btn');
        const box = element?.getBoundingClientRect();
        return box ? { width: box.width, height: box.height } : null;
      })(),
    }));
    record(`responsive_${width}_${theme}`, `width<=${width}, tooltip in viewport, target>=44`,
      { metrics, tooltipBox },
      metrics.width <= width
      && !!metrics.button && metrics.button.width >= 44 && metrics.button.height >= 44
      && !!tooltipBox && tooltipBox.x >= 0 && tooltipBox.x + tooltipBox.width <= width
      && consoleErrors.length === 0);
    const file = `s05_${width}_${theme}.png`;
    await page.screenshot({ path: path.join(evidence, file), fullPage: true });
    await context.close();
  }
}

// Alternate /auth/student entry point must also use the server, never stub OTP.
{
  const { context, page } = await fresh();
  const calls = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/v1/auth/student/')) calls.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  await page.goto(`${base}/auth/student`);
  await page.getByLabel('First name').fill('Brij');
  await page.getByLabel('Last name').fill('Goyal');
  await page.getByLabel('Mobile number').fill('9000000007');
  await page.getByLabel('Date of birth').fill('2000-01-01');
  await page.getByLabel('College / university').selectOption('NLSIU');
  await page.getByLabel(/accept the Privacy Notice/).check();
  await resetOtp();
  await page.getByRole('button', { name: 'Send OTP' }).click();
  const otp = await latestOtp();
  await page.getByLabel('6-digit code').fill(otp);
  await page.getByRole('button', { name: 'Verify' }).click();
  await page.getByText('OTP verified').waitFor();
  record('auth_student_server_register', 'POST /register', calls,
    calls.some((r) => r.includes('POST /api/v1/auth/student/register')));
  record('auth_student_server_verify', 'POST /otp/verify', calls,
    calls.some((r) => r.includes('POST /api/v1/auth/student/otp/verify')));
  record('no_stub_otp_visible', '429016 absent', await page.locator('body').innerText(),
    !(await page.locator('body').innerText()).includes('429016'));
  await context.close();
}

await browser.close();
const report = {
  generatedAt: new Date().toISOString(),
  base,
  passed: results.filter((r) => r.pass).length,
  failed: results.filter((r) => !r.pass).length,
  results,
};
await fs.writeFile(path.join(evidence, 'registration_e2e_report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ passed: report.passed, failed: report.failed, evidence }, null, 2));
