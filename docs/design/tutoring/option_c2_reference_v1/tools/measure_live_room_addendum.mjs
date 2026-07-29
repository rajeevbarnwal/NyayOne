/* S-35 live-room geometry closure addendum — executable acceptance matrix.
   Contract: QA/wave2_priority1_design_reference_closure_2026-07-29/S35_LIVE_ROOM_GEOMETRY_CLOSURE_ADDENDUM.md
   Usage:
     LD_LIBRARY_PATH=<stublib> node tools/measure_live_room_addendum.mjs \
       [--ref <reference-dir>] [--label before|after] [--out <json>] [--shots <dir>] [--playwright <path>]

   12 pairs = 6 viewports x 2 themes. Every pair asserts addendum rules 1-13.
   Rule 11 re-runs rules 1-6 for six named states.
   Rule 12: readiness is awaited on [data-live-room-ready="true"] with a bounded
   REJECTING timeout. There is no fixed sleep anywhere in this file.
   Rule 13 [D-1]: the FAIL-CLOSED banner CONTENT-geometry oracle
   (tools/banner_geometry_oracle.mjs) runs its nine rules against EVERY
   provider-error / reconnect banner state the state model declares, at all 12
   pairs. Container geometry alone (rules 1-6) let a 315x315 warning icon and a
   0px message column pass; rule 13 exists so that can never happen again. */
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  BANNER_PROBE, BANNER_STATE_DISCOVERY, evaluateBannerGeometry, assertBannerStateCoverage,
  RULE_IDS as BANNER_RULE_IDS, RULE_TEXT as BANNER_RULE_TEXT
} from './banner_geometry_oracle.mjs';
import { resolvePlaywright, failFast } from './env_paths.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const PKG = join(here, '..');
const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };

const REF   = resolve(arg('--ref', join(PKG, 'reference')));
const LABEL = arg('--label', 'after');
const OUT   = resolve(arg('--out', join(PKG, 'LIVE_ROOM_ADDENDUM_RESULTS.json')));
const SHOTS = resolve(arg('--shots', join(PKG, 'captures', 'addendum')));
const PW    = failFast(() => resolvePlaywright(arg('--playwright', '')));
const ONLY  = arg('--pairs', '');            /* comma-separated pair indices 0-11 */
const PHASE = arg('--phase', 'all');         /* core | states | all */
const NOSHOTS = argv.includes('--noshots');
/* --inject-css is a TEST-ONLY hook: tests/banner_geometry_oracle_selftest.mjs
   seeds deliberate layout defects with it and asserts this gate exits NON-ZERO.
   It is never used by a normal evidence run; when unset nothing is injected. */
const INJECT_CSS_PATH = arg('--inject-css', '');
const INJECT_CSS = INJECT_CSS_PATH ? readFileSync(resolve(INJECT_CSS_PATH), 'utf8') : '';
const READY_TIMEOUT_MS = 15000;
const TOL = 1;            /* +-1 px, per the addendum */
const TARGET_TOL = 43.5;  /* 44 px with sub-pixel border rounding */

const { chromium } = await import(pathToFileURL(PW).href);
const BASE = pathToFileURL(join(REF, 'index.html')).href;

const VIEWPORTS = [
  { name: '390x844',  w: 390,  h: 844,  o: 'portrait'  },
  { name: '430x932',  w: 430,  h: 932,  o: 'portrait'  },
  { name: '768x1024', w: 768,  h: 1024, o: 'portrait'  },
  { name: '844x390',  w: 844,  h: 390,  o: 'landscape' },
  { name: '932x430',  w: 932,  h: 430,  o: 'landscape' },
  { name: '1024x768', w: 1024, h: 768,  o: 'landscape' }
];
const THEMES = ['light', 'dark'];

/* addendum rule 11 — six named states that must preserve the same geometry */
const STATE_CASES = [
  { key: 'camera-denied',      state: 's35-room-camoff',   note: 'camera denied / off, device released wording' },
  { key: 'mic-denied',         state: 's35-room-muted',    note: 'microphone denied / muted' },
  { key: 'disconnected',       state: 's35-reconnecting',  note: 'disconnected / reconnecting' },
  { key: 'provider-failure',   state: 's35-icefail',       note: 'ICE/TURN provider failure' },
  { key: 'leave-confirmation', state: 's35-leave-confirm', note: 'leave confirmation dialog' },
  { key: 'device-release',     state: 's35-room-live', drive: 'cam', note: 'camera toggled off in-room, device released' }
];

/* ============================ in-page probe ============================ */
const PROBE = function () {
  const de = document.documentElement;
  const q = (s, r) => (r || document).querySelector(s);
  const R = (el) => { if (!el) return null; const r = el.getBoundingClientRect();
    return { x: +r.x.toFixed(2), y: +r.y.toFixed(2), w: +r.width.toFixed(2), h: +r.height.toFixed(2),
             top: +r.top.toFixed(2), left: +r.left.toFixed(2), right: +r.right.toFixed(2), bottom: +r.bottom.toFixed(2) }; };
  const name = (el) => (el.getAttribute('aria-label') || (el.textContent || '').trim().replace(/\s+/g, ' ') ||
                        el.getAttribute('title') || el.getAttribute('data-testid') || el.id || el.tagName).slice(0, 60);
  const tid = (el) => el.getAttribute('data-testid') || el.id || el.className || el.tagName;

  const vw = window.innerWidth, vh = window.innerHeight;

  const liveRoot = q('.route.room') || q('.live');
  const liveHost = q('.live-host');
  const deviceVp = q('.vp[data-screen]');
  const stage    = liveRoot && q('.stage', liveRoot);
  const header   = liveRoot && q('.lh', liveRoot);
  const dock     = liveRoot && q('.lctrl', liveRoot);
  const selfView = q('[data-testid=self-view]');
  const mentor   = q('[data-testid=remote-tile]');
  const sheet    = q('[data-testid=sheet]');

  if (!liveRoot) return { fatal: 'LIVE_ROOT_NOT_FOUND' };

  const containers = [
    { n: 'page (documentElement)', el: de },
    { n: 'body',                   el: document.body },
    { n: 'app container (#app)',   el: document.getElementById('app') },
    { n: 'device/reference viewport (.vp)', el: deviceVp },
    { n: 'live host (.live-host)', el: liveHost },
    { n: 'live root (.live/.room)', el: liveRoot },
    { n: 'stage (.stage)',         el: stage }
  ].filter(c => c.el);

  const scroll = containers.map(c => ({
    container: c.n,
    scrollHeight: c.el.scrollHeight, clientHeight: c.el.clientHeight,
    scrollWidth: c.el.scrollWidth,   clientWidth: c.el.clientWidth,
    overflowY: Math.max(0, c.el.scrollHeight - c.el.clientHeight),
    overflowX: Math.max(0, c.el.scrollWidth - c.el.clientWidth),
    ok: (c.el.scrollHeight <= c.el.clientHeight + 1) && (c.el.scrollWidth <= c.el.clientWidth + 1)
  }));

  const SEL = 'button,a[href],a[data-href],input,select,textarea,summary,[role=button]';
  const interactive = [...document.querySelectorAll(SEL)].filter(e => {
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    if (e.closest('[inert],[aria-hidden=true]')) return false;
    if (e.closest('#reviewer')) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });
  const targets = interactive.map(e => {
    const r = e.getBoundingClientRect();
    return { name: name(e), testid: tid(e), w: +r.width.toFixed(1), h: +r.height.toFixed(1),
             min: +Math.min(r.width, r.height).toFixed(1), rect: R(e),
             inViewport: r.left >= -1 && r.top >= -1 && r.right <= vw + 1 && r.bottom <= vh + 1 };
  });
  const smallest = targets.slice().sort((a, b) => a.min - b.min)[0] || null;
  const undersizedTargets = targets.filter(t => t.w < 43.5 || t.h < 43.5);

  const cs = getComputedStyle(liveRoot);
  const gridRows = (cs.gridTemplateRows || '').trim();
  const rowTracks = gridRows && gridRows !== 'none' ? gridRows.split(/\s+/).length : 0;
  const rowRects = { header: R(header), stage: R(stage), dock: R(dock) };
  const threeRowsByRect = !!(header && stage && dock) &&
    Math.abs(header.getBoundingClientRect().bottom - stage.getBoundingClientRect().top) <= 1 &&
    Math.abs(stage.getBoundingClientRect().bottom - dock.getBoundingClientRect().top) <= 1;

  const rs = getComputedStyle(de);
  const px = (v) => { const n = parseFloat(v); return isFinite(n) ? n : 0; };
  const safe = { t: px(rs.getPropertyValue('--safe-t')), b: px(rs.getPropertyValue('--safe-b')),
                 l: px(rs.getPropertyValue('--safe-l')), r: px(rs.getPropertyValue('--safe-r')) };

  const inter = (a, b) => {
    const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return (x > 1 && y > 1) ? { x: +x.toFixed(1), y: +y.toFixed(1) } : null;
  };
  const ctlSel = ['[data-testid=mic]', '[data-testid=cam]', '[data-testid=devices]', '[data-testid=leave]',
                  '[data-testid=session-info]', '[data-testid=self-move]', '[data-testid=self-min]'];
  const ctls = ctlSel.map(s => { const el = q(s); return el ? { n: s.replace(/\[data-testid=|\]/g, ''), el, r: R(el) } : null; }).filter(Boolean);
  const overlaps = [];
  for (let i = 0; i < ctls.length; i++) for (let j = i + 1; j < ctls.length; j++) {
    const o = inter(ctls[i].r, ctls[j].r);
    if (o) overlaps.push({ kind: 'control-vs-control', a: ctls[i].n, b: ctls[j].n, overlap: o });
  }
  const safeBands = [];
  if (safe.t > 0) safeBands.push({ n: 'safe-area-top',    r: { left: 0, top: 0, right: vw, bottom: safe.t } });
  if (safe.b > 0) safeBands.push({ n: 'safe-area-bottom', r: { left: 0, top: vh - safe.b, right: vw, bottom: vh } });
  if (safe.l > 0) safeBands.push({ n: 'safe-area-left',   r: { left: 0, top: 0, right: safe.l, bottom: vh } });
  if (safe.r > 0) safeBands.push({ n: 'safe-area-right',  r: { left: vw - safe.r, top: 0, right: vw, bottom: vh } });
  ctls.forEach(c => safeBands.forEach(s => { const o = inter(c.r, s.r); if (o) overlaps.push({ kind: 'control-vs-safe-area', a: c.n, b: s.n, overlap: o }); }));

  if (selfView) {
    const sr = R(selfView);
    ctls.filter(c => !selfView.contains(c.el)).forEach(c => {
      const o = inter(c.r, sr);
      if (o) overlaps.push({ kind: 'control-vs-self-view', a: c.n, b: 'self-view', overlap: o });
    });
    [['dock', dock], ['header', header]].forEach(function (pairEl) {
      const n = pairEl[0], el = pairEl[1];
      if (!el) return; const o = inter(sr, R(el));
      if (o) overlaps.push({ kind: 'self-view-vs-chrome', a: 'self-view', b: n, overlap: o });
    });
    if (stage) {
      const st = R(stage);
      if (sr.left < st.left - 1 || sr.top < st.top - 1 || sr.right > st.right + 1 || sr.bottom > st.bottom + 1)
        overlaps.push({ kind: 'self-view-escapes-stage', a: 'self-view', b: 'stage', overlap: { self: sr, stage: st } });
    }
  }
  const badge = mentor && q('.nm', mentor);
  if (badge) ctls.forEach(c => { const o = inter(c.r, R(badge)); if (o) overlaps.push({ kind: 'control-vs-mentor-badge', a: c.n, b: 'mentor-name-badge', overlap: o }); });

  const required = [['mic', '[data-testid=mic]'], ['camera', '[data-testid=cam]'],
                    ['device-settings', '[data-testid=devices]'], ['leave', '[data-testid=leave]']];
  const requiredCtl = required.map(function (p) {
    const n = p[0], s = p[1];
    const el = q(s); if (!el) return { name: n, present: false };
    const r = el.getBoundingClientRect();
    return { name: n, present: true, rect: R(el),
             fullyVisible: r.left >= -1 && r.top >= -1 && r.right <= vw + 1 && r.bottom <= vh + 1,
             w: +r.width.toFixed(1), h: +r.height.toFixed(1), meetsTarget: r.width >= 43.5 && r.height >= 43.5 };
  });

  return {
    viewport: { w: vw, h: vh },
    readyAttr: liveRoot.getAttribute('data-live-room-ready') || de.getAttribute('data-live-room-ready') || null,
    rects: {
      liveHost: R(liveHost), liveRoot: R(liveRoot), deviceVp: R(deviceVp), stage: R(stage),
      header: R(header), dock: R(dock), selfView: R(selfView), mentorTile: R(mentor), sheet: R(sheet)
    },
    rootHeight: +liveRoot.getBoundingClientRect().height.toFixed(2),
    rootHeightDelta: +(liveRoot.getBoundingClientRect().height - vh).toFixed(2),
    scroll, maxOverflowY: Math.max.apply(null, scroll.map(s => s.overflowY)),
    maxOverflowX: Math.max.apply(null, scroll.map(s => s.overflowX)),
    gridRows, rowTracks, rowRects, threeRowsByRect,
    targets, smallest, undersizedTargets, requiredCtl, safe, overlaps
  };
};

/* ============================ helpers ============================ */
async function waitReady(page) {
  const t0 = Date.now();
  /* Does this build expose the explicit signal at all? Short capability probe only. */
  const supported = await page.waitForSelector('[data-live-room-ready]', { timeout: 1500, state: 'attached' })
    .then(() => true).catch(() => false);
  if (supported) {
    /* Bounded REJECTING wait — a timeout here fails the pair, it is never swallowed. */
    await page.waitForSelector('[data-live-room-ready="true"]', { timeout: READY_TIMEOUT_MS, state: 'attached' });
    return { signal: 'data-live-room-ready', ms: Date.now() - t0 };
  }
  await page.evaluate(async (ms) => {
    let to; const guard = new Promise((_, rej) => { to = setTimeout(() => rej(new Error('READY_TIMEOUT')), ms); });
    try { await Promise.race([window.__C2_READY, guard]); } finally { clearTimeout(to); }
  }, READY_TIMEOUT_MS);
  return { signal: 'window.__C2_READY (legacy fallback)', ms: Date.now() - t0 };
}

const nav = (state, theme) => BASE + '?state=' + state + '&theme=' + theme;

function verdictFor(p) {
  return {
    r1_rootHeight: Math.abs(p.rootHeightDelta) <= TOL,
    r2_noScroll: p.scroll.every(s => s.ok),
    r3_threeRows: p.rowTracks === 3 && p.threeRowsByRect,
    r4_dockVisible: p.requiredCtl.every(c => c.present && c.fullyVisible && c.meetsTarget),
    r5_targets: p.undersizedTargets.length === 0,
    r6_noOverlap: p.overlaps.length === 0
  };
}

/* ============================ run ============================ */
mkdirSync(SHOTS, { recursive: true });
/* Evidence must never embed an absolute, machine-specific path: record every
   capture relative to the package root (or, if the caller redirected --shots
   outside the package, relative to the repository root). */
const shotRef = (abs) => {
  const relPkg = relative(PKG, abs).split(sep).join('/');
  return relPkg.startsWith('..') ? relative(join(PKG, '..', '..', '..', '..'), abs).split(sep).join('/') : relPkg;
};
const browser = await chromium.launch({ headless: true });
const pairs = [];
const failures = [];

const ALL_UNITS = [];
for (const vp of VIEWPORTS) for (const theme of THEMES) ALL_UNITS.push({ vp, theme });
const wanted = ONLY ? ONLY.split(',').map(Number) : ALL_UNITS.map((_, i) => i);

for (const idx of wanted) {
  const vp = ALL_UNITS[idx].vp, theme = ALL_UNITS[idx].theme;
  const pairName = vp.name + '__' + theme;
  const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: 1, colorScheme: theme });
  if (INJECT_CSS) await ctx.addInitScript((css) => {
    const add = () => { const st = document.createElement('style'); st.id = '__seeded_defect__'; st.textContent = css; document.head.appendChild(st); };
    if (document.head) add(); else document.addEventListener('DOMContentLoaded', add);
  }, INJECT_CSS);
  const page = await ctx.newPage();
  const con = { errors: [], warnings: [], pageErrors: [], failedRequests: [] };
  page.on('console', m => { const t = m.type(); if (t === 'error') con.errors.push(m.text()); else if (t === 'warning') con.warnings.push(m.text()); });
  page.on('pageerror', e => con.pageErrors.push(String((e && e.message) || e)));
  page.on('requestfailed', r => con.failedRequests.push(r.url() + ' :: ' + (r.failure() && r.failure().errorText)));

  const pair = { pair: pairName, index: idx, viewport: vp.name, orientation: vp.o, theme, label: LABEL, phase: PHASE };
  try {
    await page.goto(nav('s35-room-live', theme), { waitUntil: 'load' });
    pair.ready = await waitReady(page);

    const base = await page.evaluate(PROBE);
    if (base.fatal) throw new Error(base.fatal);
    pair.base = base;
    pair.verdict = verdictFor(base);
   if (PHASE !== 'states') {

    /* rule 7 — self-view corners + minimised restore */
    const corners = [];
    for (let i = 0; i < 4; i++) {
      await page.click('[data-testid=self-move]');
      corners.push(await page.evaluate(() => {
        const s = document.querySelector('[data-testid=self-view]');
        const st = document.querySelector('.stage');
        const r = s.getBoundingClientRect(), sr = st.getBoundingClientRect();
        const ctls = [...s.querySelectorAll('button')].filter(b => {
          const cs = getComputedStyle(b); return cs.display !== 'none' && cs.visibility !== 'hidden';
        }).map(b => { const br = b.getBoundingClientRect();
          return { n: b.getAttribute('data-testid') || b.id, w: +br.width.toFixed(1), h: +br.height.toFixed(1),
                   rect: { left: +br.left.toFixed(1), top: +br.top.toFixed(1), right: +br.right.toFixed(1), bottom: +br.bottom.toFixed(1) } }; });
        let ov = null;
        for (let a = 0; a < ctls.length; a++) for (let b = a + 1; b < ctls.length; b++) {
          const A = ctls[a].rect, B = ctls[b].rect;
          const x = Math.min(A.right, B.right) - Math.max(A.left, B.left);
          const y = Math.min(A.bottom, B.bottom) - Math.max(A.top, B.top);
          if (x > 1 && y > 1) ov = { a: ctls[a].n, b: ctls[b].n, x: +x.toFixed(1), y: +y.toFixed(1) };
        }
        return { pos: s.getAttribute('data-pos') || 'br',
                 rect: { left: +r.left.toFixed(1), top: +r.top.toFixed(1), right: +r.right.toFixed(1), bottom: +r.bottom.toFixed(1), w: +r.width.toFixed(1), h: +r.height.toFixed(1) },
                 insideStage: r.left >= sr.left - 1 && r.top >= sr.top - 1 && r.right <= sr.right + 1 && r.bottom <= sr.bottom + 1,
                 controls: ctls, controlOverlap: ov };
      }));
    }
    const distinctCorners = new Set(corners.map(c => c.pos)).size;
    await page.click('[data-testid=self-min]');
    const minimised = await page.evaluate(() => {
      const s = document.querySelector('[data-testid=self-view]');
      const vis = [...s.querySelectorAll('button,[role=button]')].filter(b => {
        const cs = getComputedStyle(b); if (cs.display === 'none' || cs.visibility === 'hidden') return false;
        const r = b.getBoundingClientRect(); return r.width > 0 && r.height > 0;
      });
      const r = s.getBoundingClientRect();
      return { selfRect: { w: +r.width.toFixed(1), h: +r.height.toFixed(1) },
               visibleControls: vis.map(b => { const br = b.getBoundingClientRect();
                 return { n: b.getAttribute('data-testid') || b.id, label: b.getAttribute('aria-label'), w: +br.width.toFixed(1), h: +br.height.toFixed(1) }; }) };
    });
    await page.click('[data-testid=self-min]');
    pair.rule7 = { corners, distinctCorners, allInsideStage: corners.every(c => c.insideStage),
      noControlOverlap: corners.every(c => !c.controlOverlap),
      allControlsMeetTarget: corners.every(c => c.controls.every(x => x.w >= TARGET_TOL && x.h >= TARGET_TOL)),
      minimised,
      exactlyOneRestore: minimised.visibleControls.length === 1 &&
                         minimised.visibleControls[0].w >= TARGET_TOL && minimised.visibleControls[0].h >= TARGET_TOL };
    pair.verdict.r7_selfView = pair.rule7.distinctCorners === 4 && pair.rule7.allInsideStage &&
      pair.rule7.noControlOverlap && pair.rule7.allControlsMeetTarget && pair.rule7.exactlyOneRestore;

    /* rule 8 — details sheet */
    const beforeSheet = await page.evaluate(() => {
      const de = document.documentElement, lr = document.querySelector('.route.room') || document.querySelector('.live');
      return { pageSH: de.scrollHeight, pageSW: de.scrollWidth, rootSH: lr.scrollHeight, rootSW: lr.scrollWidth };
    });
    await page.focus('[data-testid=session-info]');
    await page.click('[data-testid=session-info]');
    /* deterministic settle: wait for the OPEN state, not a fixed sleep. Bounded + rejecting. */
    await page.waitForFunction(() => {
      const sh = document.querySelector('[data-testid=sheet]');
      if (!sh || sh.getAttribute('data-open') !== '1') return false;
      const r = sh.getBoundingClientRect();
      if (r.height <= 0) return false;
      const lr = document.querySelector('.route.room') || document.querySelector('.live');
      const lrr = lr.getBoundingClientRect();
      /* the sheet has finished opening only when it is actually inside the live root */
      return r.bottom <= lrr.bottom + 1 && r.top >= lrr.top - 1;
    }, null, { timeout: 5000, polling: 'raf' });
    const sheetOpen = await page.evaluate(() => {
      const de = document.documentElement, lr = document.querySelector('.route.room') || document.querySelector('.live');
      const sh = document.querySelector('[data-testid=sheet]');
      const r = sh.getBoundingClientRect(), lrr = lr.getBoundingClientRect();
      const f = [...sh.querySelectorAll('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')];
      return { pageSH: de.scrollHeight, pageSW: de.scrollWidth, rootSH: lr.scrollHeight, rootSW: lr.scrollWidth,
               sheetRect: { left: +r.left.toFixed(1), top: +r.top.toFixed(1), right: +r.right.toFixed(1), bottom: +r.bottom.toFixed(1) },
               rootRect: { left: +lrr.left.toFixed(1), top: +lrr.top.toFixed(1), right: +lrr.right.toFixed(1), bottom: +lrr.bottom.toFixed(1) },
               insideRoot: r.left >= lrr.left - 1 && r.top >= lrr.top - 1 && r.right <= lrr.right + 1 && r.bottom <= lrr.bottom + 1,
               focusInside: sh.contains(document.activeElement),
               focusedName: document.activeElement && (document.activeElement.getAttribute('data-testid') || document.activeElement.id),
               focusableCount: f.length };
    });
    const trapProbe = [];
    for (let i = 0; i < sheetOpen.focusableCount + 2; i++) {
      await page.keyboard.press('Tab');
      trapProbe.push(await page.evaluate(() => {
        const sh = document.querySelector('[data-testid=sheet]');
        return { inside: sh.contains(document.activeElement),
                 el: document.activeElement && (document.activeElement.getAttribute('data-testid') || document.activeElement.id || document.activeElement.tagName) };
      }));
    }
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => {
      const sh = document.querySelector('[data-testid=sheet]');
      return sh && sh.getAttribute('data-open') === '0';
    }, null, { timeout: 5000, polling: 'raf' });
    const afterSheet = await page.evaluate(() => {
      const de = document.documentElement, lr = document.querySelector('.route.room') || document.querySelector('.live');
      const sh = document.querySelector('[data-testid=sheet]');
      return { pageSH: de.scrollHeight, pageSW: de.scrollWidth, rootSH: lr.scrollHeight, rootSW: lr.scrollWidth,
               open: sh.getAttribute('data-open') === '1',
               focusBackOnTrigger: document.activeElement === document.querySelector('[data-testid=session-info]'),
               focused: document.activeElement && (document.activeElement.getAttribute('data-testid') || document.activeElement.id) };
    });
    pair.rule8 = { beforeSheet, sheetOpen, trapProbe, afterSheet,
      noScrollGrowth: sheetOpen.pageSH <= beforeSheet.pageSH + 1 && sheetOpen.pageSW <= beforeSheet.pageSW + 1 &&
                      sheetOpen.rootSH <= beforeSheet.rootSH + 1 && sheetOpen.rootSW <= beforeSheet.rootSW + 1,
      trapped: trapProbe.every(t => t.inside) };
    pair.verdict.r8_sheet = sheetOpen.insideRoot && pair.rule8.noScrollGrowth && sheetOpen.focusInside &&
      pair.rule8.trapped && afterSheet.open === false && afterSheet.focusBackOnTrigger;

    /* rule 9 — keyboard reachability, DOM order, stable accessible names */
    await page.goto(nav('s35-room-live', theme), { waitUntil: 'load' });
    await waitReady(page);
    const expected = await page.evaluate(() => {
      const sel = 'button,a[href],a[data-href],input,select,textarea,summary,[role=button]';
      return [...document.querySelectorAll(sel)]
        .filter(e => { const cs = getComputedStyle(e);
          return cs.display !== 'none' && cs.visibility !== 'hidden' && !e.closest('[inert],[aria-hidden=true],#reviewer'); })
        .map((e, i) => ({ i, n: e.getAttribute('data-testid') || e.id || e.tagName,
                          label: (e.getAttribute('aria-label') || (e.textContent || '').trim()).slice(0, 60) }));
    });
    const tabOrder = [];
    for (let i = 0; i < expected.length + 1; i++) {
      await page.keyboard.press('Tab');
      const cur = await page.evaluate(() => {
        const a = document.activeElement; if (!a || a === document.body) return null;
        return { n: a.getAttribute('data-testid') || a.id || a.tagName,
                 label: (a.getAttribute('aria-label') || (a.textContent || '').trim()).slice(0, 60),
                 hasName: !!(a.getAttribute('aria-label') || (a.textContent || '').trim()) };
      });
      if (!cur) break;
      tabOrder.push(cur);
      if (tabOrder.length >= expected.length) break;
    }
    const reached = tabOrder.map(t => t.n), expNames = expected.map(e => e.n);
    pair.rule9 = { expected: expNames, reached,
      domOrderMatch: JSON.stringify(reached) === JSON.stringify(expNames.slice(0, reached.length)),
      allReached: reached.length >= expNames.length,
      allNamed: tabOrder.every(t => t.hasName), detail: tabOrder };
    pair.verdict.r9_keyboard = pair.rule9.domOrderMatch && pair.rule9.allReached && pair.rule9.allNamed;
   }

    /* capture */
    await page.goto(nav('s35-room-live', theme), { waitUntil: 'load' });
    await waitReady(page);
    const shot = join(SHOTS, LABEL + '__s35-room-live__' + vp.name + '__' + theme + '.png');
    if (!NOSHOTS) await page.screenshot({ path: shot });
    pair.capture = NOSHOTS ? null : shotRef(shot);

    /* rule 11 — six named states re-assert rules 1-6 */
    pair.rule11 = [];
    for (const sc of (PHASE === 'core' ? [] : STATE_CASES)) {
      await page.goto(nav(sc.state, theme), { waitUntil: 'load' });
      await waitReady(page);
      if (sc.drive === 'cam') await page.click('[data-testid=cam]');
      const p = await page.evaluate(PROBE);
      const v = verdictFor(p);
      /* [D-1] provider-failure / reconnect rows must publish ICON SIZE and
         TITLE/DETAIL WIDTHS, not just root height and scroll. */
      const bProbe = await page.evaluate(BANNER_PROBE);
      const bEval = (bProbe && bProbe.fatal === 'BANNER_NOT_FOUND')
        ? null : evaluateBannerGeometry(bProbe, { pair: pairName, state: sc.state, theme, viewport: vp.name });
      const sShot = join(SHOTS, LABEL + '__state-' + sc.key + '__' + vp.name + '__' + theme + '.png');
      if (!NOSHOTS) await page.screenshot({ path: sShot });
      pair.rule11.push({ case: sc.key, state: sc.state, note: sc.note, capture: NOSHOTS ? null : shotRef(sShot),
        rootHeightDelta: p.rootHeightDelta, maxOverflowY: p.maxOverflowY, maxOverflowX: p.maxOverflowX,
        rowTracks: p.rowTracks, smallest: p.smallest, overlaps: p.overlaps.length,
        undersized: p.undersizedTargets.map(t => t.name + ' ' + t.w + 'x' + t.h),
        bannerContent: bEval ? { pass: bEval.pass, measured: bEval.measured, failures: bEval.failures } : null,
        verdict: v, pass: Object.values(v).every(Boolean) && (bEval ? bEval.pass : true),
        sameGeometry: Math.abs(p.rootHeight - pair.base.rootHeight) <= 1 &&
                      Math.abs((p.rects.stage ? p.rects.stage.h : -1) - (pair.base.rects.stage ? pair.base.rects.stage.h : -2)) <= 1 });
    }
    if (PHASE !== 'core') pair.verdict.r11_states = pair.rule11.every(s => s.pass && s.sameGeometry);

    /* ---------------- rule 13 [D-1] banner CONTENT geometry ---------------- */
    if (PHASE !== 'core') {
      /* Discover every banner-bearing room state from the state model itself, so a
         NEW banner state cannot silently escape the oracle (fail-closed coverage). */
      await page.goto(nav('s35-room-live', theme), { waitUntil: 'load' });
      await waitReady(page);
      const discovered = await page.evaluate(BANNER_STATE_DISCOVERY);
      const bannerStates = (discovered && Array.isArray(discovered.states)) ? discovered.states.map(s => s.id) : [];
      const coverage = assertBannerStateCoverage(discovered, bannerStates);

      const cases = [];
      for (const stateId of bannerStates) {
        await page.goto(nav(stateId, theme), { waitUntil: 'load' });
        /* readiness is AWAITED (bounded, rejecting) — and never counts as a pass (g9) */
        let readySignal = null, readyError = null;
        try { readySignal = await waitReady(page); } catch (e) { readyError = String((e && e.message) || e); }
        const probe = readyError ? { fatal: 'READY_TIMEOUT: ' + readyError } : await page.evaluate(BANNER_PROBE);
        const ev = evaluateBannerGeometry(probe, { pair: pairName, state: stateId, theme, viewport: vp.name });
        const bShot = join(SHOTS, LABEL + '__banner-' + stateId + '__' + vp.name + '__' + theme + '.png');
        if (!NOSHOTS) await page.screenshot({ path: bShot });
        cases.push({ state: stateId, capture: NOSHOTS ? null : shotRef(bShot),
                     readySignal: readySignal && readySignal.signal, pass: ev.pass,
                     measured: ev.measured, rules: ev.rules, failures: ev.failures, fatal: ev.fatal || null });
      }
      pair.rule13 = { ruleText: BANNER_RULE_TEXT, ruleIds: BANNER_RULE_IDS, coverage, cases,
                      casesTotal: cases.length, casesPassed: cases.filter(c => c.pass).length };
      /* fail-closed: zero discovered banner states is itself a failure */
      pair.verdict.r13_bannerContent = coverage.pass && cases.length > 0 && cases.every(c => c.pass);
    }

    pair.console = con;
    pair.verdict.r10_console = con.errors.length === 0 && con.pageErrors.length === 0 &&
      con.failedRequests.length === 0 && con.warnings.length === 0;
    pair.verdict.r12_ready = /data-live-room-ready/.test(pair.ready.signal);

    pair.pass = Object.values(pair.verdict).every(Boolean);
    if (!pair.pass) failures.push({ pair: pairName, verdict: pair.verdict });
  } catch (e) {
    pair.error = String((e && e.message) || e);
    pair.pass = false; pair.console = con;
    failures.push({ pair: pairName, error: pair.error });
  }
  pairs.push(pair);
  await ctx.close();
  console.log(LABEL + ' ' + pairName + ' -> ' + (pair.pass ? 'PASS' : 'FAIL') + (pair.error ? ' :: ' + pair.error : ''));
}

await browser.close();

const summary = {
  contract: 'S35_LIVE_ROOM_GEOMETRY_CLOSURE_ADDENDUM.md',
  label: LABEL, referenceDir: REF,
  viewports: VIEWPORTS.map(v => v.name), themes: THEMES,
  pairsTotal: pairs.length, pairsPassed: pairs.filter(p => p.pass).length, pairsFailed: failures.length,
  stateCases: STATE_CASES.map(s => s.key),
  assertions: ['r1_rootHeight', 'r2_noScroll', 'r3_threeRows', 'r4_dockVisible', 'r5_targets', 'r6_noOverlap',
               'r7_selfView', 'r8_sheet', 'r9_keyboard', 'r10_console', 'r11_states', 'r12_ready',
               'r13_bannerContent'],
  bannerOracle: { rules: BANNER_RULE_IDS, ruleText: BANNER_RULE_TEXT,
                  casesTotal: pairs.reduce((n, p) => n + (p.rule13 ? p.rule13.casesTotal : 0), 0),
                  casesPassed: pairs.reduce((n, p) => n + (p.rule13 ? p.rule13.casesPassed : 0), 0) },
  seededCss: INJECT_CSS_PATH || null,
  failures, pairs
};
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, JSON.stringify(summary, null, 2) + '\n');
console.log('\n' + LABEL + ': ' + summary.pairsPassed + '/' + summary.pairsTotal + ' pairs PASS -> ' + OUT);
process.exit(failures.length ? 1 : 0);
