/**
 * Responsive accessibility/visual QA baseline (SAATHI-347).
 *
 * Runs against a running preview server (default http://localhost:1130) across
 * 390/430/768/1024/1440 and checks, per the canonical S-01..S-99 routes:
 *   - route renders (no crash, has content)
 *   - no horizontal overflow
 *   - actionable targets >= 44x44
 *   - no console errors
 *   - theme persistence (ls-theme survives reload)
 *   - mobile bottom-nav renders its labels (no dropped item)
 *
 * Usage (local / CI):
 *   npm run build && npm run preview &   # serve on 1130
 *   BASE_URL=http://localhost:1130 QA_ROUTES=all npm run qa
 *
 * Env: BASE_URL (default http://localhost:1130), QA_ROUTES ("all" or a number, default 12 sampled).
 */
import { chromium } from 'playwright';

const BASE = process.env.BASE_URL || 'http://localhost:1130';
const WIDTHS = [390, 430, 768, 1024, 1440];
const ALL = Array.from({ length: 99 }, (_, i) => `S-${String(i + 1).padStart(2, '0')}`);
const routeArg = process.env.QA_ROUTES || '12';
const screens = routeArg === 'all' ? ALL : ALL.filter((_, i) => i % Math.ceil(99 / Number(routeArg)) === 0);

let failures = 0;
const fail = (m) => { failures++; console.error('FAIL:', m); };

const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const consoleErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

for (const width of WIDTHS) {
  await page.setViewportSize({ width, height: 900 });
  for (const sid of screens) {
    consoleErrors.length = 0;
    await page.goto(`${BASE}/${sid.toLowerCase()}`, { waitUntil: 'networkidle' });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (overflow) fail(`${sid} @${width}px horizontal overflow`);
    const bodyLen = await page.evaluate(() => document.body.innerText.length);
    if (bodyLen < 1) fail(`${sid} @${width}px rendered empty`);
    const smallTargets = await page.evaluate(() => {
      const sel = 'a, button, [role="button"], input, select';
      return [...document.querySelectorAll(sel)]
        .filter((e) => e.offsetParent !== null)
        .map((e) => { const r = e.getBoundingClientRect(); return Math.min(r.width, r.height); })
        .filter((v) => v > 0 && v < 44).length;
    });
    if (smallTargets > 0) fail(`${sid} @${width}px has ${smallTargets} sub-44px targets`);
    if (width <= 768) {
      const navCount = await page.evaluate(() => document.querySelectorAll('.ls-bnav__item').length);
      if (navCount !== 5) fail(`${sid} @${width}px mobile nav has ${navCount} items (expected 5)`);
    }
    if (consoleErrors.length) fail(`${sid} @${width}px console errors: ${consoleErrors.join(' | ')}`);
  }
}

// Theme persistence
await page.setViewportSize({ width: 1440, height: 900 });
await page.goto(`${BASE}/s-13`, { waitUntil: 'networkidle' });
await page.evaluate(() => { window.localStorage.setItem('ls-theme', 'dark'); });
await page.reload({ waitUntil: 'networkidle' });
const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
if (theme !== 'dark') fail(`theme persistence: expected dark after reload, got ${theme}`);

await browser.close();
console.log(`QA complete: ${screens.length} screens x ${WIDTHS.length} widths. Failures: ${failures}`);
process.exit(failures ? 1 : 0);
