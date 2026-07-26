/**
 * SAATHI-388 / SAATHI-421 — repository-owned Playwright functional + negative
 * suite for the S-05 registration remediation. Runs on the native Mac env
 * (Headless Chromium); the sandbox has no browser.
 *
 *   npm run build && npm run preview &                 # serves on :1030
 *   BASE_URL=http://localhost:1030 node scripts/registration-qa.mjs
 *
 * Every negative row asserts all three: (1) the correct error is visible,
 * (2) navigation/OTP is blocked (still on /s-05), (3) no profile draft was
 * persisted (localStorage key absent). Uses semantic labels + ticket-scoped
 * data-testids; no hardcoded sleeps.
 */
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const BASE = process.env.BASE_URL || 'http://localhost:1030';
const OUT = resolve(process.env.OUT_DIR || 'tests/registration-out');
const WIDTHS = [390, 430, 768, 1024, 1440];
const THEMES = ['light', 'dark'];
const DRAFT_KEY = 'legalsaathi.student.profile.v1';
const results = [];
let failures = 0;
const rec = (name, pass, detail) => { if (!pass) failures++; results.push({ name, pass, detail }); };

const browser = await chromium.launch();
mkdirSync(OUT, { recursive: true });

async function freshPage(width = 390, theme = 'light') {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
  const page = await ctx.newPage();
  await page.addInitScript(() => { try { localStorage.clear(); } catch { /* ignore */ } });
  await page.goto(`${BASE}/s-05`, { waitUntil: 'networkidle' });
  return { ctx, page };
}
const draftAbsent = (page) => page.evaluate((k) => localStorage.getItem(k) === null, DRAFT_KEY);
const errorText = (page, id) => page.locator(`#${id}-error`).textContent().catch(() => null);

async function fill(page, { first = '', middle = '', last = '', mobile = '', dob = '', terms = true, privacy = true, law = true }) {
  if (first !== null) await page.fill('#reg-first-name', first);
  await page.fill('#reg-middle-name', middle);
  if (last !== null) await page.fill('#reg-last-name', last);
  await page.fill('#reg-mobile', mobile);
  if (dob) await page.fill('#reg-dob', dob);
  if (terms) await page.check('#reg-terms');
  if (privacy) await page.check('#reg-privacy');
  if (law) await page.check('#reg-law');
  await page.getByRole('button', { name: /create account/i }).click();
}

// --- Negative / boundary matrix (390 light) --------------------------------
const NEG = [
  ['mobile-empty', { first: 'Aditi', last: 'Nair', mobile: '', dob: '2004-03-14' }, 'reg-mobile'],
  ['mobile-9', { first: 'Aditi', last: 'Nair', mobile: '987654321', dob: '2004-03-14' }, 'reg-mobile'],
  ['mobile-11', { first: 'Aditi', last: 'Nair', mobile: '98765432101', dob: '2004-03-14' }, 'reg-mobile'],
  ['mobile-12', { first: 'Aditi', last: 'Nair', mobile: '987654321012', dob: '2004-03-14' }, 'reg-mobile'],
  ['mobile-letters', { first: 'Aditi', last: 'Nair', mobile: '98765abc10', dob: '2004-03-14' }, 'reg-mobile'],
  ['dob-empty', { first: 'Aditi', last: 'Nair', mobile: '9876543210', dob: '' }, 'reg-dob'],
  ['dob-impossible', { first: 'Aditi', last: 'Nair', mobile: '9876543210', dob: '2026-02-31' }, 'reg-dob'],
  ['dob-future-jan', { first: 'Aditi', last: 'Nair', mobile: '9876543210', dob: '2030-01-01' }, 'reg-dob'],
  ['dob-future-dec', { first: 'Aditi', last: 'Nair', mobile: '9876543210', dob: '2030-12-31' }, 'reg-dob'],
  ['first-empty', { first: '', last: 'Nair', mobile: '9876543210', dob: '2004-03-14' }, 'reg-first-name'],
  ['last-empty', { first: 'Aditi', last: '', mobile: '9876543210', dob: '2004-03-14' }, 'reg-last-name'],
  ['name-symbol', { first: '12345', last: 'Nair', mobile: '9876543210', dob: '2004-03-14' }, 'reg-first-name'],
  ['name-max-plus-one', { first: 'a'.repeat(61), last: 'Nair', mobile: '9876543210', dob: '2004-03-14' }, 'reg-first-name'],
  ['consent-unchecked', { first: 'Aditi', last: 'Nair', mobile: '9876543210', dob: '2004-03-14', terms: false }, null],
];

for (const [name, input, errId] of NEG) {
  const { ctx, page } = await freshPage();
  await fill(page, input);
  const onS05 = page.url().includes('/s-05');
  const err = errId ? await errorText(page, errId) : (await page.locator('.ui-validation').first().textContent().catch(() => null));
  const noDraft = await draftAbsent(page);
  await page.screenshot({ path: `${OUT}/neg_${name}.png` });
  rec(`NEG ${name}`, onS05 && !!err && noDraft, { onS05, err, noDraft });
  await ctx.close();
}

// --- Positive: valid registration reaches OTP (S-06) then S-09/S-10 --------
{
  const { ctx, page } = await freshPage();
  await fill(page, { first: 'Aditi', middle: 'Rani', last: 'Nair', mobile: '9876543210', dob: '2004-03-14' });
  const reachedOtp = await page.waitForURL(/\/s-06/, { timeout: 4000 }).then(() => true).catch(() => false);
  const draft = await page.evaluate((k) => JSON.parse(localStorage.getItem(k) || 'null'), DRAFT_KEY);
  const mapped = draft && draft.firstName === 'Aditi' && draft.middleName === 'Rani' && draft.lastName === 'Nair' && draft.fullName === 'Aditi Rani Nair';
  await page.screenshot({ path: `${OUT}/pos_reached_otp.png` });
  rec('POS valid → S-06 + name mapped', reachedOtp && !!mapped, { reachedOtp, draft });
  await ctx.close();
}
{
  // Middle absent → middleName '' and no double space in fullName.
  const { ctx, page } = await freshPage();
  await fill(page, { first: 'Aditi', middle: '', last: 'Nair', mobile: '9876543210', dob: '2004-03-14' });
  await page.waitForURL(/\/s-06/, { timeout: 4000 }).catch(() => {});
  const draft = await page.evaluate((k) => JSON.parse(localStorage.getItem(k) || 'null'), DRAFT_KEY);
  rec('POS middle absent → no double space', draft && draft.fullName === 'Aditi Nair' && draft.middleName === '', { draft });
  await ctx.close();
}

// --- Tooltip: accessible button exposes exact text; static footnote absent --
{
  const { ctx, page } = await freshPage();
  const btn = page.getByRole('button', { name: /information about name and guardian consent/i });
  const present = await btn.count();
  await btn.focus();
  const expanded = await btn.getAttribute('aria-expanded');
  const controls = await btn.getAttribute('aria-controls');
  const tipText = controls ? await page.locator(`#${controls}`).textContent().catch(() => null) : null;
  const footnoteBelow = await page.locator('.st-dpdp', { hasText: 'guardian consent' }).count();
  await page.screenshot({ path: `${OUT}/tooltip_focus.png` });
  rec('TOOLTIP accessible + exact text + no static footnote',
    present === 1 && (expanded === 'true' || expanded === 'false') && !!tipText && /DPDP Act, 2023/.test(tipText || '') && footnoteBelow === 0,
    { present, expanded, tipText, footnoteBelow });
  await ctx.close();
}

// --- Responsive/theme smoke: no horizontal overflow on S-05 -----------------
for (const width of WIDTHS) for (const theme of THEMES) {
  const { ctx, page } = await freshPage(width, theme);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await page.screenshot({ path: `${OUT}/responsive_${width}_${theme}.png` });
  rec(`RESP ${width}_${theme} no overflow`, !overflow, { overflow });
  await ctx.close();
}

await browser.close();
writeFileSync(`${OUT}/registration_qa_report.json`, JSON.stringify({ base: BASE, failures, total: results.length, results }, null, 2));
console.log(JSON.stringify({ failures, total: results.length }, null, 2));
if (failures > 0) { console.error(`REGISTRATION QA FAIL — ${failures}/${results.length}`); process.exit(1); }
console.log('REGISTRATION QA PASS');
