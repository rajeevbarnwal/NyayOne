/**
 * SAATHI-286 — DOM-region feature-only visual gate for S-90/S-91 (v3.2a).
 *
 * Repository-owned, deterministic Playwright harness implementing Jira Product
 * decision 12314 and the independent-QA remediation of commit abce339 (comment
 * 12448). Two modes:
 *   MODE=generate  — capture the developed calendar FEATURE REGION under the
 *                    Product-approved fixture for all 20 pairs, write them as the
 *                    versioned v3.2a baseline candidates, and emit a checksum
 *                    manifest (approvalStatus: "pending"). Product must approve.
 *   MODE=verify    — (default) cryptographically verify the approved baseline,
 *                    then re-capture the developed side and require every one of
 *                    the 20 pairs strictly below 2%.
 *
 * Design decisions from QA 12448:
 *   - The v3.2a baseline is generated from the DEVELOPED app under the fixture
 *     (Product ratified the developed schema) — NOT from the superseded v3.2
 *     Exam/Moot/Personal/no-Cancel mock, which cannot render the approved schema.
 *     A canonical developed-source baseline needs NO visual exclusions (masks=[]).
 *   - The feature region is a calendar-specific selector, never broad `.content`;
 *     the developed app has no reviewer banner/global shell inside it.
 *   - The identical fixture is applied AND asserted (read back from the DOM) on
 *     both sides before every screenshot.
 *   - Approval is not trusted from text alone: every PNG SHA-256 is recomputed
 *     and matched to the manifest; missing/extra/changed files fail.
 *
 * Run against a built preview server:
 *   npm run build && npm run preview &                 # serves on :1130
 *   GIT_COMMIT=$(git rev-parse HEAD) MODE=generate \
 *   BASE_URL=http://localhost:1130 BASELINE_DIR=tests/visual-baseline/s91-v3.2a \
 *   node scripts/calendar-visual-qa.mjs                # writes candidates + manifest
 *   # → Product approves the candidate pack, records approvalCommentId, sets approved
 *   MODE=verify … node scripts/calendar-visual-qa.mjs  # enforces all 20 < 2%
 */
import { chromium } from 'playwright';
import { readFileSync, existsSync, mkdirSync, writeFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { diffPngBuffers, sideBySide, diffOverlay } from './lib/png.mjs';

const MODE = process.env.MODE || 'verify';
const BASE = process.env.BASE_URL || 'http://localhost:1130';
const BASELINE_DIR = resolve(process.env.BASELINE_DIR || 'tests/visual-baseline/s91-v3.2a');
const OUT_DIR = resolve(process.env.OUT_DIR || 'tests/visual-out');
const THRESHOLD = 2.0;
const WIDTHS = [390, 430, 768, 1024, 1440];
const THEMES = ['light', 'dark'];
const SCREENS = ['S-90', 'S-91'];
const MASKS = []; // canonical developed-source baseline requires no exclusions

const FIXTURE = {
  version: 's91-v3.2a',
  productDecision: '12314',
  clockIso: '2026-07-19T03:30:00Z',
  timezone: 'Asia/Kolkata',
  studentId: 'self',
  filters: { sources: null, from: null, to: null, timezone: 'Asia/Kolkata' },
  s90Events: ['CLAT mock test 3', 'Legal-aid camp', 'CAM application deadline', 'Community AMA', 'Vidhi interview'],
  s91Form: { title: 'Judiciary mock', date: '2026-07-09', time: '20:00', type: 'study', timezone: 'Asia/Kolkata' },
};

const FEATURE_SELECTOR = '[data-testid="cal-feature-region"][data-qa-crop="calendar-feature"]';
const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const nameOf = (screen, width, theme) => `${screen}_${width}_${theme}`;

async function seed(page, theme) {
  await page.addInitScript(({ clockIso, filtersKey, filters, theme }) => {
    const fixed = new Date(clockIso).getTime();
    const _Date = Date;
    // eslint-disable-next-line no-global-assign
    Date = class extends _Date { constructor(...a) { super(...(a.length ? a : [fixed])); } static now() { return fixed; } };
    try {
      Object.keys(localStorage).filter((k) => k.startsWith('ls-cal-') || k === 'nyayone.theme.v1').forEach((k) => localStorage.removeItem(k));
      localStorage.setItem(filtersKey, JSON.stringify(filters));
      localStorage.setItem('nyayone.theme.v1', theme);
    } catch { /* ignore */ }
  }, { clockIso: FIXTURE.clockIso, filtersKey: `ls-cal-filters-${FIXTURE.studentId}`, filters: FIXTURE.filters, theme });
}

/** Capture the developed feature region under the fixture, asserting fixture identity. */
async function captureDeveloped(browser, screen, width, theme) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
  const page = await ctx.newPage();
  await seed(page, theme);
  const route = screen.toLowerCase();
  await page.goto(`${BASE}/${route}`, { waitUntil: 'networkidle' });
  if (!page.url().endsWith(`/${route}`)) { await ctx.close(); throw new Error(`wrong screen: ${page.url()} != /${route}`); }
  const applied = { clockIso: FIXTURE.clockIso, timezone: FIXTURE.timezone, filters: FIXTURE.filters, theme, screen };
  if (screen === 'S-91') {
    await page.fill('[data-testid="ev-title"]', FIXTURE.s91Form.title);
    await page.fill('[data-testid="ev-date"]', FIXTURE.s91Form.date);
    await page.fill('[data-testid="ev-time"]', FIXTURE.s91Form.time);
    await page.click(`[data-testid="ev-type-${FIXTURE.s91Form.type}"]`);
    // Assert fixture identity from the DOM before capture.
    const readBack = await page.evaluate(() => {
      const v = (sel) => document.querySelector(sel)?.value ?? null;
      const pressed = document.querySelector('.type-chips [aria-pressed="true"]');
      return {
        title: v('[data-testid="ev-title"]'),
        date: v('[data-testid="ev-date"]'),
        time: v('[data-testid="ev-time"]'),
        type: pressed ? pressed.getAttribute('data-testid').replace('ev-type-', '') : null,
        cancel: !!document.querySelector('[data-testid="ev-cancel"]'),
      };
    });
    if (readBack.title !== FIXTURE.s91Form.title || readBack.date !== FIXTURE.s91Form.date ||
        readBack.time !== FIXTURE.s91Form.time || readBack.type !== FIXTURE.s91Form.type || !readBack.cancel) {
      await ctx.close();
      throw new Error(`S-91 fixture mismatch: ${JSON.stringify(readBack)}`);
    }
    applied.form = FIXTURE.s91Form;
    applied.cancelPresent = readBack.cancel;
  }
  const el = await page.waitForSelector(FEATURE_SELECTOR, { timeout: 5000 });
  await page.evaluate(async () => { if (document.fonts) await document.fonts.ready; });
  const shot = await el.screenshot();
  await ctx.close();
  return { shot, applied };
}

function readManifest() {
  const p = join(BASELINE_DIR, 'baseline_manifest.json');
  return existsSync(p) ? JSON.parse(readFileSync(p, 'utf8')) : null;
}

/** Cryptographically verify the approved baseline: approval fields + every checksum. */
function verifyBaselineIntegrity(manifest) {
  const problems = [];
  if (!manifest) return ['baseline_manifest.json missing'];
  if (manifest.approvalStatus !== 'approved') problems.push(`approvalStatus is "${manifest.approvalStatus}", not "approved"`);
  if (!manifest.approvalCommentId) problems.push('approvalCommentId is empty (no Product approval recorded)');
  const checksums = manifest.checksums || {};
  const listed = Object.keys(checksums);
  if (listed.length !== 20) problems.push(`manifest lists ${listed.length} checksummed PNGs, expected 20`);
  // Missing / changed
  for (const rel of listed) {
    const p = join(BASELINE_DIR, rel);
    if (!existsSync(p)) { problems.push(`missing baseline file: ${rel}`); continue; }
    const actual = sha(readFileSync(p));
    if (actual !== checksums[rel]) problems.push(`checksum mismatch (tampered): ${rel}`);
  }
  // Extra PNGs not in the manifest
  if (existsSync(BASELINE_DIR)) {
    for (const f of readdirSync(BASELINE_DIR)) {
      if (f.endsWith('.png') && !listed.includes(f)) problems.push(`extra baseline file not in manifest: ${f}`);
    }
  }
  return problems;
}

const browser = await chromium.launch();
mkdirSync(OUT_DIR, { recursive: true });

if (MODE === 'generate') {
  mkdirSync(BASELINE_DIR, { recursive: true });
  const checksums = {};
  for (const screen of SCREENS) for (const width of WIDTHS) for (const theme of THEMES) {
    const name = nameOf(screen, width, theme);
    const { shot } = await captureDeveloped(browser, screen, width, theme);
    const rel = `${name}.png`;
    writeFileSync(join(BASELINE_DIR, rel), shot);
    checksums[rel] = sha(shot);
  }
  await browser.close();
  const manifest = {
    version: FIXTURE.version,
    sourceReference: 'developed calendar S-90/S-91 rendered under Product decision 12314 fixture (original v3.2 prototype preserved separately, unchanged)',
    productDecision: FIXTURE.productDecision,
    fixtureVersion: FIXTURE.version,
    generatedDate: new Date().toISOString(),
    generatedFromCommit: process.env.GIT_COMMIT || null,
    checksums,
    approvalStatus: 'pending',
    approvalCommentId: null,
    masks: MASKS,
    notes: 'Candidate pack for Product approval. approvalStatus stays "pending" until a Product Jira comment approves these exact images; the verify mode recomputes every SHA-256 and refuses to run on any missing/extra/changed file. The harness never self-approves.',
  };
  writeFileSync(join(BASELINE_DIR, 'baseline_manifest.json'), JSON.stringify(manifest, null, 2));
  console.log(`GENERATED 20 v3.2a candidates + manifest in ${BASELINE_DIR} (approvalStatus: pending). Request Product approval.`);
  process.exit(3);
}

// MODE=verify
const manifest = readManifest();
const integrity = verifyBaselineIntegrity(manifest);
if (integrity.length) {
  console.error('BASELINE INTEGRITY / APPROVAL FAIL:\n - ' + integrity.join('\n - '));
  await browser.close();
  process.exit(3);
}

const results = [];
let failures = 0, invalid = 0;
for (const screen of SCREENS) for (const width of WIDTHS) for (const theme of THEMES) {
  const name = nameOf(screen, width, theme);
  const rec = { pair: name, screen, width, theme, masks: MASKS };
  try {
    const { shot, applied } = await captureDeveloped(browser, screen, width, theme);
    rec.fixture = applied;
    const baseline = readFileSync(join(BASELINE_DIR, `${name}.png`));
    writeFileSync(join(OUT_DIR, `${name}_developed.png`), shot);
    writeFileSync(join(OUT_DIR, `${name}_baseline.png`), baseline);
    writeFileSync(join(OUT_DIR, `${name}_side_by_side.png`), sideBySide(shot, baseline));
    writeFileSync(join(OUT_DIR, `${name}_diff_overlay.png`), diffOverlay(shot, baseline, { masks: MASKS }));
    const d = diffPngBuffers(shot, baseline, { channelThreshold: 16, driftTolerance: 0.02, masks: MASKS });
    rec.percent = Number(d.percent.toFixed(3));
    rec.aDims = d.aDims; rec.bDims = d.bDims; rec.target = d.target;
    rec.dimensionDrift = d.dimensionDrift; rec.driftFraction = d.driftFraction;
    rec.maskedPixels = d.maskedPixels; rec.comparedPixels = d.comparedPixels;
    rec.pass = !d.dimensionDrift && d.percent < THRESHOLD;
    if (d.dimensionDrift) { invalid++; rec.note = 'dimension drift — invalid'; }
    if (!rec.pass) failures++;
  } catch (e) {
    invalid++; rec.percent = null; rec.pass = false; rec.note = `capture/fixture failure: ${e.message}`;
  }
  results.push(rec);
}
await browser.close();

const scored = results.filter((r) => typeof r.percent === 'number' && !r.dimensionDrift);
const nums = scored.map((r) => r.percent);
const worst = scored.slice().sort((a, b) => b.percent - a.percent)[0] || null;
const summary = {
  mode: 'verify',
  commit: process.env.GIT_COMMIT || null,
  productDecision: FIXTURE.productDecision,
  approvalCommentId: manifest.approvalCommentId,
  threshold: THRESHOLD,
  pairCount: results.length,
  scoredPairs: scored.length,
  invalidPairs: invalid,
  average: nums.length ? Number((nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(3)) : null,
  maximum: nums.length ? Math.max(...nums) : null,
  worstPair: worst ? { pair: worst.pair, percent: worst.percent } : null,
  allValidBelowThreshold: results.length === 20 && scored.length === 20 && failures === 0 && invalid === 0,
  fixture: FIXTURE,
  masks: MASKS,
  results,
};
writeFileSync(join(OUT_DIR, 'feature_visual_deviation.json'), JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));

if (invalid > 0) { console.error(`INVALID PAIRS — ${invalid}`); process.exit(1); }
if (failures > 0) { console.error(`VISUAL FAIL — ${failures}/20 pairs >= ${THRESHOLD}%`); process.exit(1); }
console.log('VISUAL PASS — all 20 valid pairs below', THRESHOLD, '%');
