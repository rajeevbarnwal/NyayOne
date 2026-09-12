// Reference-only measurement. This does not activate an application parity gate.
import http from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { PNG } from 'pngjs';
import { SOURCE_SHA256, VIEWS, VIEWPORTS, coverage, comparePixels, validateCalibration } from './lib/nyay66-conformance.mjs';
import { inspectSurface } from './lib/nyay66-dom.mjs';

const require = createRequire(import.meta.url);
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const out = resolve(process.env.NYAY66_OUTPUT || resolve(root, 'frontend/artifacts/nyay66-calibration'));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const source = await readFile(resolve(root, 'docs/design/nyayone-option-3.2.1/NYAYONE_OPTION3_2_1_REVL_SOURCE.html'));
if (sha(source) !== SOURCE_SHA256) throw Error('REFERENCE_HASH_MISMATCH');
// Exclusive output directory prevents accidental historical artifact overwrite.
await mkdir(dirname(out), { recursive: true });
await mkdir(out);
const head = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
const server = http.createServer((req, res) => {
  if (req.url !== '/') { res.writeHead(404).end(); return; }
  res.setHeader('Content-Type', 'text/html'); res.end(source);
});
await new Promise(resolveListen => server.listen(0, '127.0.0.1', resolveListen));
const origin = `http://127.0.0.1:${server.address().port}`;
const report = {
  purpose: 'REFERENCE_CALIBRATION_ONLY', sourceSha256: SOURCE_SHA256, head,
  generatedUTC: new Date().toISOString(), platform: `${process.platform}-${process.arch}`,
  node: process.version, playwright: require('playwright/package.json').version,
  viewportDPR: 1, locale: 'en-IN', timezone: 'Asia/Kolkata', theme: 'light',
  applicationParityMeasured: false, numericToleranceApproved: false,
  coverage: coverage(), darkCoverage: coverage('dark'), rows: [],
};
let browser;
try {
  browser = await chromium.launch(); report.chromium = browser.version();
  for (const vp of VIEWPORTS) for (const view of VIEWS) {
    const hashes = [], samples = [];
    let blockedRequests = 0, runtimeErrors = 0, fonts, surface;
    for (let sample = 0; sample < 3; sample++) {
      // Independent contexts expose initialization variance, not only repeat screenshots.
      const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1, locale: 'en-IN', timezoneId: 'Asia/Kolkata', colorScheme: 'light', reducedMotion: 'reduce', serviceWorkers: 'block' });
      try {
        const page = await context.newPage();
        page.on('pageerror', () => runtimeErrors++);
        page.on('console', msg => { if (msg.type() === 'error') runtimeErrors++; });
        await page.route('**/*', route => {
          const url = route.request().url();
          if (url === `${origin}/` || url.startsWith('blob:') || url.startsWith('data:')) return route.continue();
          blockedRequests++; return route.abort();
        });
        await page.goto(origin);
        await page.waitForFunction(() => !!window.__ny);
        const registry = await page.evaluate(() => window.__ny.screens);
        if (JSON.stringify([...registry].sort()) !== JSON.stringify([...VIEWS].sort())) throw Error('REFERENCE_REGISTRY_DRIFT');
        await page.evaluate(({ view, preset }) => { window.__ny.bare(true); window.__ny.setViewportPreset(preset); window.__ny.go(view); }, { view, preset: vp.id });
        fonts = await page.evaluate(async () => {
          await document.fonts.ready;
          await Promise.all([...document.images].map(img => img.decode()));
          await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
          return [...document.fonts].map(font => ({ family: font.family, status: font.status, style: font.style, weight: font.weight }));
        });
        const bytes = await page.locator('.vp').screenshot({ animations: 'disabled' });
        if (sample === 0) surface = await page.evaluate(inspectSurface, { reference: true, clocks: ['s05', 's09'].includes(view) });
        hashes.push(sha(bytes)); samples.push(PNG.sync.read(bytes));
        await writeFile(resolve(out, `${view}-${vp.id}-${sample}.png`), bytes);
      } finally { await context.close(); }
    }
    const row = { view, viewport: vp.id, executed: true, sampleHashes: hashes,
      dimensions: [samples[0].width, samples[0].height], fonts, surface, blockedRequests, runtimeErrors,
      deltas: samples.slice(1).map(actual => comparePixels(samples[0], actual)) };
    report.rows.push(row);
    console.log(JSON.stringify({ view, viewport: vp.id, deltas: row.deltas }));
  }
  report.validationErrors = validateCalibration(report);
  await writeFile(resolve(out, 'calibration.json'), JSON.stringify(report, null, 2) + '\n');
  const manifest = report.rows.flatMap(row => row.sampleHashes.map((hash, index) => `${hash}  ${row.view}-${row.viewport}-${index}.png`));
  manifest.push(`${sha(await readFile(resolve(out, 'calibration.json')))}  calibration.json`);
  await writeFile(resolve(out, 'SHA256SUMS'), manifest.join('\n') + '\n');
  if (report.validationErrors.length) throw Error(report.validationErrors.join(','));
} finally {
  if (browser) await browser.close();
  await new Promise(done => server.close(done));
}
