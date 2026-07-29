/* PORTABILITY test — the package must run from a directory that is not the
   checkout it was authored in.

   Independent QA found absolute session-scratch defaults hard-coded in five
   tools (the scanner below is what now forbids them). A tool
   with a machine path is not reproducible: on any other machine it either fails
   opaquely or, worse, silently measures the wrong tree. This test proves:

     1. no executable under tools/ or tests/ contains an absolute machine path,
        with ONE deliberate exception: tests/a11y_oracle_selftest.mjs, whose
        stale literals are NEGATIVE FIXTURES that the accessibility oracle must
        reject. They are asserted to still be present, so nobody "cleans" them
        away and quietly deletes that test's teeth;
     2. a byte-for-byte COPY of the package, placed in a foreign directory
        outside the original checkout, still resolves its own paths and runs the
        banner content-geometry gate to a ZERO exit code;
     3. the copy resolves paths structurally even when it is NOT a git checkout;
     4. every de-pathed tool fails FAST with a TYPED error instead of guessing.

   Run:
     LD_LIBRARY_PATH=<stublib> node tests/portability.test.mjs [--workdir <dir>]
   Environment:
     PLAYWRIGHT_MODULE       path to playwright's index.mjs
     PORTABILITY_WORKDIR     where to place the foreign copy (default: a fresh mkdtemp)
*/
import { existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, writeFileSync, rmSync, cpSync, statSync } from 'node:fs';
import { join, dirname, relative, sep, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(HERE, '..');
const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };

const results = [];
const expect = (id, requirement, ok, detail) =>
  results.push({ id, requirement, ok: !!ok, actual: String(detail), result: ok ? 'PASS' : 'FAIL' });

/* The negative fixtures that must NOT be cleaned up. */
const NEGATIVE_FIXTURE = 'tests/a11y_oracle_selftest.mjs';
/* An absolute POSIX or Windows path literal inside a string. */
const ABS_PATH = /(['"`])(\/(?:sessions|Users|home|var|opt|mnt)\/[^'"`\n]+|[A-Za-z]:\\[^'"`\n]+)\1/g;

/* ---------------- 1. no machine paths in executables ---------------- */
const execFiles = [];
for (const d of ['tools', 'tests']) {
  for (const f of readdirSync(join(PKG, d))) {
    if (f.endsWith('.mjs') || f.endsWith('.js')) execFiles.push(d + '/' + f);
  }
}
const offenders = [];
for (const rel of execFiles) {
  if (rel === NEGATIVE_FIXTURE) continue;
  const src = readFileSync(join(PKG, rel), 'utf8');
  const hits = [...src.matchAll(ABS_PATH)].map(m => m[0]);
  if (hits.length) offenders.push(rel + ' -> ' + hits.join(', '));
}
expect('P1_no_machine_paths', 'no executable under tools/ or tests/ hard-codes an absolute machine path',
  offenders.length === 0, offenders.join(' | ') || 'none in ' + execFiles.length + ' files');

/* the intentional negative fixtures must survive */
const negSrc = readFileSync(join(PKG, NEGATIVE_FIXTURE), 'utf8');
const negHits = [...negSrc.matchAll(ABS_PATH)].map(m => m[0]);
expect('P1b_negative_fixtures_intact',
  NEGATIVE_FIXTURE + ' keeps its intentional stale path/commit literals as negative fixtures',
  negHits.length > 0, negHits.length + ' stale literal(s) retained');

/* ---------------- 2. run a copy from a foreign directory ---------------- */
const WORK = arg('--workdir', process.env.PORTABILITY_WORKDIR || mkdtempSync(join(tmpdir(), 'c2-portcheck-')));
mkdirSync(WORK, { recursive: true });
/* Mirror the repository shape a de-pathed tool is allowed to rely on:
   <foreign>/docs/design/tutoring/option_c2_reference_v1 — but with NO .git, so
   `git rev-parse` cannot answer and the structural fallback must carry it. */
const FOREIGN_PKG = join(WORK, 'docs', 'design', 'tutoring', 'option_c2_reference_v1');
rmSync(FOREIGN_PKG, { recursive: true, force: true });
mkdirSync(dirname(FOREIGN_PKG), { recursive: true });
cpSync(PKG, FOREIGN_PKG, { recursive: true });
expect('P2_copy_made', 'a byte-for-byte copy of the package exists outside the original checkout',
  existsSync(join(FOREIGN_PKG, 'reference', 'index.html')) && !FOREIGN_PKG.startsWith(PKG),
  'copied to a foreign directory (' + readdirSync(FOREIGN_PKG).length + ' entries)');
expect('P2b_copy_is_not_a_git_checkout', 'the foreign copy is NOT a git checkout, so git-based resolution cannot rescue it',
  !existsSync(join(WORK, '.git')) && !existsSync(join(FOREIGN_PKG, '.git')), 'no .git in the foreign tree');

/* playwright must come from the caller, exactly as on a foreign machine */
const PW = process.env.PLAYWRIGHT_MODULE || arg('--playwright', '');
expect('P2c_playwright_supplied', 'playwright is supplied by the caller, not by a baked-in default',
  !!PW && existsSync(PW), PW ? 'supplied' : 'MISSING — set PLAYWRIGHT_MODULE');

const gateOut = join(WORK, 'portability_gate.json');
let gate = { status: null };
if (PW && existsSync(PW)) {
  gate = spawnSync(process.execPath, [
    join(FOREIGN_PKG, 'tools', 'measure_live_room_addendum.mjs'),
    '--pairs', '0', '--phase', 'states', '--noshots', '--out', gateOut, '--playwright', PW
  ], { encoding: 'utf8', env: process.env, cwd: WORK });
}
let gateJson = null;
try { gateJson = JSON.parse(readFileSync(gateOut, 'utf8')); } catch { /* reported by exit code */ }
expect('P3_foreign_gate_zero_exit',
  'the banner content-geometry gate runs from the foreign copy and exits ZERO',
  gate.status === 0, 'exit=' + gate.status + (gate.stderr ? ' stderr=' + gate.stderr.trim().split('\n').slice(-1)[0] : ''));
expect('P3b_foreign_gate_measured_the_copy',
  'the foreign run measured the FOREIGN reference directory, not the original checkout',
  !!gateJson && typeof gateJson.referenceDir === 'string' &&
  resolve(gateJson.referenceDir).startsWith(resolve(FOREIGN_PKG)) &&
  !resolve(gateJson.referenceDir).startsWith(resolve(PKG)),
  gateJson ? relative(WORK, gateJson.referenceDir) : 'no gate output');
expect('P3c_foreign_gate_banner_oracle_ran',
  'rule 13 executed in the foreign copy over every discovered banner state',
  !!gateJson && gateJson.bannerOracle && gateJson.bannerOracle.casesTotal > 0 &&
  gateJson.bannerOracle.casesTotal === gateJson.bannerOracle.casesPassed,
  gateJson && gateJson.bannerOracle ? gateJson.bannerOracle.casesPassed + '/' + gateJson.bannerOracle.casesTotal + ' banner cases' : 'n/a');

/* ---------------- 3. typed fail-fast, never a silent guess ---------------- */
const typedCases = [
  { id: 'P4_merge_requires_dir', tool: 'tools/merge_measurements.mjs', args: [],
    env: { C2_PARTIALS_DIR: '' }, code: 'PARTIALS_DIR_REQUIRED',
    requirement: 'merge_measurements fails fast with a typed error when no partials directory is given' },
  { id: 'P4b_merge_rejects_bad_dir', tool: 'tools/merge_measurements.mjs',
    args: [join(WORK, 'no-such-partials')], env: {}, code: 'PARTIALS_DIR_REQUIRED',
    requirement: 'merge_measurements rejects a non-existent partials directory with the same typed code' },
  { id: 'P4c_playwright_typed_error', tool: 'tools/measure.mjs', args: ['--playwright', join(WORK, 'no-such-playwright.mjs')],
    env: { PLAYWRIGHT_MODULE: '' }, code: 'PLAYWRIGHT_NOT_RESOLVABLE',
    requirement: 'a missing playwright raises a typed PLAYWRIGHT_NOT_RESOLVABLE error, not a module-resolution stack trace' },
  { id: 'P4d_historical_typed_error', tool: 'tools/measure_before.mjs',
    args: ['--historical', join(WORK, 'no-such-gate.html'), '--playwright', PW || 'x'],
    env: { C2_HISTORICAL_GATE: '' }, code: 'HISTORICAL_GATE_NOT_FOUND',
    requirement: 'a missing historical gate raises a typed HISTORICAL_GATE_NOT_FOUND error' }
];
for (const c of typedCases) {
  const env = { ...process.env };
  for (const k of Object.keys(c.env)) { if (c.env[k] === '') delete env[k]; else env[k] = c.env[k]; }
  const r = spawnSync(process.execPath, [join(FOREIGN_PKG, c.tool), ...c.args], { encoding: 'utf8', env, cwd: WORK });
  const out = ((r.stderr || '') + (r.stdout || ''));
  expect(c.id, c.requirement, r.status === 2 && out.includes(c.code),
    'exit=' + r.status + ' :: ' + (out.trim().split('\n')[0] || '').slice(0, 120));
}

/* ---------------- report ---------------- */
const failed = results.filter(r => !r.ok);
const report = {
  contract: 'package portability — runs from a foreign path with no machine defaults',
  packagePath: relative(resolve(PKG, '..', '..', '..', '..'), PKG).split(sep).join('/'),
  executablesScanned: execFiles.length,
  intentionalNegativeFixture: NEGATIVE_FIXTURE,
  intentionalStaleLiteralsRetained: negHits.length,
  foreignRun: { insideOriginalCheckout: false, gateExitCode: gate.status,
                bannerCases: gateJson && gateJson.bannerOracle ? gateJson.bannerOracle.casesTotal : null },
  checks: results, total: results.length, passed: results.length - failed.length, failed: failed.length
};
/* Written to a caller-supplied evidence directory only: the package must not
   contain an artefact that this very test would then have to scan. */
const outDir = process.env.PORTABILITY_OUT_DIR;
if (outDir) { mkdirSync(outDir, { recursive: true }); writeFileSync(join(outDir, 'PORTABILITY_TEST.json'), JSON.stringify(report, null, 2) + '\n'); }
for (const r of results) console.log((r.ok ? 'PASS' : 'FAIL') + '  ' + r.id + '  ' + r.requirement + '  [' + r.actual + ']');
console.log(report.passed + '/' + report.total + ' portability checks PASS');
if (!arg('--keep', '') && !process.env.PORTABILITY_WORKDIR) rmSync(WORK, { recursive: true, force: true });
process.exit(failed.length ? 1 : 0);
