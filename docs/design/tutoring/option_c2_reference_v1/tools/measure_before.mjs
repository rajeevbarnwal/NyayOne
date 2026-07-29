/* Reproduces, in real Chromium, the live-room defect reported by the independent
   Product/UX review against the HISTORICAL approved package (read-only).
   Writes BEFORE_AFTER_LIVE_ROOM.json alongside the repaired measurements. */
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const PKG = join(dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const PW = arg('--playwright', '/sessions/cool-bold-clarke/factorder_wt/frontend/node_modules/playwright/index.mjs');
const HIST = arg('--historical', '/sessions/cool-bold-clarke/mnt/LegalSaathi/docs/design/tutoring_option_c2_mobile_gate_2026-07-29/C2_MOBILE_GATE.html');
const { chromium } = await import(pathToFileURL(PW).href);

const VPS = [[390, 844], [430, 932], [844, 390], [932, 430]];
const b = await chromium.launch({ headless: true });
const before = [];
for (const [w, h] of VPS) {
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  const p = await ctx.newPage();
  await p.goto(pathToFileURL(HIST).href, { waitUntil: 'load' });
  await p.waitForFunction(() => window.__c2m && typeof window.__c2m.measure === 'function', { timeout: 30000 });
  await p.evaluate(() => document.fonts.ready);
  const r = await p.evaluate(() => { window.__c2m.setBoth(true); return window.__c2m.measure(); });
  const want = `${w}x${h}`;
  for (const s of r.screens) {
    if (s.viewport !== want) continue;
    if (s.screen !== 's35live' && s.screen !== 's35land') continue;
    const small = await p.evaluate((scr) => {
      window.__c2m.setBoth(false); window.__c2m.go(scr);
      const vp = document.querySelector('.vp');
      return [...vp.querySelectorAll('button,a,input,summary')]
        .map(e => { const r = e.getBoundingClientRect(); return { n: (e.getAttribute('aria-label') || e.textContent || e.tagName).trim().slice(0, 30), w: +r.width.toFixed(1), h: +r.height.toFixed(1) }; })
        .filter(x => x.w > 0 && x.h > 0 && (x.w < 43.5 || x.h < 43.5));
    }, s.screen);
    before.push({
      source: 'HISTORICAL tutoring_option_c2_mobile_gate_2026-07-29/C2_MOBILE_GATE.html (read-only)',
      screen: s.screen, viewport: s.viewport, browserWindow: want,
      scrollHeight: s.scrollHeight, clientHeight: s.clientHeight,
      verticalScrollPx: s.verticalScrollPx, horizontalOverflowPx: s.horizontalOverflowPx,
      minTargetPx: s.minTargetPx, minTargetControl: s.minTargetControl,
      targetsUnder44: small
    });
  }
  await ctx.close();
}
await b.close();
writeFileSync(join(PKG, 'BEFORE_AFTER_LIVE_ROOM.json'), JSON.stringify({
  schema: 'legalsaathi.tutoring.live-room-before-after/1',
  provenance: 'BROWSER_MEASURED',
  independentReviewClaim: {
    source: 'sources/OPTION_C2_MOBILE_GATE_INDEPENDENT_PRODUCT_UX_REVIEW.md',
    rows: [
      { screen: 'S-35 live portrait', viewport: '390x844', scrollBeyondViewportPx: 309, minTargetPx: 40, result: 'FAIL' },
      { screen: 'S-35 live portrait', viewport: '430x932', scrollBeyondViewportPx: 309, minTargetPx: 40, result: 'FAIL' },
      { screen: 'S-35 live landscape', viewport: '844x390', scrollBeyondViewportPx: 621, minTargetPx: 40, result: 'FAIL' },
      { screen: 'S-35 live landscape', viewport: '932x430', scrollBeyondViewportPx: 581, minTargetPx: 40, result: 'FAIL' }
    ]
  },
  reproducedBefore: before,
  rootCause: [
    'The details sheet is position:absolute and its containing block is .app (position:relative), NOT .live.',
    '.live{overflow:hidden} therefore never clips it, so the sheet translated by translateY(100%) adds exactly its own height to the document scroll height (308px portrait, 290-330px landscape).',
    '.live also used height:100vh inside a nested device-bezel scroll container, where vh refers to the outer visual viewport rather than the bezel.',
    'The session-info control was min 40x40 and the self-view Move/Minimise controls were 30x30, all below the 44px floor.'
  ],
  repair: [
    'The reference renders every state as a full-page route at the real browser viewport: no device-bezel nesting, so 100dvh is meaningful.',
    '.route.room is exactly 100dvh with grid-template-columns:minmax(0,1fr) and grid-template-rows:auto minmax(0,1fr) auto.',
    'html[data-family=room] and body[data-family=room] set overflow:hidden and overscroll-behavior:none.',
    'The details sheet is position:fixed, so it can never contribute to document height (asserted: sheetAddsNoHeight).',
    'Every room control including session-info, self-view Move and Minimise is >=44x44.',
    'Landscape compacts the header and self-view; the control dock is never removed. At <=360px the dock wraps rather than dropping controls.'
  ]
}, null, 1) + '\n');
console.log('before rows:', before.length);
before.forEach(r => console.log(` ${r.screen} ${r.viewport}: scroll=${r.verticalScrollPx}px minTarget=${r.minTargetPx}px (${r.targetsUnder44.length} controls <44)`));
