/* Option C2 accessibility ORACLE — measurement COLLECTOR (shard runner).
   Drives real Chromium against the reference package that lives in THIS
   checkout and writes ONE raw measurement shard. Adjudication, thresholds and
   the pass/fail verdict live in tools/a11y_oracle_report.mjs, which consumes
   the shards; a shard on its own is never a verdict.

   Provenance is derived at RUNTIME:
     commit       = `git rev-parse HEAD` of the tree this file belongs to
     package path = resolved from import.meta.url and reported repo-relative
   No commit hash and no absolute checkout path is hard-coded anywhere.

   Usage:
     node tools/a11y_oracle.mjs
   Environment (all optional; absolute paths are supplied at RUN time only):
     A11Y_OUT_DIR       directory for the shard file            (default: cwd)
     A11Y_TAG           shard filename tag                      (default: run)
     A11Y_THEMES        comma list                              (default: light,dark)
     A11Y_STATES        comma list                              (default: all 10 S-35 states)
     A11Y_PHASES        contrast|focus|keyboard|hygiene         (default: all four)
     PLAYWRIGHT_MODULE  path to playwright's index.mjs          (default: <repo>/frontend/node_modules/playwright/index.mjs)
     AXE_CORE_PATH      path to axe.min.js                      (default: <repo>/frontend/node_modules/axe-core/axe.min.js)
*/
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { join, dirname, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import os from 'node:os';
import { PROBE, FOCUS_PROBE } from './a11y_oracle_probes.mjs';
import { CONTROLS, ALL_STATES, VIEWPORT, validateProvenance } from './a11y_oracle_contract.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = join(HERE, '..');
const git = (...a) => execFileSync('git', ['-C', PKG, ...a], { encoding: 'utf8' }).trim();
const REPO_ROOT = git('rev-parse', '--show-toplevel');
const HEAD = git('rev-parse', 'HEAD');
const PKG_REL = relative(REPO_ROOT, PKG).split(sep).join('/');
const TREE_STATUS = git('status', '--porcelain');

const OUT_DIR = process.env.A11Y_OUT_DIR || process.cwd();
const TAG = process.env.A11Y_TAG || 'run';
const THEMES = (process.env.A11Y_THEMES || 'light,dark').split(',').filter(Boolean);
const STATES = (process.env.A11Y_STATES || ALL_STATES.join(',')).split(',').filter(Boolean);
const PHASES = (process.env.A11Y_PHASES || 'contrast,focus,keyboard,hygiene').split(',').filter(Boolean);
if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true });

const firstExisting = (c) => c.find(p => p && existsSync(p)) || null;
const PW_PATH = firstExisting([process.env.PLAYWRIGHT_MODULE, join(REPO_ROOT, 'frontend/node_modules/playwright/index.mjs')]);
if (!PW_PATH) throw new Error('playwright not resolvable; set PLAYWRIGHT_MODULE');
const AXE_PATH = firstExisting([process.env.AXE_CORE_PATH, join(REPO_ROOT, 'frontend/node_modules/axe-core/axe.min.js')]);
if (!AXE_PATH) throw new Error('axe-core not resolvable; set AXE_CORE_PATH');
const AXE_SRC = readFileSync(AXE_PATH, 'utf8');
const pkgVersion = (p) => { const f = join(dirname(p), 'package.json'); return existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')).version : 'unknown'; };

const { chromium } = await import(pathToFileURL(PW_PATH).href);
const BASE = pathToFileURL(join(PKG, 'reference/index.html')).href;
const READY_MS = 15000;

const browser = await chromium.launch({ headless: true });
const provenance = {
  generatedAt: new Date().toISOString(),
  commit: HEAD,
  runtimeHeadCommit: HEAD,
  commitSource: 'git rev-parse HEAD (runtime)',
  repoRootBasename: REPO_ROOT.split(sep).pop(),
  packagePathRelativeToRepo: PKG_REL,
  workingTreeClean: TREE_STATUS === '',
  workingTreeStatus: TREE_STATUS ? TREE_STATUS.split('\n') : [],
  node: process.version,
  os: { platform: os.platform(), release: os.release(), arch: os.arch(), type: os.type() },
  browser: { name: 'chromium', version: browser.version(), executablePath: chromium.executablePath(), headless: true, playwright: pkgVersion(PW_PATH) },
  axe: { version: pkgVersion(AXE_PATH), resolvedFrom: process.env.AXE_CORE_PATH ? 'AXE_CORE_PATH (runtime env)' : '<repo>/frontend/node_modules' },
  viewport: VIEWPORT
};
provenance.validation = validateProvenance(provenance);
provenance.valid = provenance.validation.valid;

const raw = { text: [], nonText: [], focus: [], axe: [], keyboard: [], storage: [], readiness: {} };
/* Console / network hygiene is tallied PER PHASE. The `hygiene` phase never
   injects axe-core, so it is the authoritative package number; the axe phase is
   recorded separately together with axe-core's own file:// XHR preload noise,
   which is isolated by phase rather than silently dropped. */
const consoleByPhase = {};
const bucket = (phase) => (consoleByPhase[phase] = consoleByPhase[phase] ||
  { phase, errors: 0, warnings: 0, pageErrors: 0, failedRequests: 0, failedRequestDetail: [], consoleDetail: [] });
const wire = (page, theme, phase) => {
  const b = bucket(phase);
  page.on('console', m => { const t = m.type();
    if (t === 'error') { b.errors++; b.consoleDetail.push({ theme, phase, type: t, text: m.text().slice(0, 240) }); }
    else if (t === 'warning') { b.warnings++; b.consoleDetail.push({ theme, phase, type: t, text: m.text().slice(0, 240) }); } });
  page.on('pageerror', e => { b.pageErrors++; b.consoleDetail.push({ theme, phase, type: 'pageerror', text: String(e).slice(0, 240) }); });
  page.on('requestfailed', r => { b.failedRequests++;
    b.failedRequestDetail.push({ theme, phase, url: r.url().slice(-120), resourceType: r.resourceType(),
      failure: r.failure() && r.failure().errorText }); });
};
const goto = (page, state) => page.evaluate(([id, t]) => {
  window.__C2.goto(id);
  return Promise.race([window.__C2_READY, new Promise((_, rej) => setTimeout(() => rej(new Error('READY_TIMEOUT ' + id)), t))]);
}, [state, READY_MS]);

/* ---------------------------- contrast + axe ---------------------------- */
if (PHASES.includes('contrast')) for (const theme of THEMES) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, colorScheme: theme });
  const page = await ctx.newPage(); wire(page, theme, 'contrast+axe');
  await page.goto(BASE + '?state=' + STATES[0] + '&theme=' + theme, { waitUntil: 'load' });
  await page.addScriptTag({ content: AXE_SRC });
  for (const state of STATES) {
    await goto(page, state);
    raw.readiness[theme + '/' + state] = await page.evaluate(() => {
      const lr = document.querySelector('.route.room') || document.querySelector('.live');
      return { isRoomFamily: !!lr, dataLiveRoomReady: lr ? lr.getAttribute('data-live-room-ready') : null, readyFlag: window.__C2_READY_FLAG === true };
    });
    const probe = await page.evaluate(PROBE, { controls: CONTROLS });
    probe.text.forEach(r => raw.text.push({ theme, state, ...r }));
    probe.nonText.forEach(r => raw.nonText.push({ theme, state, ...r }));
    const st = await page.evaluate(() => ({
      localStorage: Object.keys(window.localStorage || {}).length,
      sessionStorage: Object.keys(window.sessionStorage || {}).length,
      documentCookie: document.cookie ? document.cookie.split(';').filter(Boolean).length : 0 }));
    raw.storage.push({ theme, state, ...st, contextCookies: (await ctx.cookies()).length });

    const ax = await page.evaluate(async () => {
      const res = await window.axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] },
        resultTypes: ['violations', 'incomplete'] });
      const slim = (v) => ({ id: v.id, impact: v.impact, help: v.help, tags: v.tags,
        nodes: v.nodes.map(n => ({ target: n.target.join(' '), html: (n.html || '').slice(0, 160),
          message: (n.any || []).concat(n.all || [], n.none || []).map(c => c.message).join(' | ').slice(0, 260),
          data: (n.any && n.any[0] && n.any[0].data) || null })) });
      return { violations: res.violations.map(slim), incomplete: (res.incomplete || []).map(slim), passRuleCount: res.passes ? res.passes.length : null };
    });
    /* every axe colour-contrast INCOMPLETE node is recomputed here, so the
       reporter can adjudicate it instead of leaving it unresolved */
    const resolutions = [];
    for (const v of ax.incomplete.filter(v => v.id === 'color-contrast')) for (const n of v.nodes) {
      const computed = await page.evaluate((sel) => {
        const parse = (c) => { const m = String(c).match(/rgba?\(([^)]+)\)/i); if (!m) return null;
          const p = m[1].split(/[,\s\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
        const over = (f, b) => ({ r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1 });
        const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
          return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
        const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return Math.round(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)) * 100) / 100; };
        const hex = (c) => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
        const effBg = (el) => { let n = el, stack = [], chain = [];
          while (n && n.nodeType === 1) { const cs = getComputedStyle(n); const c = parse(cs.backgroundColor);
            const img = cs.backgroundImage && cs.backgroundImage !== 'none';
            if (c && c.a > 0) { stack.push(c); chain.push((n.getAttribute('data-testid') || n.className || n.tagName) + ':' + hex(c) + (c.a < 1 ? '@' + c.a : '') + (img ? '+bgimage' : '')); }
            if (c && c.a >= 1) break; n = n.parentElement; }
          let base = { r: 255, g: 255, b: 255, a: 1 }; const last = stack[stack.length - 1];
          if (last && last.a >= 1) base = last; let acc = base;
          for (let i = stack.length - (last && last.a >= 1 ? 2 : 1); i >= 0; i--) acc = over(stack[i], acc);
          return { color: acc, chain }; };
        let el; try { el = document.querySelector(sel); } catch (e) { return { error: 'unresolvable selector: ' + e.message }; }
        if (!el) return { error: 'node not found for selector ' + sel };
        const cs = getComputedStyle(el); const fgRaw = parse(cs.color); const bg = effBg(el);
        if (!fgRaw) return { error: 'no computed colour' };
        const fg = fgRaw.a < 1 ? over(fgRaw, bg.color) : fgRaw;
        const fs = parseFloat(cs.fontSize), fw = parseInt(cs.fontWeight, 10) || 400;
        const parentOfEl = el.parentElement;
        return { fg: hex(fg), bg: hex(bg.color), bgChain: bg.chain.slice(0, 4), fontPx: Math.round(fs * 10) / 10, weight: fw,
          large: fs >= 24 || (fs >= 18.66 && fw >= 700), ratio: ratio(fg, bg.color),
          overBackgroundImage: bg.chain.some(c => c.indexOf('+bgimage') >= 0),
          text: (el.textContent || '').trim().slice(0, 56), parentTestId: parentOfEl ? parentOfEl.getAttribute('data-testid') : null };
      }, n.target);
      resolutions.push({ theme, state, target: n.target, html: n.html, axeMessage: n.message, axeData: n.data, computed });
    }
    raw.axe.push({ theme, state, ...ax, colorContrastIncompleteMeasurements: resolutions });
  }
  await ctx.close();
}

/* ------------------------- focus indicator sweep ------------------------ */
if (PHASES.includes('focus')) for (const theme of THEMES) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, colorScheme: theme });
  const page = await ctx.newPage(); wire(page, theme, 'focus');
  await page.goto(BASE + '?state=' + STATES[0] + '&theme=' + theme, { waitUntil: 'load' });
  for (const state of STATES) {
    await goto(page, state);
    const count = await page.evaluate(() => {
      const sel = 'button,a[href],a[data-href],input,select,textarea,summary,[role=button]';
      return [...document.querySelectorAll(sel)].filter(e => { const cs = getComputedStyle(e);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && !e.closest('[inert],[aria-hidden=true],#reviewer'); }).length;
    });
    await page.evaluate(() => { document.activeElement && document.activeElement.blur(); });
    const seen = new Set();
    for (let i = 0; i < count + 2; i++) {
      await page.keyboard.press('Tab');
      const f = await page.evaluate(FOCUS_PROBE);
      if (!f) continue;
      const key = f.selector + '|' + f.ringColor + '|' + f.outerAdjacent + '|' + f.innerAdjacent;
      if (seen.has(key)) continue;
      seen.add(key);
      raw.focus.push({ theme, state, ...f });
    }
  }
  await ctx.close();
}

/* ---------- keyboard order / trap / escape / return / reduced motion ---- */
if (PHASES.includes('keyboard')) for (const theme of THEMES) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, colorScheme: theme });
  const page = await ctx.newPage(); wire(page, theme, 'keyboard');
  await page.goto(BASE + '?state=s35-room-live&theme=' + theme, { waitUntil: 'load' });
  await page.waitForSelector('[data-live-room-ready="true"]', { timeout: READY_MS, state: 'attached' });
  const FOCUSABLE = () => {
    const sel = 'button,a[href],a[data-href],input,select,textarea,summary,[role=button]';
    return [...document.querySelectorAll(sel)].filter(e => { const cs = getComputedStyle(e);
      return cs.display !== 'none' && cs.visibility !== 'hidden' && !e.closest('[inert],[aria-hidden=true],#reviewer'); });
  };
  const dom = await page.evaluate(() => {
    const sel = 'button,a[href],a[data-href],input,select,textarea,summary,[role=button]';
    return [...document.querySelectorAll(sel)].filter(e => { const cs = getComputedStyle(e);
      return cs.display !== 'none' && cs.visibility !== 'hidden' && !e.closest('[inert],[aria-hidden=true],#reviewer'); })
      .map(e => ({ n: e.getAttribute('data-testid') || e.id || e.tagName, name: (e.getAttribute('aria-label') || (e.textContent || '').trim()).slice(0, 50) })); });
  const order = [];
  for (let i = 0; i < dom.length; i++) {
    await page.keyboard.press('Tab');
    const cur = await page.evaluate(() => { const a = document.activeElement; if (!a || a === document.body) return null;
      return { n: a.getAttribute('data-testid') || a.id || a.tagName, name: (a.getAttribute('aria-label') || (a.textContent || '').trim()).slice(0, 50) }; });
    if (!cur) break; order.push(cur);
  }
  const namesBefore = order.map(o => o.name);
  await page.click('[data-testid=session-info]');
  await page.waitForFunction(() => document.querySelector('[data-testid=sheet]').getAttribute('data-open') === '1', null, { timeout: 5000, polling: 'raf' });
  const trap = [];
  for (let i = 0; i < 10; i++) { await page.keyboard.press('Tab');
    trap.push(await page.evaluate(() => { const sh = document.querySelector('[data-testid=sheet]');
      return { inside: sh.contains(document.activeElement), n: document.activeElement && (document.activeElement.getAttribute('data-testid') || document.activeElement.id || document.activeElement.tagName) }; })); }
  await page.keyboard.press('Escape');
  const afterEsc = await page.evaluate(() => { const sh = document.querySelector('[data-testid=sheet]');
    return { open: sh.getAttribute('data-open') === '1', focusReturned: document.activeElement === document.querySelector('[data-testid=session-info]') }; });
  const namesAfter = await page.evaluate(() => {
    const sel = 'button,a[href],a[data-href],input,select,textarea,summary,[role=button]';
    return [...document.querySelectorAll(sel)].filter(e => { const cs = getComputedStyle(e);
      return cs.display !== 'none' && cs.visibility !== 'hidden' && !e.closest('[inert],[aria-hidden=true],#reviewer'); })
      .map(e => (e.getAttribute('aria-label') || (e.textContent || '').trim()).slice(0, 50)); });
  const targets = await page.evaluate(() => {
    const sel = 'button,a[href],a[data-href],input,select,textarea,summary,[role=button]';
    return [...document.querySelectorAll(sel)].filter(e => { const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      if (e.closest('[inert],[aria-hidden=true],#reviewer')) return false;
      const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
      .map(e => { const r = e.getBoundingClientRect(); return { n: e.getAttribute('data-testid') || e.id, w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 }; }); });
  await ctx.close();

  const rctx = await browser.newContext({ viewport: VIEWPORT, colorScheme: theme, reducedMotion: 'reduce' });
  const rp = await rctx.newPage(); wire(rp, theme, 'keyboard');
  await rp.goto(BASE + '?state=s35-room-live&theme=' + theme, { waitUntil: 'load' });
  await rp.waitForSelector('[data-live-room-ready="true"]', { timeout: READY_MS, state: 'attached' });
  const rm = await rp.evaluate(() => {
    const rs = getComputedStyle(document.documentElement);
    const animated = [...document.querySelectorAll('*')].filter(e => { const cs = getComputedStyle(e);
      return (cs.transitionDuration + ' ' + cs.animationDuration).split(/[, ]+/).filter(Boolean).some(v => parseFloat(v) > 0); });
    return { motionFast: rs.getPropertyValue('--motion-fast').trim(), motionBase: rs.getPropertyValue('--motion-base').trim(),
      prefersReduce: matchMedia('(prefers-reduced-motion: reduce)').matches, residualAnimatedCount: animated.length }; });
  await rctx.close();

  raw.keyboard.push({ theme, domOrder: dom.map(d => d.n), tabOrder: order.map(o => o.n),
    tabOrderMatchesDom: JSON.stringify(order.map(o => o.n)) === JSON.stringify(dom.map(d => d.n).slice(0, order.length)),
    allReached: order.length >= dom.length, focusTrapAllInside: trap.every(t => t.inside),
    escapeDismissed: afterEsc.open === false, focusReturnedToTrigger: afterEsc.focusReturned,
    accessibleNamesStable: JSON.stringify(namesBefore) === JSON.stringify(namesAfter.slice(0, namesBefore.length)),
    targets, undersizedTargets: targets.filter(t => t.w < 43.5 || t.h < 43.5), reducedMotion: rm, trapProbe: trap });
}
/* ------------- axe-free hygiene pass: the authoritative numbers ---------- */
if (PHASES.includes('hygiene')) for (const theme of THEMES) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, colorScheme: theme });
  const page = await ctx.newPage(); wire(page, theme, 'hygiene');
  await page.goto(BASE + '?state=' + STATES[0] + '&theme=' + theme, { waitUntil: 'load' });
  for (const state of STATES) {
    await goto(page, state);
    const st = await page.evaluate(() => ({
      localStorage: Object.keys(window.localStorage || {}).length,
      sessionStorage: Object.keys(window.sessionStorage || {}).length,
      documentCookie: document.cookie ? document.cookie.split(';').filter(Boolean).length : 0 }));
    raw.storage.push({ phase: 'hygiene', theme, state, ...st, contextCookies: (await ctx.cookies()).length });
  }
  /* 200% reflow + safe-area sanity at the same time: no horizontal scroll and
     no clipped dock when the effective viewport is halved by a 200% zoom */
  for (const theme2 of [theme]) {
    const zctx = await browser.newContext({ viewport: { width: Math.round(VIEWPORT.width / 2), height: Math.round(VIEWPORT.height / 2) }, colorScheme: theme2, deviceScaleFactor: 2 });
    const zp = await zctx.newPage(); wire(zp, theme2, 'hygiene');
    await zp.goto(BASE + '?state=s35-room-live&theme=' + theme2, { waitUntil: 'load' });
    await zp.waitForSelector('[data-live-room-ready="true"]', { timeout: READY_MS, state: 'attached' });
    raw.reflow = raw.reflow || [];
    raw.reflow.push(await zp.evaluate((t) => {
      const de = document.documentElement;
      const dock = document.querySelector('[data-testid=control-dock]');
      const r = dock ? dock.getBoundingClientRect() : null;
      return { theme: t, viewportCssPx: { w: innerWidth, h: innerHeight },
        horizontalScroll: de.scrollWidth > de.clientWidth + 1,
        scrollWidth: de.scrollWidth, clientWidth: de.clientWidth,
        dockVisible: !!r && r.height > 0 && r.bottom <= innerHeight + 1,
        dockRect: r ? { top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height) } : null }; }, theme2));
    await zctx.close();
  }
  await ctx.close();
}
await browser.close();

const shard = { schema: 'legalsaathi.option-c2.a11y-oracle-shard/1', provenance,
  shard: { themes: THEMES, states: STATES, phases: PHASES }, raw, consoleByPhase };
const file = join(OUT_DIR, 'a11y_shard__' + TAG + '.json');
writeFileSync(file, JSON.stringify(shard, null, 2) + '\n');
console.log('shard written:', file);
console.log('commit(runtime):', provenance.commit, '| package:', provenance.packagePathRelativeToRepo,
  '| clean:', provenance.workingTreeClean, '| provenance valid:', provenance.valid);
console.log('rows: text', raw.text.length, 'nonText', raw.nonText.length, 'focus', raw.focus.length,
  'axeStates', raw.axe.length, 'keyboard', raw.keyboard.length);
for (const b of Object.values(consoleByPhase)) console.log('console[' + b.phase + ']:',
  JSON.stringify({ errors: b.errors, warnings: b.warnings, pageErrors: b.pageErrors, failedRequests: b.failedRequests }));
