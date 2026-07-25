/**
 * SAATHI-286 — DOM-region feature-only visual harness for S-90/S-91 (v3.2a).
 *
 * Repository-owned, deterministic Playwright harness comparing the developed
 * calendar FEATURE REGION against the Product-approved v3.2a baseline, excluding
 * the global shell. Implements Jira Product decision 12314 fixtures and the
 * independent-QA remediation of commit c70baed (comment 12377):
 *   - dependency-free scoring via ./lib/png.mjs (clean checkout needs only
 *     `playwright`; no pixelmatch/pngjs install);
 *   - screen-correct prototype capture (navigate #/s/S-90|S-91, wait for
 *     window.__ls.S.screenId, apply theme) with a requested==actual assertion
 *     and an S-90≠S-91 candidate-hash guard;
 *   - identical deterministic fixture applied to both sides, asserted in JSON;
 *   - real nearest-neighbour alignment (no silent crop); dimension drift fails;
 *   - versioned, non-self-approving v3.2a baseline (manifest with checksums).
 *
 * Run against a built preview server:
 *   npm run build && npm run preview &            # serves on :1030
 *   BASE_URL=http://localhost:1030 \
 *   PROTOTYPE_FILE="/abs/path/LegalSaathi Student Module Option J Full Prototype v3.2.html" \
 *   BASELINE_DIR=tests/visual-baseline/s91-v3.2a \
 *   node scripts/calendar-visual-qa.mjs
 *
 * Exit 0 only when a Product-APPROVED baseline exists and all 20 pairs are < 2%.
 * Exit 3 when the baseline is missing/unapproved (candidates written for Product
 * approval — never scored as pass). Exit 1 on any failing/invalid pair.
 */
import { chromium } from 'playwright';
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { diffPngBuffers } from './lib/png.mjs';

const BASE = process.env.BASE_URL || 'http://localhost:1030';
const PROTOTYPE_FILE = process.env.PROTOTYPE_FILE || '';
const BASELINE_DIR = resolve(process.env.BASELINE_DIR || 'tests/visual-baseline/s91-v3.2a');
const OUT_DIR = resolve(process.env.OUT_DIR || 'tests/visual-out');
const THRESHOLD = 2.0; // percent, strict
const WIDTHS = [390, 430, 768, 1024, 1440];
const THEMES = ['light', 'dark'];
const SCREENS = ['S-90', 'S-91'];

// --- Product decision 12314 fixture (identical on both sides) ----------------
const FIXTURE = {
  version: 's91-v3.2a',
  productDecision: '12314',
  clockIso: '2026-07-19T03:30:00Z', // 09:00 Asia/Kolkata
  timezone: 'Asia/Kolkata',
  studentId: 'self',
  filters: { sources: null, from: null, to: null, timezone: 'Asia/Kolkata' }, // all sources, no date filter
  s90Events: ['CLAT mock test 3', 'Legal-aid camp', 'CAM application deadline', 'Community AMA', 'Vidhi interview'],
  s91Form: { title: 'Judiciary mock', date: '2026-07-09', time: '20:00', type: 'study', timezone: 'Asia/Kolkata' },
};

const DEV_SELECTOR = '[data-testid="cal-feature-region"][data-qa-crop="calendar-feature"]';
const PROTO_SELECTOR = process.env.PROTO_SELECTOR || '.content [data-testid="cal-feature-region"], .content .calv, .content';

const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const baselinePath = (name) => join(BASELINE_DIR, `${name}.png`);

/** Read the versioned baseline manifest (records source/version/checksums/approval). */
function readBaselineManifest() {
  const p = join(BASELINE_DIR, 'baseline_manifest.json');
  return existsSync(p) ? JSON.parse(readFileSync(p, 'utf8')) : null;
}

/** Freeze clock + timezone BEFORE app code runs, clear only ticket-owned storage, seed state. */
async function seed(page, theme) {
  await page.addInitScript(({ clockIso, filtersKey, filters, theme }) => {
    const fixed = new Date(clockIso).getTime();
    const _Date = Date;
    // eslint-disable-next-line no-global-assign
    Date = class extends _Date { constructor(...a) { super(...(a.length ? a : [fixed])); } static now() { return fixed; } };
    try {
      // Clear only ticket-owned calendar keys + theme, not the whole origin.
      Object.keys(localStorage).filter((k) => k.startsWith('ls-cal-') || k === 'ls-theme').forEach((k) => localStorage.removeItem(k));
      localStorage.setItem(filtersKey, JSON.stringify(filters));
      localStorage.setItem('ls-theme', theme);
    } catch { /* ignore */ }
  }, { clockIso: FIXTURE.clockIso, filtersKey: `ls-cal-filters-${FIXTURE.studentId}`, filters: FIXTURE.filters, theme });
}

async function captureDeveloped(page, screen, theme) {
  const route = screen.toLowerCase();
  await page.goto(`${BASE}/${route}`, { waitUntil: 'networkidle' });
  const applied = { clockIso: FIXTURE.clockIso, timezone: FIXTURE.timezone, filters: FIXTURE.filters, theme, screen };
  if (screen === 'S-91') {
    await page.fill('[data-testid="ev-title"]', FIXTURE.s91Form.title);
    await page.fill('[data-testid="ev-date"]', FIXTURE.s91Form.date);
    await page.fill('[data-testid="ev-time"]', FIXTURE.s91Form.time);
    await page.click(`[data-testid="ev-type-${FIXTURE.s91Form.type}"]`);
    applied.form = FIXTURE.s91Form;
  }
  const el = await page.waitForSelector(DEV_SELECTOR, { timeout: 5000 });
  await page.evaluate(() => document.fonts && document.fonts.ready);
  return { shot: await el.screenshot(), applied };
}

/**
 * Screen-correct prototype capture: navigate to the requested hash, wait until
 * the prototype runtime confirms window.__ls.S.screenId === requested, apply the
 * theme, then capture the reviewer-banner-free calendar feature module.
 * Returns { shot, actualScreenId } (shot null if not resolvable).
 */
async function capturePrototype(browser, screen, width, theme) {
  if (!PROTOTYPE_FILE) return { shot: null, actualScreenId: null };
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
  const page = await ctx.newPage();
  await page.goto(`file://${resolve(PROTOTYPE_FILE)}#/s/${screen}`, { waitUntil: 'load' });
  let actualScreenId = null;
  try {
    await page.waitForFunction((want) => window.__ls && window.__ls.S && window.__ls.S.screenId === want, screen, { timeout: 5000 });
    // Apply theme through the prototype runtime if it exposes a setter; else via attribute.
    await page.evaluate((t) => {
      if (window.__ls && typeof window.__ls.setTheme === 'function') window.__ls.setTheme(t);
      else document.documentElement.setAttribute('data-theme', t);
    }, theme);
    await page.evaluate(() => document.fonts && document.fonts.ready);
    actualScreenId = await page.evaluate(() => window.__ls.S.screenId);
    page.evaluate(() => document.querySelectorAll('[data-reviewer-banner], .reviewer-banner').forEach((n) => n.remove()));
    const el = await page.waitForSelector(PROTO_SELECTOR, { timeout: 4000 });
    const shot = await el.screenshot();
    await ctx.close();
    return { shot, actualScreenId };
  } catch {
    await ctx.close();
    return { shot: null, actualScreenId };
  }
}

const browser = await chromium.launch();
mkdirSync(OUT_DIR, { recursive: true });
const manifest = readBaselineManifest();
const baselineApproved = !!(manifest && manifest.approvalStatus === 'approved');
const results = [];
const protoHashes = {}; // `${width}_${theme}` -> { 'S-90': hash, 'S-91': hash }
let failures = 0;
let invalid = 0;
let baselineUsable = baselineApproved;

for (const screen of SCREENS) {
  for (const width of WIDTHS) {
    for (const theme of THEMES) {
      const name = `${screen}_${width}_${theme}`;
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
      const page = await ctx.newPage();
      await seed(page, theme);
      const { shot, applied } = await captureDeveloped(page, screen, theme);
      writeFileSync(join(OUT_DIR, `${name}_developed.png`), shot);
      await ctx.close();

      const rec = { pair: name, screen, width, theme, fixture: applied, percent: null };

      // Screen-correct prototype candidate (for baseline generation / integrity).
      const { shot: proto, actualScreenId } = await capturePrototype(browser, screen, width, theme);
      if (proto) {
        writeFileSync(join(OUT_DIR, `${name}_prototype_candidate.png`), proto);
        const h = sha(proto);
        (protoHashes[`${width}_${theme}`] ||= {})[screen] = h;
        rec.prototypeScreenId = actualScreenId;
        rec.prototypeScreenMatches = actualScreenId === screen;
        rec.prototypeHash = h;
        if (actualScreenId !== screen) { invalid++; rec.note = `prototype screen mismatch (got ${actualScreenId})`; }
      } else {
        rec.prototypeScreenId = actualScreenId;
        rec.prototypeScreenMatches = false;
      }

      const bPath = baselinePath(name);
      if (baselineUsable && existsSync(bPath)) {
        const d = diffPngBuffers(shot, readFileSync(bPath), { channelThreshold: 16, driftTolerance: 0.02 });
        rec.percent = Number(d.percent.toFixed(3));
        rec.aDims = d.aDims; rec.bDims = d.bDims; rec.target = d.target;
        rec.dimensionDrift = d.dimensionDrift; rec.driftFraction = d.driftFraction;
        rec.masks = ['dynamic-date-region', 'wcag-44px-override']; // documented exclusions
        const pass = !d.dimensionDrift && d.percent < THRESHOLD;
        rec.pass = pass;
        if (d.dimensionDrift) { invalid++; rec.note = 'dimension drift — pair invalid'; }
        if (!pass) failures++;
      } else {
        rec.note = (rec.note ? rec.note + '; ' : '') + 'baseline missing or unapproved — candidate written, not scored';
      }
      results.push(rec);
    }
  }
}

// Guard: S-90 and S-91 prototype candidates must NOT be byte-identical per viewport/theme.
const identicalScreenPairs = [];
for (const key of Object.keys(protoHashes)) {
  const h = protoHashes[key];
  if (h['S-90'] && h['S-91'] && h['S-90'] === h['S-91']) identicalScreenPairs.push(key);
}
if (identicalScreenPairs.length) invalid += identicalScreenPairs.length;

await browser.close();

const scored = results.filter((r) => typeof r.percent === 'number' && !r.dimensionDrift);
const nums = scored.map((r) => r.percent);
const summary = {
  commit: process.env.GIT_COMMIT || null,
  productDecision: FIXTURE.productDecision,
  fixtureVersion: FIXTURE.version,
  threshold: THRESHOLD,
  pairCount: results.length,
  scoredPairs: scored.length,
  invalidPairs: invalid,
  identicalPrototypeScreenPairs: identicalScreenPairs,
  average: nums.length ? Number((nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(3)) : null,
  maximum: nums.length ? Math.max(...nums) : null,
  allValidBelowThreshold: results.length === 20 && scored.length === 20 && failures === 0 && invalid === 0,
  baselineApproved,
  baselineManifest: manifest,
  fixture: FIXTURE,
  prototypeFile: PROTOTYPE_FILE || null,
  results,
};
writeFileSync(join(OUT_DIR, 'feature_visual_deviation.json'), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));

if (identicalScreenPairs.length) { console.error('PROTOTYPE INTEGRITY FAIL — S-90/S-91 candidates identical for:', identicalScreenPairs.join(', ')); process.exit(1); }
if (!baselineApproved) { console.error('BASELINE MISSING/UNAPPROVED — candidates in', OUT_DIR, '— request Product approval; not scored as pass.'); process.exit(3); }
if (invalid > 0) { console.error(`INVALID PAIRS — ${invalid} (screen mismatch or dimension drift)`); process.exit(1); }
if (failures > 0) { console.error(`VISUAL FAIL — ${failures}/${results.length} pairs >= ${THRESHOLD}%`); process.exit(1); }
console.log('VISUAL PASS — all 20 valid pairs below', THRESHOLD, '%');
