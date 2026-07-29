/* Executable SELF-TESTS for the Option C2 accessibility oracle.

   These prove the oracle actually FAILS when it should. Independent QA rejected
   the previous evidence because the runner could report PASS while real
   accessibility defects were present, so the oracle is now tested with
   deliberately seeded defects before its output is trusted.

   Four required detections:
     (a) an intentionally low-contrast TEXT pair            -> must FAIL
     (b) an intentionally low-contrast FOCUS INDICATOR      -> must FAIL
     (c) an APPLICABLE low-contrast ICON / BOUNDARY         -> must FAIL
         (including: a NOT_APPLICABLE adjudication may not hide a defect when
          the named identifying icon itself fails 3:1)
     (d) stale hard-coded commit / absolute path metadata   -> must be INVALID

   Positive controls are asserted too, so "everything fails" cannot pass.

   Run:
     LD_LIBRARY_PATH=<stublib> node tests/a11y_oracle_selftest.mjs
   Environment:
     PLAYWRIGHT_MODULE  path to playwright's index.mjs (default: <repo>/frontend/node_modules/playwright/index.mjs)
     A11Y_OUT_DIR       optional directory to also write the result JSON into
*/
import { existsSync, writeFileSync, readFileSync } from 'node:fs';
import { join, dirname, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { PROBE, FOCUS_PROBE } from '../tools/a11y_oracle_probes.mjs';
import {
  RESULT, evaluateTextRow, evaluateNonTextRow, evaluateFocusRow, validateProvenance, contrastRatio
} from '../tools/a11y_oracle_core.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = join(HERE, '..');
const REPO_ROOT = execFileSync('git', ['-C', PKG, 'rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
const HEAD = execFileSync('git', ['-C', PKG, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const PKG_REL = relative(REPO_ROOT, PKG).split(sep).join('/');

const PW_PATH = [process.env.PLAYWRIGHT_MODULE, join(REPO_ROOT, 'frontend/node_modules/playwright/index.mjs')]
  .find(p => p && existsSync(p));
if (!PW_PATH) throw new Error('playwright not resolvable; set PLAYWRIGHT_MODULE');
const { chromium } = await import(pathToFileURL(PW_PATH).href);

const results = [];
function expect(id, requirement, ok, detail) {
  results.push({ id, requirement, expected: requirement, actual: detail, result: ok ? 'PASS' : 'FAIL' });
}

/* ------------------------------------------------------------------ *
 * Seeded defect fixture. Every colour here is deliberately broken.
 * ------------------------------------------------------------------ */
const SEEDED = `<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;background:#ffffff;font-family:sans-serif}
  .panel{background:#101010;padding:24px;display:flex;gap:12px;align-items:center}
  .lowtext{color:#bcbcbc;background:#ffffff;font-size:14px}
  .goodtext{color:#111111;background:#ffffff;font-size:14px}
  .ic{width:20px;height:20px;display:block}
  .ic .s{stroke:currentColor;fill:none;stroke-width:2}
  #seeded-bad-control{background:#141414;border:2px solid #1a1a1a;color:#1c1c1c;
    width:44px;height:44px;border-radius:50%;display:grid;place-items:center}
  #seeded-good-control{background:#141414;border:2px solid #1a1a1a;color:#f6efe2;
    width:44px;height:44px;border-radius:50%;display:grid;place-items:center}
  #seeded-bad-focus:focus-visible{outline:3px solid #202020;outline-offset:2px}
  #seeded-good-focus:focus-visible{outline:3px solid #ffffff;outline-offset:2px}
  .fbtn{background:#101010;border:0;color:#f6efe2;width:44px;height:44px}
</style></head><body>
  <p class="lowtext" id="lowtext">Seeded low contrast body copy</p>
  <p class="goodtext" id="goodtext">Seeded high contrast body copy</p>
  <div class="panel">
    <button id="seeded-bad-control" type="button" aria-label="Seeded low contrast control">
      <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path class="s" d="M6 12h12"/></svg></button>
    <button id="seeded-good-control" type="button" aria-label="Seeded legible control">
      <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path class="s" d="M6 12h12"/></svg></button>
    <button id="seeded-bad-focus" class="fbtn" type="button" aria-label="Seeded low contrast focus ring">A</button>
    <button id="seeded-good-focus" class="fbtn" type="button" aria-label="Seeded legible focus ring">B</button>
  </div>
</body></html>`;

const SEED_CONTROLS = [
  { sel: '#seeded-bad-control', name: 'Seeded low contrast control',
    identify: { feature: 'icon glyph', selector: '#seeded-bad-control svg.ic' } },
  { sel: '#seeded-good-control', name: 'Seeded legible control',
    identify: { feature: 'icon glyph', selector: '#seeded-good-control svg.ic' } }
];

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
const page = await ctx.newPage();
await page.setContent(SEEDED, { waitUntil: 'load' });

const probe = await page.evaluate(PROBE, { controls: SEED_CONTROLS });

/* ---------------- (a) low-contrast TEXT pair must FAIL ---------------- */
const lowText = probe.text.find(r => r.selector === '#lowtext');
const goodText = probe.text.find(r => r.selector === '#goodtext');
const lowTextEval = lowText ? evaluateTextRow(lowText) : null;
const goodTextEval = goodText ? evaluateTextRow(goodText) : null;
expect('a1', 'seeded low-contrast TEXT pair is detected as FAIL',
  !!lowTextEval && lowTextEval.result === RESULT.FAIL,
  lowTextEval ? lowTextEval.actual + ' -> ' + lowTextEval.result : 'row not produced by the probe');
expect('a2', 'positive control: legible TEXT pair is PASS',
  !!goodTextEval && goodTextEval.result === RESULT.PASS,
  goodTextEval ? goodTextEval.actual + ' -> ' + goodTextEval.result : 'row not produced by the probe');

/* ---------------- (c) low-contrast ICON / BOUNDARY ---------------- */
const badBorder = probe.nonText.find(r => r.selector === '#seeded-bad-control' && r.facet === 'border');
const badSurface = probe.nonText.find(r => r.selector === '#seeded-bad-control' && r.facet === 'surface');
const goodBorder = probe.nonText.find(r => r.selector === '#seeded-good-control' && r.facet === 'border');

const applicableBad = badBorder ? evaluateNonTextRow({ ...badBorder,
  adjudication: { status: 'APPLICABLE', reason: 'seeded: the boundary is the only identifying feature' } }) : null;
expect('c1', 'seeded low-contrast APPLICABLE BOUNDARY is detected as FAIL',
  !!applicableBad && applicableBad.result === RESULT.FAIL,
  applicableBad ? applicableBad.actual + ' -> ' + applicableBad.result : 'row not produced by the probe');

const waivedBad = badSurface ? evaluateNonTextRow({ ...badSurface, adjudication: {
  status: 'NOT_APPLICABLE', reason: 'seeded: claim that the icon identifies the control',
  identifiedBy: { feature: badSurface.identifying.feature, selector: badSurface.identifying.selector },
  substitute: { fg: badSurface.identifying.fg, bg: badSurface.identifying.bg, ratio: badSurface.identifying.ratio }
} }) : null;
expect('c2', 'NOT_APPLICABLE cannot waive a defect when the named ICON GLYPH itself fails 3:1',
  !!waivedBad && waivedBad.result === RESULT.FAIL && /identifying feature itself fails/.test(waivedBad.adjudicationError || ''),
  waivedBad ? 'icon ' + (waivedBad.substituteRatio || 0).toFixed(2) + ':1 -> ' + waivedBad.result : 'row not produced by the probe');

const unsubstantiated = badBorder ? evaluateNonTextRow({ ...badBorder,
  adjudication: { status: 'NOT_APPLICABLE', reason: 'seeded: hand-waved waiver with no measurement' } }) : null;
expect('c3', 'an unsubstantiated NOT_APPLICABLE is ADJUDICATION_INVALID, never PASS',
  !!unsubstantiated && unsubstantiated.result === RESULT.ADJUDICATION_INVALID,
  unsubstantiated ? unsubstantiated.result + ' :: ' + unsubstantiated.adjudicationError : 'row not produced by the probe');

const unadjudicated = badBorder ? evaluateNonTextRow({ ...badBorder, adjudication: null }) : null;
expect('c4', 'a non-text row with NO adjudication is ADJUDICATION_INVALID, never PASS',
  !!unadjudicated && unadjudicated.result === RESULT.ADJUDICATION_INVALID,
  unadjudicated ? unadjudicated.result : 'row not produced by the probe');

const waivedGood = goodBorder ? evaluateNonTextRow({ ...goodBorder, adjudication: {
  status: 'NOT_APPLICABLE', reason: 'positive control: the legible icon identifies the control',
  identifiedBy: { feature: goodBorder.identifying.feature, selector: goodBorder.identifying.selector },
  substitute: { fg: goodBorder.identifying.fg, bg: goodBorder.identifying.bg, ratio: goodBorder.identifying.ratio }
} }) : null;
expect('c5', 'positive control: a substantiated NOT_APPLICABLE is recorded as NOT_APPLICABLE (not PASS, not FAIL)',
  !!waivedGood && waivedGood.result === RESULT.NOT_APPLICABLE,
  waivedGood ? 'icon ' + (waivedGood.substituteRatio || 0).toFixed(2) + ':1 -> ' + waivedGood.result : 'row not produced by the probe');

/* ---------------- (b) low-contrast FOCUS INDICATOR ---------------- */
async function focusOf(id) {
  await page.evaluate(() => { document.activeElement && document.activeElement.blur(); });
  let f = null;
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press('Tab');
    const cur = await page.evaluate(FOCUS_PROBE);
    if (cur && cur.selector === '#' + id) { f = cur; break; }
  }
  return f;
}
const badFocus = await focusOf('seeded-bad-focus');
const goodFocus = await focusOf('seeded-good-focus');
const badFocusEval = badFocus ? evaluateFocusRow(badFocus) : null;
const goodFocusEval = goodFocus ? evaluateFocusRow(goodFocus) : null;
expect('b1', 'seeded low-contrast FOCUS INDICATOR is detected as FAIL',
  !!badFocusEval && badFocusEval.result === RESULT.FAIL,
  badFocusEval ? badFocusEval.actual + ' -> ' + badFocusEval.result + ' :: ' + badFocusEval.problems.join('; ') : 'focus row not produced');
expect('b2', 'positive control: legible FOCUS INDICATOR is PASS',
  !!goodFocusEval && goodFocusEval.result === RESULT.PASS,
  goodFocusEval ? goodFocusEval.actual + ' -> ' + goodFocusEval.result : 'focus row not produced');
const thinFocus = evaluateFocusRow({ selector: '#synthetic-thin', hasIndicator: true, thicknessPx: 1,
  ratioOuter: 12, ratioInner: 12 });
expect('b3', 'a focus indicator thinner than 2px is FAIL even at high contrast',
  thinFocus.result === RESULT.FAIL, thinFocus.actual + ' -> ' + thinFocus.result);
const noFocus = evaluateFocusRow({ selector: '#synthetic-none', hasIndicator: false, thicknessPx: 0 });
expect('b4', 'a control with no visible focus indicator is FAIL',
  noFocus.result === RESULT.FAIL, noFocus.result + ' :: ' + noFocus.problems.join('; '));

await ctx.close();
await browser.close();

/* ---------------- (d) stale provenance must be INVALID ---------------- */
const stale = {
  commit: '5bbd608486a4377035ccd43b900b9c181c55ba89',      /* the hard-coded hash QA rejected */
  runtimeHeadCommit: HEAD,
  commitSource: 'hard-coded literal',
  packagePathRelativeToRepo: '/sessions/cool-bold-clarke/qa_w2p1_5bbd608_wt/docs/design/tutoring/option_c2_reference_v1',
  workingTreeClean: true,
  node: process.version,
  os: { platform: 'linux' },
  browser: { version: 'x', executablePath: '/x' }
};
const staleCheck = validateProvenance(stale);
expect('d1', 'stale hard-coded commit metadata fails provenance validation',
  !staleCheck.valid && staleCheck.errors.some(e => /does not equal the runtime/.test(e)),
  staleCheck.errors.join(' | '));
expect('d2', 'an absolute out-of-repository package path fails provenance validation',
  !staleCheck.valid && staleCheck.errors.some(e => /absolute, not repository-relative/.test(e)),
  staleCheck.errors.filter(e => /absolute/.test(e)).join(' | ') || 'no absolute-path error raised');
expect('d3', 'a commit that was not derived at runtime fails provenance validation',
  staleCheck.errors.some(e => /not derived at runtime/.test(e)),
  staleCheck.errors.filter(e => /runtime/.test(e)).join(' | '));
const dirty = { commit: HEAD, runtimeHeadCommit: HEAD, commitSource: 'git rev-parse HEAD (runtime)',
  packagePathRelativeToRepo: PKG_REL, workingTreeClean: false, node: process.version,
  os: { platform: 'linux' }, browser: { version: 'x', executablePath: '/x' } };
const dirtyCheck = validateProvenance(dirty);
expect('d4', 'evidence measured on a DIRTY worktree fails provenance validation',
  !dirtyCheck.valid && dirtyCheck.errors.some(e => /dirty/.test(e)), dirtyCheck.errors.join(' | '));
const honest = { ...dirty, workingTreeClean: true };
const honestCheck = validateProvenance(honest);
expect('d5', 'positive control: runtime-derived commit + repo-relative package path is VALID',
  honestCheck.valid, honestCheck.errors.join(' | ') || 'valid');

/* ---------------- deterministic colour maths sanity ---------------- */
expect('m1', 'contrastRatio(#000,#fff) === 21', contrastRatio('#000000', '#ffffff') === 21,
  String(contrastRatio('#000000', '#ffffff')));
expect('m2', 'a pair that only reaches 4.5 after rounding is not accepted as PASS',
  evaluateTextRow({ selector: '#x', fg: '#000', bg: '#fff', ratio: 4.4999, fontPx: 14, weight: 400 }).result === RESULT.FAIL,
  '4.4999 -> ' + evaluateTextRow({ selector: '#x', fg: '#000', bg: '#fff', ratio: 4.4999, fontPx: 14, weight: 400 }).result);

/* ------------------------------- report ------------------------------- */
const failed = results.filter(r => r.result === 'FAIL');
const out = {
  schema: 'legalsaathi.option-c2.a11y-oracle-selftest/1',
  generatedAt: new Date().toISOString(),
  commit: HEAD, packagePathRelativeToRepo: PKG_REL,
  browserPlaywrightModuleResolved: PW_PATH === process.env.PLAYWRIGHT_MODULE ? 'from PLAYWRIGHT_MODULE' : 'from <repo>/frontend/node_modules',
  total: results.length, passed: results.length - failed.length, failed: failed.length,
  requiredDetections: {
    'a low-contrast text pair fails': results.find(r => r.id === 'a1').result,
    'a low-contrast focus indicator fails': results.find(r => r.id === 'b1').result,
    'an applicable low-contrast icon/boundary fails': results.find(r => r.id === 'c1').result,
    'stale hard-coded commit/path metadata fails provenance validation': results.find(r => r.id === 'd1').result
  },
  results
};
if (process.env.A11Y_OUT_DIR) {
  writeFileSync(join(process.env.A11Y_OUT_DIR, 'a11y_oracle_selftest.json'), JSON.stringify(out, null, 2) + '\n');
}
for (const r of results) console.log(r.result.padEnd(5), r.id.padEnd(4), r.requirement, '::', r.actual);
console.log('\nself-tests: ' + out.passed + '/' + out.total + ' passed');
process.exit(failed.length ? 1 : 0);
