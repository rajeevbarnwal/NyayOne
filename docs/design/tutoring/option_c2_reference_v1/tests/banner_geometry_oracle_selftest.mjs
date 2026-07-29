/* Executable SELF-TESTS for the Option C2 banner CONTENT-geometry oracle (D-1).

   Independent QA rejected the previous adverse-state evidence because the matrix
   could report 72/72 PASS while its own committed screenshot showed a 315x315
   warning icon and a 0px-wide message column. A gate that cannot fail is not a
   gate, so before this oracle's output is trusted it is proven to FAIL on three
   deliberately SEEDED defects:

     S1  an over-broad `.room .mtile svg` rule   (the original D-1 regression)
     S2  a 300+px warning icon
     S3  a zero-width title/detail column

   Each seed is asserted twice:
     (a) against the pure evaluator  — the right rule ids must go false;
     (b) against the REAL GATE       — tools/measure_live_room_addendum.mjs is
         spawned with --inject-css and its process EXIT CODE must be NON-ZERO.
   A positive control (no seed) must exit ZERO, so "everything fails" cannot pass.

   Run:
     LD_LIBRARY_PATH=<stublib> node tests/banner_geometry_oracle_selftest.mjs
   Environment:
     PLAYWRIGHT_MODULE  path to playwright's index.mjs
                        (default: <repo-root>/frontend/node_modules/playwright/index.mjs)
     BANNER_SELFTEST_OUT_DIR  optional directory to also write the result JSON into
*/
import { existsSync, mkdtempSync, writeFileSync, readFileSync, rmSync, mkdirSync } from 'node:fs';
import { join, dirname, relative, sep, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import {
  BANNER_PROBE, evaluateBannerGeometry, assertBannerStateCoverage, RULE_IDS
} from '../tools/banner_geometry_oracle.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = join(HERE, '..');
const REPO_ROOT = execFileSync('git', ['-C', PKG, 'rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
const HEAD = execFileSync('git', ['-C', PKG, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const PKG_REL = relative(REPO_ROOT, PKG).split(sep).join('/');

const PW_PATH = [process.env.PLAYWRIGHT_MODULE, join(REPO_ROOT, 'frontend/node_modules/playwright/index.mjs')]
  .find(p => p && existsSync(p));
if (!PW_PATH) {
  console.error('TYPED ERROR: PLAYWRIGHT_NOT_RESOLVABLE — set PLAYWRIGHT_MODULE or install playwright under <repo>/frontend');
  process.exit(2);
}
const { chromium } = await import(pathToFileURL(PW_PATH).href);
const BASE = pathToFileURL(join(PKG, 'reference', 'index.html')).href;

const results = [];
const expect = (id, requirement, ok, detail) =>
  results.push({ id, requirement, ok: !!ok, actual: detail, result: ok ? 'PASS' : 'FAIL' });

/* ------------------------------------------------------------------ *
 * The three seeded defects.
 * ------------------------------------------------------------------ */
const SEEDS = [
  { key: 'S1_overbroad_mtile_svg',
    why: 'over-broad `.room .mtile svg` descendant rule (the original D-1 regression)',
    css: '.room .mtile svg{width:100%;height:100%;display:block;object-fit:cover}',
    mustFail: ['g1_iconBox', 'g2_textRendered', 'g3_textColumnWidth'] },
  { key: 'S2_oversized_warning_icon',
    why: 'a 300+px warning icon',
    css: '.room .rbanner>svg.ic{width:320px;height:320px;flex:none}',
    mustFail: ['g1_iconBox'] },
  { key: 'S3_zero_width_text_column',
    why: 'a zero-width title/detail column',
    css: '.room .rbanner>div{flex:0 0 0px;width:0;min-width:0;max-width:0;overflow:hidden}',
    mustFail: ['g2_textRendered', 'g3_textColumnWidth'] }
];

const TMP = mkdtempSync(join(tmpdir(), 'c2-banner-selftest-'));
const seedFile = (s) => { const p = join(TMP, s.key + '.css'); writeFileSync(p, s.css + '\n'); return p; };

/* ------------------------------------------------------------------ *
 * Part A — pure evaluator against a real seeded render.
 * ------------------------------------------------------------------ */
const browser = await chromium.launch({ headless: true });
const STATE = 's35-icefail';

async function probeWith(css) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, colorScheme: 'light' });
  if (css) await ctx.addInitScript((c) => {
    const add = () => { const st = document.createElement('style'); st.textContent = c; document.head.appendChild(st); };
    if (document.head) add(); else document.addEventListener('DOMContentLoaded', add);
  }, css);
  const page = await ctx.newPage();
  await page.goto(BASE + '?state=' + STATE + '&theme=light', { waitUntil: 'load' });
  await page.waitForSelector('[data-live-room-ready="true"]', { timeout: 15000, state: 'attached' });
  const p = await page.evaluate(BANNER_PROBE);
  await ctx.close();
  return p;
}

/* positive control: the shipped reference must PASS all nine rules */
const clean = await probeWith(null);
const cleanEval = evaluateBannerGeometry(clean, { case: 'positive-control' });
expect('A0_positive_control', 'the shipped reference passes all nine content-geometry rules',
  cleanEval.pass, JSON.stringify(cleanEval.measured));
expect('A0_ready_true', 'the positive control really did reach data-live-room-ready="true"',
  clean.readyAttr === 'true', String(clean.readyAttr));

const partA = [];
for (const s of SEEDS) {
  const p = await probeWith(s.css);
  const ev = evaluateBannerGeometry(p, { case: s.key });
  const wentFalse = s.mustFail.filter(id => ev.rules[id] === false);
  const readyStillTrue = p.readyAttr === 'true';
  expect('A_' + s.key, 'seeded ' + s.why + ' -> evaluator FAILS ' + s.mustFail.join(','),
    ev.pass === false && wentFalse.length === s.mustFail.length,
    'pass=' + ev.pass + ' failedRules=' + JSON.stringify(ev.failures));
  /* g9: readiness true must NOT rescue a broken render */
  expect('A_' + s.key + '_g9', 'data-live-room-ready="true" does not make the seeded defect pass',
    readyStillTrue && ev.rules.g9_readinessNotSufficient === false,
    'ready=' + p.readyAttr + ' g9=' + ev.rules.g9_readinessNotSufficient);
  partA.push({ seed: s.key, why: s.why, pass: ev.pass, measured: ev.measured, failures: ev.failures, readyAttr: p.readyAttr });
}

/* fail-closed evaluator contract: no probe / fatal probe is a FAILURE, not a skip */
const nullEval = evaluateBannerGeometry(null, { case: 'null-probe' });
expect('A_failclosed_null', 'a null probe fails all nine rules',
  nullEval.pass === false && RULE_IDS.every(id => nullEval.rules[id] === false), nullEval.fatal);
const missingEval = evaluateBannerGeometry({ fatal: 'BANNER_NOT_FOUND', readyAttr: 'true' }, { case: 'missing-banner' });
expect('A_failclosed_missing', 'a missing banner fails all nine rules even when readiness is true',
  missingEval.pass === false && RULE_IDS.every(id => missingEval.rules[id] === false), missingEval.fatal);
const covGap = assertBannerStateCoverage({ states: [{ id: 's35-icefail' }, { id: 's35-new-provider-error' }] }, ['s35-icefail']);
expect('A_failclosed_coverage', 'a banner state the oracle does not cover is a FAILURE',
  covGap.pass === false && covGap.missing.includes('s35-new-provider-error'), JSON.stringify(covGap.missing));

await browser.close();

/* ------------------------------------------------------------------ *
 * Part B — the REAL GATE must exit NON-ZERO for every seed.
 * ------------------------------------------------------------------ */
const GATE = join(PKG, 'tools', 'measure_live_room_addendum.mjs');
function runGate(cssPath, tag) {
  const out = join(TMP, 'gate_' + tag + '.json');
  const args = [GATE, '--pairs', '0', '--phase', 'states', '--noshots', '--out', out, '--playwright', PW_PATH];
  if (cssPath) args.push('--inject-css', cssPath);
  const r = spawnSync(process.execPath, args, { encoding: 'utf8', env: process.env, cwd: PKG });
  /* Read the gate's own verdict rather than echoing stdout: stdout contains the
     absolute --out path, and no committed artefact may carry a machine path. */
  let pairsPassed = null, pairsFailed = null, r13 = null;
  try {
    const j = JSON.parse(readFileSync(out, 'utf8'));
    pairsPassed = j.pairsPassed; pairsFailed = j.pairsFailed;
    r13 = (j.pairs && j.pairs[0] && j.pairs[0].verdict) ? j.pairs[0].verdict.r13_bannerContent : null;
  } catch { /* a gate that produced no parsable output is still a failure, by exit code */ }
  return { code: r.status, out, pairsPassed, pairsFailed, r13_bannerContent: r13,
           summary: 'pairsPassed=' + pairsPassed + ' pairsFailed=' + pairsFailed + ' r13=' + r13 };
}

const control = runGate(null, 'control');
expect('B0_gate_positive_control', 'the unseeded gate exits ZERO', control.code === 0, 'exit=' + control.code + ' :: ' + control.summary);

const partB = [];
for (const s of SEEDS) {
  const g = runGate(seedFile(s), s.key);
  expect('B_' + s.key, 'seeded ' + s.why + ' -> GATE EXITS NON-ZERO', g.code !== 0, 'exit=' + g.code + ' :: ' + g.summary);
  partB.push({ seed: s.key, why: s.why, gateExitCode: g.code, nonZero: g.code !== 0,
               gatePairsPassed: g.pairsPassed, gatePairsFailed: g.pairsFailed, gate_r13_bannerContent: g.r13_bannerContent });
}

/* ------------------------------------------------------------------ *
 * Report
 * ------------------------------------------------------------------ */
const failed = results.filter(r => !r.ok);
const report = {
  contract: 'banner content-geometry oracle self-tests (D-1)',
  provenance: { commit: HEAD, packagePath: PKG_REL },
  rules: RULE_IDS,
  seeds: SEEDS.map(s => ({ key: s.key, why: s.why, css: s.css, mustFailRules: s.mustFail })),
  partA_pureEvaluator: partA,
  partB_realGateExitCodes: partB,
  positiveControls: { evaluator: cleanEval.pass, gateExitCode: control.code },
  checks: results,
  total: results.length, passed: results.length - failed.length, failed: failed.length
};
/* The report records the commit it ran against, so — exactly like the
   accessibility oracle — it is written to a caller-supplied evidence directory
   and never back into the package, where it would churn its own checksum. */
const outDir = process.env.BANNER_SELFTEST_OUT_DIR;
if (outDir) { mkdirSync(outDir, { recursive: true }); writeFileSync(join(outDir, 'BANNER_ORACLE_SELFTEST.json'), JSON.stringify(report, null, 2) + '\n'); }

for (const r of results) console.log((r.ok ? 'PASS' : 'FAIL') + '  ' + r.id + '  ' + r.requirement + '  [' + r.actual + ']');
console.log('\nseeded-defect gate exit codes: ' + partB.map(b => b.seed + '=' + b.gateExitCode).join(', ') +
            ' | unseeded control=' + control.code);
console.log(report.passed + '/' + report.total + ' self-test checks PASS');
rmSync(TMP, { recursive: true, force: true });
process.exit(failed.length ? 1 : 0);
