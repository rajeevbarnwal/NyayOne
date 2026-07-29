/* Option C2 reference — real-Chromium geometry measurement + reference captures.
   Usage: LD_LIBRARY_PATH=<stublib> node tools/measure.mjs [--playwright <path>] [--out <file>]
   Produces MEASURED_GEOMETRY_RESULTS.json (real rows, BROWSER_MEASURED) and captures/*.png.
   No fixed sleeps: every navigation awaits window.__C2_READY with a bounded rejecting timeout. */
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const here = dirname(fileURLToPath(import.meta.url));
const PKG = join(here, '..');
const require = createRequire(import.meta.url);
const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const PW = arg('--playwright', '/sessions/cool-bold-clarke/factorder_wt/frontend/node_modules/playwright/index.mjs');
const { chromium } = await import(pathToFileURL(PW).href);

globalThis.C2Fixtures = require(join(PKG, 'reference/fixtures.js'));
const St = require(join(PKG, 'reference/states.js'));
const FIXTURE_CHECKSUM = globalThis.C2Fixtures.CHECKSUM;
console.log('fixture checksum (node):', FIXTURE_CHECKSUM);

const BASE = pathToFileURL(join(PKG, 'reference/index.html')).href;
const READY_TIMEOUT_MS = 15000;

const VIEWPORTS = [
  { name: '390x844',  w: 390,  h: 844,  class: 'mobile-portrait' },
  { name: '430x932',  w: 430,  h: 932,  class: 'mobile-portrait' },
  { name: '844x390',  w: 844,  h: 390,  class: 'mobile-landscape' },
  { name: '932x430',  w: 932,  h: 430,  class: 'mobile-landscape' },
  { name: '768x1024', w: 768,  h: 1024, class: 'tablet-portrait' },
  { name: '1024x768', w: 1024, h: 768,  class: 'tablet-landscape' },
  { name: '1440x900', w: 1440, h: 900,  class: 'desktop' }
];
const THEMES = ['light', 'dark'];

/* ---------------- in-page probe ---------------- */
const PROBE = function (opts) {
  const de = document.documentElement;
  const app = document.getElementById('app');
  const family = de.getAttribute('data-family');
  const cw = de.clientWidth, ch = de.clientHeight;
  const sel = '#app button,#app a[href],#app a[data-href],#app input,#app select,#app textarea,#app summary,#app label.ib,#app [role=button]';
  /* A visually-hidden input (the star radios) is not itself the hit target: its
     labelling ancestor is. Such inputs are excluded only when that ancestor is >=44x44. */
  const hiddenInputDelegates = [];
  const nodes = [...document.querySelectorAll(sel)].filter(e => {
    const r = e.getBoundingClientRect();
    if (getComputedStyle(e).visibility === 'hidden') return false;
    if (e.closest('[inert],[aria-hidden=true]')) return false;   /* modal background is inert */
    if (r.width <= 2 && r.height <= 2) {
      const host = e.closest('label,button,[role=button]');
      const hr = host && host.getBoundingClientRect();
      if (hr && hr.width >= 43.5 && hr.height >= 43.5) {
        hiddenInputDelegates.push({ n: (e.getAttribute('aria-label') || e.name || e.tagName), hostW: +hr.width.toFixed(1), hostH: +hr.height.toFixed(1) });
        return false;
      }
      return true;
    }
    return r.width > 0 && r.height > 0;
  });
  const name = e => (e.getAttribute('data-testid') || e.getAttribute('aria-label') || (e.textContent || '').trim() || e.tagName).slice(0, 30);
  const rects = nodes.map(e => {
    const r = e.getBoundingClientRect();
    return { n: name(e), x: +r.left.toFixed(1), y: +r.top.toFixed(1), w: +r.width.toFixed(1), h: +r.height.toFixed(1), el: e };
  });

  const smallTargets = rects.filter(r => r.w < 43.5 || r.h < 43.5).map(({ n, w, h }) => ({ n, w, h }));

  /* a control inside a horizontal scroller (the S-31 practice-area rail) is reachable
     by scrolling that rail; it is checked against the scroller, not the viewport */
  const inXScroller = e => {
    for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll') return p;
    }
    return null;
  };
  const outsideX = [], railUnreachable = [];
  for (const r of rects) {
    const sc = inXScroller(r.el);
    if (sc) {
      const sr = sc.getBoundingClientRect();
      if (r.x - sr.left + sc.scrollLeft < -0.5 || r.x - sr.left + sc.scrollLeft + r.w > sc.scrollWidth + 0.5)
        railUnreachable.push({ n: r.n });
      continue;
    }
    if (r.x < -0.5 || r.x + r.w > cw + 0.5) outsideX.push({ n: r.n, x: r.x, w: r.w });
  }

  /* pairwise overlap between actionable controls.
     Sticky/fixed layers (dock, dialog, sheet, scrim) are intentionally stacked above
     content: they are excluded here and covered by the dedicated dock/sheet assertions. */
  const layered = e => {
    for (let p = e; p && p !== document.body; p = p.parentElement) {
      const pos = getComputedStyle(p).position;
      if (pos === 'fixed' || pos === 'sticky' || pos === 'absolute') return true;
    }
    return false;
  };
  const overlaps = [];
  for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
    const a = rects[i], b = rects[j];
    if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
    if (layered(a.el) !== layered(b.el)) continue;
    const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
    const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    if (ox > 1 && oy > 1) overlaps.push({ a: a.n, b: b.n, ox: +ox.toFixed(1), oy: +oy.toFixed(1) });
  }

  const row = {
    scrollHeight: de.scrollHeight, clientHeight: ch, scrollWidth: de.scrollWidth, clientWidth: cw,
    verticalScrollPx: Math.max(0, de.scrollHeight - ch),
    horizontalOverflowPx: Math.max(0, de.scrollWidth - cw),
    actionableCount: rects.length,
    railControlsUnreachable: railUnreachable,
    hiddenInputDelegates,
    minTargetPx: rects.length ? +Math.min(...rects.map(r => Math.min(r.w, r.h))).toFixed(1) : null,
    minTargetControl: rects.length ? rects.reduce((m, r) => Math.min(r.w, r.h) < Math.min(m.w, m.h) ? r : m).n : null,
    targetsUnder44: smallTargets,
    controlsOutsideViewportX: outsideX,
    improperOverlaps: overlaps.slice(0, 6),
    fixtureChecksum: window.__C2_FIXTURE_CHECKSUM
  };

  /* room family: strict no-scroll + everything inside the visual viewport */
  if (family === 'room') {
    row.roomNoPageScroll = de.scrollHeight <= ch + 1;
    row.bodyOverflowY = getComputedStyle(document.body).overflowY;
    row.htmlOverflowY = getComputedStyle(de).overflowY;
    const rootEl = document.querySelector('.route.room');
    row.roomRootHeightPx = rootEl ? +rootEl.getBoundingClientRect().height.toFixed(1) : null;
    row.roomRootEqualsViewport = rootEl ? Math.abs(rootEl.getBoundingClientRect().height - ch) <= 1 : null;
    row.controlsOutsideViewportY = rects
      .filter(r => r.y < -0.5 || r.y + r.h > ch + 0.5).map(({ n, y, h }) => ({ n, y, h }));
    const dock = document.querySelector('[data-testid=control-dock]');
    const dr = dock && dock.getBoundingClientRect();
    row.dockVisible = !!dr && dr.bottom <= ch + 0.5 && dr.top >= -0.5;
    row.dockPaddingBottom = dock ? getComputedStyle(dock).paddingBottom : null;
    ['mic', 'cam', 'devices', 'leave', 'session-info', 'self-move', 'self-min'].forEach(k => {
      const e = document.querySelector('[data-testid=' + k + ']');
      const r = e && e.getBoundingClientRect();
      row['ctl_' + k] = r ? { w: +r.width.toFixed(1), h: +r.height.toFixed(1), inViewport: r.bottom <= ch + 0.5 && r.top >= -0.5 && r.left >= -0.5 && r.right <= cw + 0.5 } : null;
    });
    /* sheet must not change page height and focus must be preserved */
    const before = de.scrollHeight;
    const modal = document.querySelector('[data-testid=dialog]');
    if (modal) {
      /* a modal owns focus: the details sheet must be inert, not operable */
      row.modalOpen = true;
      row.modalFocusInside = modal.contains(document.activeElement);
      row.modalBackgroundInert = !!document.querySelector('.lctrl[inert]') || !!document.querySelector('.body[inert]');
      const mr = modal.getBoundingClientRect();
      row.modalWithinViewport = mr.top >= -0.5 && mr.bottom <= ch + 0.5 && mr.left >= -0.5 && mr.right <= cw + 0.5;
    } else if (window.__C2 && window.__C2.openSheet) {
      const sheetEl = document.querySelector('[data-testid=sheet]');
      const prevTransition = sheetEl.style.transition;
      sheetEl.style.transition = 'none';   /* measure the settled position, not a frame mid-transition */
      const invoker = document.querySelector('[data-testid=session-info]');
      invoker.focus();
      window.__C2.openSheet();
      row.sheetOpenScrollHeight = de.scrollHeight;
      row.sheetAddsNoHeight = de.scrollHeight <= before + 1;
      row.focusMovedIntoSheet = document.activeElement === document.querySelector('[data-testid=sheet-close]');
      const sr = document.querySelector('[data-testid=sheet]').getBoundingClientRect();
      row.sheetClipped = sr.top < -0.5 || sr.bottom > ch + 40;
      window.__C2.closeSheet();
      row.focusRestoredOnClose = document.activeElement === invoker;
      row.sheetClosedScrollHeight = de.scrollHeight;
      sheetEl.style.transition = prevTransition;
    }
  } else {
    /* scrolling families: everything must be reachable and no dock may bury the last content */
    row.controlsUnreachable = rects
      .filter(r => (r.y + window.scrollY) < -0.5 || (r.y + window.scrollY + r.h) > de.scrollHeight + 0.5)
      .map(({ n }) => ({ n }));
    const dock = document.querySelector('.dock');
    const tail = document.querySelector('[data-testid=policy-tail]') || (app.querySelector('.body') && app.querySelector('.body').lastElementChild);
    if (dock && tail) {
      const y0 = window.scrollY;
      window.scrollTo(0, de.scrollHeight);
      const d = dock.getBoundingClientRect(), t = tail.getBoundingClientRect();
      row.stickyCoversFinalContent = t.bottom > d.top + 0.5;
      window.scrollTo(0, y0);
    }
  }
  return row;
};

/* ---------------- runner ---------------- */
async function gotoState(page, stateId, { theme, landscape, chromeUi } = {}) {
  const u = new URL(BASE);
  u.searchParams.set('state', stateId);
  if (theme) u.searchParams.set('theme', theme);
  if (landscape) u.searchParams.set('landscape', '1');
  if (chromeUi) u.searchParams.set('chrome', '1');
  await page.goto(u.href, { waitUntil: 'load' });
  return page.evaluate(t => Promise.race([
    window.__C2_READY,
    new Promise((_, rej) => setTimeout(() => rej(new Error('READY_TIMEOUT after ' + t + 'ms')), t))
  ]), READY_TIMEOUT_MS);
}
async function nav(page, stateId, landscape) {
  return page.evaluate(([id, t]) => {
    window.__C2.goto(id);
    return Promise.race([
      window.__C2_READY,
      new Promise((_, rej) => setTimeout(() => rej(new Error('READY_TIMEOUT after ' + t + 'ms')), t))
    ]);
  }, [stateId, READY_TIMEOUT_MS]);
}

let doCaptures = false;
const rows = [];
const captures = [];
const failures = [];
const consoleErrors = [];
mkdirSync(join(PKG, 'captures'), { recursive: true });

const browser = await chromium.launch({ headless: true });

async function pass(label, { viewports, themes, states, reducedMotion, safeArea, zoom, landscapeFlag }) {
  for (const vp of viewports) for (const theme of themes) {
    const ctx = await browser.newContext({
      viewport: { width: vp.w, height: vp.h },
      deviceScaleFactor: 1,
      reducedMotion: reducedMotion ? 'reduce' : 'no-preference',
      colorScheme: theme
    });
    const page = await ctx.newPage();
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push({ pass: label, vp: vp.name, theme, text: m.text() }); });
    page.on('pageerror', e => consoleErrors.push({ pass: label, vp: vp.name, theme, text: 'PAGEERROR ' + e.message }));

    const landscape = landscapeFlag !== undefined ? landscapeFlag : vp.class === 'mobile-landscape';
    let first = true;
    for (const id of states) {
      const st = St.BY_ID[id];
      let ready;
      try {
        ready = first ? await gotoState(page, id, { theme, landscape }) : await nav(page, id, landscape);
        first = false;
      } catch (e) {
        failures.push({ pass: label, state: id, viewport: vp.name, theme, error: e.message });
        rows.push({ pass: label, state: id, screen: st.screen, family: st.layoutFamily, viewport: vp.name, viewportClass: vp.class, theme, status: 'READY_FAILED', error: e.message });
        first = true;
        continue;
      }
      if (ready.fixtureChecksum !== FIXTURE_CHECKSUM) {
        failures.push({ pass: label, state: id, viewport: vp.name, theme, error: 'FIXTURE_CHECKSUM_MISMATCH' });
      }
      if (safeArea) {
        await page.evaluate(([t, b, l, r]) => {
          const s = document.getElementById('__safe') || document.head.appendChild(Object.assign(document.createElement('style'), { id: '__safe' }));
          s.textContent = `:root{--safe-t:${t}px;--safe-b:${b}px;--safe-l:${l}px;--safe-r:${r}px}`;
        }, landscape ? [0, 21, 44, 44] : [47, 34, 0, 0]);
      }
      const m = await page.evaluate(PROBE, {});
      const row = {
        pass: label, state: id, screen: st.screen, family: st.layoutFamily, label: st.label,
        viewport: vp.name, viewportClass: vp.class, theme,
        reducedMotion: !!reducedMotion, safeArea: !!safeArea, zoomPercent: zoom || 100,
        ...m
      };
      row.verdict = verdict(row);
      if (row.verdict !== 'PASS') failures.push({ pass: label, state: id, viewport: vp.name, theme, verdict: row.verdict, why: row.violations });
      rows.push(row);
    }
    await ctx.close();
  }
}

function verdict(r) {
  const v = [];
  if (r.horizontalOverflowPx > 0) v.push('HORIZONTAL_OVERFLOW ' + r.horizontalOverflowPx + 'px');
  if (r.targetsUnder44 && r.targetsUnder44.length) v.push('TARGET_UNDER_44 ' + r.targetsUnder44.map(t => `${t.n}(${t.w}x${t.h})`).join(';'));
  if (r.controlsOutsideViewportX && r.controlsOutsideViewportX.length) v.push('CONTROL_OUTSIDE_VIEWPORT_X ' + r.controlsOutsideViewportX.map(t => t.n).join(';'));
  if (r.railControlsUnreachable && r.railControlsUnreachable.length) v.push('RAIL_CONTROL_UNREACHABLE ' + r.railControlsUnreachable.map(t => t.n).join(';'));
  if (r.improperOverlaps && r.improperOverlaps.length) v.push('IMPROPER_OVERLAP ' + r.improperOverlaps.map(o => o.a + '/' + o.b).join(';'));
  if (r.family === 'room') {
    if (r.roomNoPageScroll === false) v.push('ROOM_PAGE_SCROLL ' + r.verticalScrollPx + 'px');
    if (r.roomRootEqualsViewport === false) v.push('ROOM_ROOT_NOT_100DVH ' + r.roomRootHeightPx + ' vs ' + r.clientHeight);
    if (r.dockVisible === false) v.push('DOCK_NOT_VISIBLE');
    if (r.controlsOutsideViewportY && r.controlsOutsideViewportY.length) v.push('CONTROL_OUTSIDE_VIEWPORT_Y ' + r.controlsOutsideViewportY.map(t => t.n).join(';'));
    if (r.modalOpen) {
      if (r.modalFocusInside === false) v.push('MODAL_FOCUS_NOT_INSIDE');
      if (r.modalBackgroundInert === false) v.push('MODAL_BACKGROUND_NOT_INERT');
      if (r.modalWithinViewport === false) v.push('MODAL_OUTSIDE_VIEWPORT');
    }
    if (r.sheetAddsNoHeight === false) v.push('SHEET_CHANGES_PAGE_HEIGHT');
    if (r.sheetClipped === true) v.push('SHEET_CLIPPED');
    if (r.focusMovedIntoSheet === false) v.push('FOCUS_NOT_MOVED_INTO_SHEET');
    if (r.focusRestoredOnClose === false) v.push('FOCUS_NOT_RESTORED');
    ['mic', 'cam', 'devices', 'leave'].forEach(k => {
      const c = r['ctl_' + k];
      if (!c) v.push('MISSING_CONTROL_' + k.toUpperCase());
      else if (!c.inViewport) v.push('CONTROL_NOT_IN_VIEWPORT_' + k.toUpperCase());
      else if (c.w < 43.5 || c.h < 43.5) v.push('CONTROL_UNDER_44_' + k.toUpperCase());
    });
  } else if (r.stickyCoversFinalContent === true) v.push('DOCK_COVERS_FINAL_CONTENT');
  r.violations = v;
  return v.length ? 'FAIL' : 'PASS';
}

const ALL = St.IDS;
const ZOOM_VPS = [{ name: '195x422', w: 195, h: 422, class: 'mobile-portrait-200pct' },
                  { name: '720x450', w: 720, h: 450, class: 'desktop-200pct' }];
const UNITS = [];
for (const vp of VIEWPORTS) for (const theme of THEMES) UNITS.push({ pass: 'main', vp, theme, opts: {} });
for (const vp of VIEWPORTS.slice(0, 4)) UNITS.push({ pass: 'reduced-motion', vp, theme: 'light', opts: { reducedMotion: true } });
for (const vp of ZOOM_VPS) UNITS.push({ pass: 'zoom-200', vp, theme: 'light', opts: { zoom: 200 } });
for (const vp of VIEWPORTS.slice(0, 4)) UNITS.push({ pass: 'safe-area', vp, theme: 'light', opts: { safeArea: true } });
UNITS.push({ pass: 'captures', vp: null, theme: null, opts: {} });

const unitArg = arg('--units', 'all');
const outArg = arg('--out', null);
if (unitArg === 'list') { UNITS.forEach((u, i) => console.log(i, u.pass, u.vp ? u.vp.name : '-', u.theme || '-')); process.exit(0); }
const selected = unitArg === 'all' ? UNITS.map((_, i) => i)
  : unitArg.split(',').flatMap(t => t.includes('-') ? (([a, b]) => Array.from({ length: +b - +a + 1 }, (_, k) => +a + k))(t.split('-')) : [+t]);

for (const i of selected) {
  const u = UNITS[i];
  if (u.pass === 'captures') { doCaptures = true; continue; }
  console.log('unit', i, u.pass, u.vp.name, u.theme);
  await pass(u.pass, { viewports: [u.vp], themes: [u.theme], states: ALL, ...u.opts });
}

/* ---------------- captures ---------------- */
const CAPTURES = doCaptures ? [
  ...St.FAMILIES.map(f => ({ state: St.STATES.find(s => s.layoutFamily === f).id, vp: VIEWPORTS[0], why: 'layout family ' + f })),
  { state: 's32-availability', vp: VIEWPORTS[0], why: 'S-32 controlled adaptation — availability' },
  { state: 's33-hold-urgent', vp: VIEWPORTS[0], why: 'non-colour hold urgency' },
  { state: 's35-room-live', vp: VIEWPORTS[0], why: 'repaired live room — 390x844 boundary' },
  { state: 's35-room-live', vp: VIEWPORTS[1], why: 'repaired live room — 430x932 boundary' },
  { state: 's35-room-live', vp: VIEWPORTS[2], why: 'repaired live room — 844x390 landscape boundary' },
  { state: 's35-room-live', vp: VIEWPORTS[3], why: 'repaired live room — 932x430 landscape boundary' },
  { state: 's35-reconnecting', vp: VIEWPORTS[0], why: 'room typed network state' },
  { state: 's35-leave-confirm', vp: VIEWPORTS[0], why: 'room exit dialog' },
  { state: 's35-room-live', vp: { name: '195x422', w: 195, h: 422, class: 'mobile-portrait-200pct' }, why: 'live room at 200% zoom' },
  { state: 's35-perm-cam', vp: VIEWPORTS[0], why: 'permission refusal' },
  { state: 's35-review-open', vp: VIEWPORTS[0], why: 'review form' },
  { state: 's34-confirmed', vp: VIEWPORTS[6], why: 'desktop 1440 confirmation' },
  { state: 's31-default', vp: VIEWPORTS[4], why: 'tablet 768 marketplace' }
] : [];
for (const cap of CAPTURES) for (const theme of THEMES) {
  const ctx = await browser.newContext({ viewport: { width: cap.vp.w, height: cap.vp.h }, deviceScaleFactor: 1, colorScheme: theme });
  const page = await ctx.newPage();
  const ready = await gotoState(page, cap.state, { theme, landscape: cap.vp.class.startsWith('mobile-landscape') });
  if (ready.fixtureChecksum !== FIXTURE_CHECKSUM) throw new Error('FIXTURE_CHECKSUM_MISMATCH before capture ' + cap.state);
  if (cap.state === 's35-room-live' && theme === 'dark') {
    await page.evaluate(() => window.__C2.openSheet());
  }
  const file = `${cap.state}__${cap.vp.name}__${theme}.png`;
  await page.screenshot({ path: join(PKG, 'captures', file), fullPage: false });
  captures.push({ file, state: cap.state, viewport: cap.vp.name, theme, why: cap.why, fixtureChecksum: ready.fixtureChecksum });
  await ctx.close();
}
await browser.close();

/* ---------------- output ---------------- */
const byVerdict = rows.reduce((a, r) => (a[r.verdict || r.status] = (a[r.verdict || r.status] || 0) + 1, a), {});
const roomRows = rows.filter(r => r.family === 'room');
const out = {
  schema: 'legalsaathi.tutoring.measured-geometry/1',
  provenance: 'BROWSER_MEASURED',
  package: 'docs/design/tutoring/option_c2_reference_v1',
  supersedes: 'sources/MOBILE_GEOMETRY_RESULTS_HISTORICAL_pending.json (status pending_measured_run; left untouched in its own historical package)',
  generatedAtUtc: new Date().toISOString().slice(0, 10),
  fixtureChecksum: FIXTURE_CHECKSUM,
  budgets: {
    horizontalOverflowPx: 0, minTargetPx: 44,
    roomVerticalScrollPx: 0, roomRootEqualsViewport: true,
    dockAlwaysVisible: true, sheetAddsNoPageHeight: true,
    focusRestoredOnSheetClose: true, consoleErrors: 0
  },
  passes: [...new Set(rows.map(r => r.pass))],
  viewports: VIEWPORTS.map(v => v.name),
  themes: THEMES,
  totals: { rows: rows.length, ...byVerdict, consoleErrors: consoleErrors.length, readyFailures: failures.filter(f => f.error).length },
  roomTotals: { rows: roomRows.length, pass: roomRows.filter(r => r.verdict === 'PASS').length, fail: roomRows.filter(r => r.verdict !== 'PASS').length },
  consoleErrors, failures, captures,
  rows
};
writeFileSync(outArg || join(PKG, 'MEASURED_GEOMETRY_RESULTS.json'), JSON.stringify(out, null, 1) + '\n');
console.log('\nrows:', rows.length, byVerdict, 'consoleErrors:', consoleErrors.length);
console.log('room rows:', out.roomTotals);
console.log('captures:', captures.length);
if (failures.length) { console.log('FAILURES (first 12):'); failures.slice(0, 12).forEach(f => console.log(' ', JSON.stringify(f).slice(0, 240))); }
