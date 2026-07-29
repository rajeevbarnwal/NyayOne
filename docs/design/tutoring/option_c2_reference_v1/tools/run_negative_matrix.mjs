/* Executes the negative matrix in real Chromium and writes NEGATIVE_TEST_RESULTS.json/.md.
   Every row carries input, expected, actual, status and the evidence file. */
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
const PKG = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const { chromium } = await import(pathToFileURL(arg('--playwright', '/sessions/cool-bold-clarke/factorder_wt/frontend/node_modules/playwright/index.mjs')).href);
globalThis.C2Fixtures = require(join(PKG, 'reference/fixtures.js'));
const CHECKSUM = globalThis.C2Fixtures.CHECKSUM;
const BASE = pathToFileURL(join(PKG, 'reference/index.html')).href;
const EVIDENCE = 'MEASURED_GEOMETRY_RESULTS.json';

const browser = await chromium.launch({ headless: true });
const meta = await (async () => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const p = await ctx.newPage();
  await p.goto(BASE + '?state=s31-default', { waitUntil: 'load' });
  await p.evaluate(() => window.__C2_READY);
  const m = await p.evaluate(() => window.C2Negative.CASES.map(c => ({ id: c.id, area: c.area, input: c.input, expected: c.expected, kind: c.kind, state: c.state || null, zoom: c.zoom || null, reducedMotion: !!c.reducedMotion })));
  await ctx.close(); return m;
})();

const results = [];
for (const c of meta) {
  const vp = c.zoom === 2 ? { width: 195, height: 422 } : { width: 390, height: 844 };
  const ctx = await browser.newContext({ viewport: vp, reducedMotion: c.reducedMotion ? 'reduce' : 'no-preference' });
  const page = await ctx.newPage();
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => errs.push('PAGEERROR ' + e.message));
  const state = c.state || 's31-default';
  await page.goto(`${BASE}?state=${state}`, { waitUntil: 'load' });
  let row;
  try {
    const ready = await page.evaluate(t => Promise.race([window.__C2_READY,
      new Promise((_, r) => setTimeout(() => r(new Error('READY_TIMEOUT')), t))]), 15000);
    if (ready.fixtureChecksum !== CHECKSUM) throw new Error('FIXTURE_CHECKSUM_MISMATCH');
    const out = await page.evaluate(id => {
      const c = window.C2Negative.CASES.find(x => x.id === id);
      try { const r = c.run(); return { actual: String(r.actual), pass: !!r.pass }; }
      catch (e) { return { actual: 'THREW ' + e.message, pass: false }; }
    }, c.id);
    row = { ...c, viewport: `${vp.width}x${vp.height}`, actual: out.actual, status: out.pass ? 'PASS' : 'FAIL', consoleErrors: errs.length, evidence: EVIDENCE, fixtureChecksum: CHECKSUM };
  } catch (e) {
    row = { ...c, viewport: `${vp.width}x${vp.height}`, actual: 'NOT_EXECUTED: ' + e.message, status: 'BLOCKED', consoleErrors: errs.length, evidence: EVIDENCE, fixtureChecksum: CHECKSUM };
  }
  if (row.status === 'PASS' && errs.length) { row.status = 'FAIL'; row.actual += ' | console errors: ' + errs.join(' ~ '); }
  results.push(row);
  await ctx.close();
}
await browser.close();

const counts = results.reduce((a, r) => (a[r.status] = (a[r.status] || 0) + 1, a), {});
const byArea = {};
for (const r of results) { byArea[r.area] = byArea[r.area] || { total: 0, pass: 0, fail: 0, blocked: 0 };
  byArea[r.area].total++; byArea[r.area][r.status.toLowerCase()]++; }

writeFileSync(join(PKG, 'NEGATIVE_TEST_RESULTS.json'), JSON.stringify({
  schema: 'legalsaathi.tutoring.negative-matrix/1', provenance: 'BROWSER_MEASURED',
  package: 'docs/design/tutoring/option_c2_reference_v1',
  harness: 'reference/negative_matrix.js executed in headless Chromium via tools/run_negative_matrix.mjs',
  fixtureChecksum: CHECKSUM, totals: { cases: results.length, ...counts }, byArea, results
}, null, 1) + '\n');

const md = ['# Negative test results — Option C2 reference v1', '',
  `**Provenance:** BROWSER_MEASURED (headless Chromium, ${new Date().toISOString().slice(0, 10)})`,
  `**Fixture checksum:** \`${CHECKSUM}\``,
  `**Totals:** ${results.length} cases — ` + Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(', '), '',
  '| Area | Total | Pass | Fail | Blocked |', '|---|---:|---:|---:|---:|',
  ...Object.entries(byArea).map(([a, v]) => `| ${a} | ${v.total} | ${v.pass || 0} | ${v.fail || 0} | ${v.blocked || 0} |`),
  '', '## Case detail', '',
  '| ID | Area | Input | Expected | Actual | Status | Evidence |', '|---|---|---|---|---|---|---|',
  ...results.map(r => `| ${r.id} | ${r.area} | ${r.input.replace(/\|/g, '\\|')} | ${r.expected.replace(/\|/g, '\\|')} | ${String(r.actual).replace(/\|/g, '\\|').slice(0, 160)} | ${r.status} | ${r.evidence} |`), ''].join('\n');
writeFileSync(join(PKG, 'NEGATIVE_TEST_RESULTS.md'), md);
console.log('negative matrix:', results.length, counts);
results.filter(r => r.status !== 'PASS').forEach(r => console.log('  ', r.status, r.id, '|', String(r.actual).slice(0, 120)));
