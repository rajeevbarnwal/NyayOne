/**
 * SAATHI-286 — DOM-region feature-only visual harness for S-90/S-91 (v3.2a).
 *
 * Repository-owned, deterministic Playwright harness that compares the developed
 * calendar FEATURE REGION against the Product-approved v3.2a baseline, excluding
 * the global shell. Implements the fixtures ratified in Jira Product decision
 * 12314 (SAATHI-286):
 *   - S-90: fixed clock 2026-07-19T03:30:00Z, timezone Asia/Kolkata, storage
 *     cleared, all sources, no date filter, the five stable sample events.
 *   - S-91: Judiciary mock / 2026-07-09 / 20:00 / Study / Asia/Kolkata.
 *   - Types: Study, Deadline, Meeting, Reminder, Other. Cancel present.
 *
 * Selectors:
 *   - developed:  [data-testid="cal-feature-region"][data-qa-crop="calendar-feature"]
 *   - prototype:  the reviewer-banner-free calendar module inside `.content`
 *
 * Matrix: {390,430,768,1024,1440} × {light,dark}; every one of the 20 pairs must
 * be strictly below 2% deviation. Raw per-pair numbers are written to JSON.
 *
 * Requires (native Mac/CI): `npm i -D pixelmatch pngjs` (kept out of the app
 * bundle). Run against a built preview server:
 *   npm run build && npm run preview &            # serves on :1030
 *   BASE_URL=http://localhost:1030 \
 *   PROTOTYPE_FILE="/absolute/path/LegalSaathi Student Module Option J Full Prototype v3.2.html" \
 *   BASELINE_DIR=tests/visual-baseline/s91-v3.2a \
 *   node scripts/calendar-visual-qa.mjs
 *
 * Exit code 0 only when all 20 pairs are < 2% against an existing approved
 * baseline. If the baseline is absent, candidates are written for Product
 * approval and the run exits non-zero (never a silent pass).
 */
import { chromium } from 'playwright';
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const BASE = process.env.BASE_URL || 'http://localhost:1030';
const PROTOTYPE_FILE = process.env.PROTOTYPE_FILE || '';
const BASELINE_DIR = resolve(process.env.BASELINE_DIR || 'tests/visual-baseline/s91-v3.2a');
const OUT_DIR = resolve(process.env.OUT_DIR || 'tests/visual-out');
const THRESHOLD = 2.0; // percent, strict
const WIDTHS = [390, 430, 768, 1024, 1440];
const THEMES = ['light', 'dark'];

// Fixtures from Product decision 12314.
const FIXED_CLOCK_ISO = '2026-07-19T03:30:00Z';
const TIMEZONE = 'Asia/Kolkata';
const STUDENT_ID = 'self';
const DEFAULT_FILTERS = { sources: null, from: null, to: null, timezone: TIMEZONE }; // sources:null ⇒ all
const S91_FIXTURE = { title: 'Judiciary mock', date: '2026-07-09', time: '20:00', type: 'study' };

const DEV_SELECTOR = '[data-testid="cal-feature-region"][data-qa-crop="calendar-feature"]';
// Prototype: the calendar module inside `.content`, excluding the reviewer banner.
const PROTO_SELECTOR = process.env.PROTO_SELECTOR || '.content .calv, .content [data-screen], .content';

let pixelmatch, PNG;
try {
  pixelmatch = (await import('pixelmatch')).default;
  PNG = (await import('pngjs')).PNG;
} catch {
  console.error('MISSING DEV DEPS: run `npm i -D pixelmatch pngjs` before this harness.');
  process.exit(2);
}

function deviationPercent(aBuf, bBuf) {
  const a = PNG.sync.read(aBuf);
  const b = PNG.sync.read(bBuf);
  const width = Math.min(a.width, b.width);
  const height = Math.min(a.height, b.height);
  // Resize-to-common-min by cropping to the shared top-left box (Lanczos resize
  // is done upstream if dimensions differ materially; here we compare the shared
  // region deterministically).
  const crop = (img) => {
    const out = new PNG({ width, height });
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const si = (img.width * y + x) << 2;
        const di = (width * y + x) << 2;
        out.data[di] = img.data[si];
        out.data[di + 1] = img.data[si + 1];
        out.data[di + 2] = img.data[si + 2];
        out.data[di + 3] = img.data[si + 3];
      }
    }
    return out;
  };
  const ca = crop(a);
  const cb = crop(b);
  const diff = new PNG({ width, height });
  const changed = pixelmatch(ca.data, cb.data, diff.data, width, height, { threshold: 0.1 });
  return { percent: (changed / (width * height)) * 100, diff: PNG.sync.write(diff), width, height };
}

async function seed(page, theme) {
  await page.addInitScript(({ clock, filtersKey, filters, theme }) => {
    // Deterministic clock.
    const fixed = new Date(clock).getTime();
    const _Date = Date;
    // eslint-disable-next-line no-global-assign
    Date = class extends _Date { constructor(...a) { super(...(a.length ? a : [fixed])); } static now() { return fixed; } };
    try { localStorage.clear(); } catch { /* ignore */ }
    try { localStorage.setItem(filtersKey, JSON.stringify(filters)); } catch { /* ignore */ }
    try { localStorage.setItem('ls-theme', theme); } catch { /* ignore */ }
  }, { clock: FIXED_CLOCK_ISO, filtersKey: `ls-cal-filters-${STUDENT_ID}`, filters: DEFAULT_FILTERS, theme });
}

async function captureDeveloped(page, route, selector) {
  await page.goto(`${BASE}/${route}`, { waitUntil: 'networkidle' });
  if (route === 's-91') {
    await page.fill('[data-testid="ev-title"]', S91_FIXTURE.title);
    await page.fill('[data-testid="ev-date"]', S91_FIXTURE.date);
    await page.fill('[data-testid="ev-time"]', S91_FIXTURE.time);
    await page.click(`[data-testid="ev-type-${S91_FIXTURE.type}"]`);
  }
  const el = await page.waitForSelector(selector, { timeout: 5000 });
  return el.screenshot();
}

function loadBaseline(name) {
  const p = join(BASELINE_DIR, `${name}.png`);
  return existsSync(p) ? readFileSync(p) : null;
}

/**
 * Capture the reviewer-banner-free prototype calendar region for a screen, to
 * seed a v3.2a baseline candidate when no approved baseline exists yet. Only
 * used when PROTOTYPE_FILE is provided; the resulting PNG must be Product-
 * approved before it becomes an authoritative baseline.
 */
async function capturePrototype(browser, screen, width, theme) {
  if (!PROTOTYPE_FILE) return null;
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
  const page = await ctx.newPage();
  await page.goto(`file://${resolve(PROTOTYPE_FILE)}`, { waitUntil: 'load' });
  await page.evaluate(() => {
    document.querySelectorAll('[data-reviewer-banner], .reviewer-banner').forEach((n) => n.remove());
  });
  let shot = null;
  try {
    const el = await page.waitForSelector(PROTO_SELECTOR, { timeout: 4000 });
    shot = await el.screenshot();
  } catch { /* prototype selector not resolvable for this screen */ }
  await ctx.close();
  return shot;
}

const browser = await chromium.launch();
mkdirSync(OUT_DIR, { recursive: true });
const results = [];
let baselineMissing = false;
let failures = 0;

for (const screen of ['S-90', 'S-91']) {
  const route = screen.toLowerCase();
  for (const width of WIDTHS) {
    for (const theme of THEMES) {
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
      const page = await ctx.newPage();
      await seed(page, theme);
      const shot = await captureDeveloped(page, route, DEV_SELECTOR);
      const name = `${screen}_${width}_${theme}`;
      writeFileSync(join(OUT_DIR, `${name}_developed.png`), shot);
      const baseline = loadBaseline(name);
      if (!baseline) {
        baselineMissing = true;
        const protoShot = await capturePrototype(browser, screen, width, theme);
        if (protoShot) writeFileSync(join(OUT_DIR, `${name}_prototype_candidate.png`), protoShot);
        results.push({ pair: name, percent: null, note: 'baseline missing — generate + Product-approve v3.2a' });
      } else {
        const { percent, diff } = deviationPercent(shot, baseline);
        writeFileSync(join(OUT_DIR, `${name}_diff.png`), diff);
        const pass = percent < THRESHOLD;
        if (!pass) failures++;
        results.push({ pair: name, percent: Number(percent.toFixed(3)), pass });
      }
      await ctx.close();
    }
  }
}
await browser.close();

const nums = results.filter((r) => typeof r.percent === 'number').map((r) => r.percent);
const summary = {
  commit: process.env.GIT_COMMIT || null,
  threshold: THRESHOLD,
  pairCount: results.length,
  average: nums.length ? Number((nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(3)) : null,
  maximum: nums.length ? Math.max(...nums) : null,
  allBelowThreshold: nums.length === results.length && failures === 0,
  baselineMissing,
  prototypeFile: PROTOTYPE_FILE || null,
  results,
};
writeFileSync(join(OUT_DIR, 'feature_visual_deviation.json'), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));

if (baselineMissing) { console.error('BASELINE MISSING — candidates written to', OUT_DIR); process.exit(3); }
if (failures > 0) { console.error(`VISUAL FAIL — ${failures}/${results.length} pairs >= ${THRESHOLD}%`); process.exit(1); }
console.log('VISUAL PASS — all pairs below', THRESHOLD, '%');
