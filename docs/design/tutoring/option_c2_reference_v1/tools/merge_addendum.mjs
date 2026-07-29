/* Merges the sharded S-35 live-room addendum runs into the two package artifacts.
   Usage:
     node tools/merge_addendum.mjs <before-chunk-dir> <after-chunk-dir>
     node tools/merge_addendum.mjs --before-from <BEFORE_AFTER_LIVE_ROOM_ADDENDUM.json> <after-chunk-dir>

   `--before-from` CARRIES FORWARD the already-measured BEFORE side (the
   historical commit) instead of re-measuring it. The BEFORE side is a property
   of a commit that is not being changed, so re-running it would produce the same
   numbers; carrying them forward keeps the artifact honest about what was
   measured when, and the `note` field records it explicitly.
   Deterministic: rows are sorted by (orientation, viewport, theme); no timestamps. */
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PKG = join(dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const beforeFromIdx = argv.indexOf('--before-from');
const BEFORE_FROM = beforeFromIdx >= 0 ? argv[beforeFromIdx + 1] : null;
const positional = argv.filter((a, i) => a !== '--before-from' && i !== beforeFromIdx + 1);
const beforeDir = BEFORE_FROM ? null : positional[0];
const afterDir = BEFORE_FROM ? positional[0] : positional[1];
if (!afterDir) { console.error('TYPED ERROR AFTER_CHUNK_DIR_REQUIRED — pass the AFTER chunk directory'); process.exit(2); }

const load = (dir) => {
  const out = {};
  for (const f of readdirSync(dir).filter(f => f.endsWith('.json')).sort()) {
    for (const p of JSON.parse(readFileSync(join(dir, f), 'utf8')).pairs) {
      out[p.pair] = out[p.pair] || {};
      /* core and states phases are merged per pair; later keys win only when present */
      for (const [k, v] of Object.entries(p)) {
        if (k === 'verdict') { out[p.pair].verdict = Object.assign({}, out[p.pair].verdict, v); }
        else if (k === 'rule11' && (!v || !v.length) && out[p.pair].rule11) { /* keep */ }
        else if (v !== undefined && v !== null) out[p.pair][k] = v;
      }
    }
  }
  return out;
};

const ORDER = ['390x844', '430x932', '768x1024', '844x390', '932x430', '1024x768'];
const key = (p) => ORDER.indexOf(p.viewport) * 2 + (p.theme === 'light' ? 0 : 1);
/* Rehydrate a carried-forward BEFORE side into the shape `side()` consumes, so
   the emitted BEFORE block is byte-identical to the one it came from. */
const rehydrate = (file) => {
  const prev = JSON.parse(readFileSync(file, 'utf8'));
  const out = {};
  for (const row of prev.pairs) {
    const b = row.before;
    if (!b) { out[row.pair] = null; continue; }
    out[row.pair] = {
      pair: row.pair, viewport: row.viewport, orientation: row.orientation, theme: row.theme,
      ready: { signal: b.readySignal }, verdict: b.verdict, pass: b.pass,
      base: {
        rootHeight: b.rootHeight, viewport: { h: b.viewportHeight }, rootHeightDelta: b.rootHeightDelta,
        maxOverflowY: b.maxScrollOverflowY, maxOverflowX: b.maxScrollOverflowX,
        gridRows: b.gridRows, rowTracks: b.rowTracks,
        smallest: b.smallestControl, undersizedTargets: b.undersizedControls,
        overlaps: new Array(b.overlapViolations).fill({ carriedForward: true }),
        rects: b.rects,
        scroll: b.scrollByContainer.map(c => ({ container: c.container, scrollHeight: c.scrollH, clientHeight: c.clientH,
                                                scrollWidth: c.scrollW, clientWidth: c.clientW,
                                                overflowY: c.overflowY, overflowX: c.overflowX }))
      }
    };
  }
  return out;
};
const before = BEFORE_FROM ? rehydrate(BEFORE_FROM) : load(beforeDir);
const after = load(afterDir);
const names = Object.keys(after).sort((a, b) => key(after[a]) - key(after[b]));

/* ---------- artifact 1: full AFTER results ---------- */
const compact = (p) => {
  const c = JSON.parse(JSON.stringify(p));
  if (c.base) delete c.base.targets;                 /* smallest + undersized are retained */
  if (c.rule11) c.rule11.forEach(s => { delete s.targets; });
  return c;
};
const results = {
  contract: 'S35_LIVE_ROOM_GEOMETRY_CLOSURE_ADDENDUM.md',
  scope: 'S-35 live room only. S-31, S-33, S-34 and the S-35 refund journey are untouched.',
  viewports: ORDER, themes: ['light', 'dark'],
  assertions: {
    r1_rootHeight: 'live-room root height == available viewport height within 1px',
    r2_noScroll: 'scrollHeight<=clientHeight+1 and scrollWidth<=clientWidth+1 for page, body, #app, device viewport, live host, live root, stage',
    r3_threeRows: 'exactly three layout rows: header / minmax(0,1fr) stage / dock',
    r4_dockVisible: 'mic, camera, device-settings and Leave fully visible without scrolling',
    r5_targets: 'every interactive rectangle >= 44x44',
    r6_noOverlap: 'no overlap between controls, safe area, mentor name badge or self-view; self-view stays inside the stage',
    r7_selfView: 'self-view moves through all four corners; minimised exposes exactly one non-overlapping 44x44 restore control',
    r8_sheet: 'details sheet stays inside the live root, adds no scroll, traps focus, closes on Escape, restores focus to its trigger',
    r9_keyboard: 'every control keyboard-reachable in DOM order with a stable accessible name',
    r10_console: 'zero console errors, zero warnings, zero page errors, zero failed requests',
    r11_states: 'camera-denied, mic-denied, disconnected/reconnecting, provider-failure, leave-confirmation and device-release preserve the same geometry',
    r12_ready: 'the run waits on data-live-room-ready="true" with a bounded rejecting timeout; no fixed sleeps',
    r13_bannerContent: '[D-1] every provider-error/reconnect banner state the state model declares passes the nine content-geometry rules: 18-24px status icon; non-zero visible title and detail; message column >= max(120px, 40% of the banner); text inside the banner; no icon/text overlap; scrollWidth<=clientWidth; nothing clipped by an overflow:hidden ancestor; banner inside the mentor tile and stage; readiness never counts as a visual pass on its own'
  },
  pairsTotal: names.length,
  pairsPassed: names.filter(n => after[n].pass).length,
  stateRowsTotal: names.reduce((a, n) => a + (after[n].rule11 || []).length, 0),
  stateRowsPassed: names.reduce((a, n) => a + (after[n].rule11 || []).filter(s => s.pass && s.sameGeometry).length, 0),
  bannerContentRowsTotal: names.reduce((a, n) => a + ((after[n].rule13 && after[n].rule13.cases) || []).length, 0),
  bannerContentRowsPassed: names.reduce((a, n) => a + ((after[n].rule13 && after[n].rule13.cases) || []).filter(c => c.pass).length, 0),
  pairs: names.map(n => compact(after[n]))
};
writeFileSync(join(PKG, 'LIVE_ROOM_ADDENDUM_RESULTS.json'), JSON.stringify(results, null, 2) + '\n');

/* ---------- artifact 2: before/after rectangles ---------- */
const side = (p) => {
  if (!p || !p.base) return null;
  const b = p.base;
  return {
    rootHeight: b.rootHeight, viewportHeight: b.viewport.h, rootHeightDelta: b.rootHeightDelta,
    maxScrollOverflowY: b.maxOverflowY, maxScrollOverflowX: b.maxOverflowX,
    gridRows: b.gridRows, rowTracks: b.rowTracks,
    smallestControl: b.smallest ? { name: b.smallest.name, w: b.smallest.w, h: b.smallest.h } : null,
    undersizedControls: b.undersizedTargets.map(t => ({ name: t.name, w: t.w, h: t.h })),
    overlapViolations: b.overlaps.length,
    rects: b.rects,
    scrollByContainer: b.scroll.map(s => ({ container: s.container, scrollH: s.scrollHeight, clientH: s.clientHeight, scrollW: s.scrollWidth, clientW: s.clientWidth, overflowY: s.overflowY, overflowX: s.overflowX })),
    readySignal: p.ready ? p.ready.signal : null,
    verdict: p.verdict, pass: !!p.pass
  };
};
const ba = {
  contract: 'S35_LIVE_ROOM_GEOMETRY_CLOSURE_ADDENDUM.md',
  note: 'BEFORE is commit 647aa76 reference/ measured unmodified; AFTER is this commit. Both measured in the same real headless Chromium with the same harness.' +
        (BEFORE_FROM ? ' The BEFORE container-geometry side is CARRIED FORWARD unchanged from the previous artifact (the commit it describes was not modified); the AFTER side and every D-1 banner rectangle below were measured fresh on this commit.' : ''),
  rootCauses: [
    { id: 'RC-1', defect: '.live declared height:100dvh then height:100vh, so 100vh won and defeated dvh', fix: '.live-host declares the 100vh FALLBACK FIRST, then 100dvh; .live is height:100%' },
    { id: 'RC-2', defect: 'the rig .app used only min-height:100%, breaking the percentage height chain so viewport units measured the outer browser', fix: 'body[data-family=room] #app{height:100%}, .live-host, and .vp[data-screen=s35live|s35land]>.app{height:100%;min-height:0;overflow:hidden}; rig exercised by ?rig=vp&device=WxH' },
    { id: 'RC-3', defect: '.lctrl permitted flex-wrap:wrap so the persistent dock could become multiple rows', fix: '.lctrl{flex:0 0 auto;flex-wrap:nowrap}; the only remaining wrap is the documented WCAG 2.2 1.4.10 reflow exception below 361px' },
    { id: 'RC-4', defect: 'session-details and sheet-close carried inline 40x40 minimums', fix: 'no inline minimums remain; .live button,.live [role=button]{min-width:44px;min-height:44px} is the floor' },
    { id: 'RC-5', defect: 'self-view move/minimise were 30x30 and the landscape self-view was 78x58, too small for two 44x44 controls', fix: 'controls moved inside the self-view; portrait 112x140 and landscape 116x100 contain two 44x44 targets without overlap; minimised hides .selfmove, the tile >svg and .nm2, leaving exactly one 44x44 restore control' },
    { id: 'RC-6', defect: 'the live container did not establish the explicit positioned constrained three-row layout', fix: '.live{position:relative;height:100%;min-height:0;overflow:hidden;display:grid;grid-template-rows:auto minmax(0,1fr) auto} with .stage{min-width:0;min-height:0;overflow:hidden}' }
  ],
  pairs: names.map(n => ({ pair: n, viewport: after[n].viewport, orientation: after[n].orientation, theme: after[n].theme,
                           before: side(before[n]), after: side(after[n]),
                           /* [D-1] the rectangles a user actually reads, per banner state */
                           bannerContentAfter: ((after[n].rule13 && after[n].rule13.cases) || [])
                             .map(c => ({ state: c.state, pass: c.pass,
                                          iconW: c.measured && c.measured.iconW, iconH: c.measured && c.measured.iconH,
                                          titleW: c.measured && c.measured.titleW, detailW: c.measured && c.measured.detailW,
                                          columnW: c.measured && c.measured.columnW, bannerW: c.measured && c.measured.bannerW,
                                          requiredColumnW: c.measured && c.measured.requiredColumnW,
                                          readyAttr: c.measured && c.measured.readyAttr })) }))
};
writeFileSync(join(PKG, 'BEFORE_AFTER_LIVE_ROOM_ADDENDUM.json'), JSON.stringify(ba, null, 2) + '\n');
console.log(`pairs ${results.pairsPassed}/${results.pairsTotal} PASS, state rows ${results.stateRowsPassed}/${results.stateRowsTotal} PASS, ` +
            `banner content rows ${results.bannerContentRowsPassed}/${results.bannerContentRowsTotal} PASS`);
process.exit((results.pairsPassed === results.pairsTotal &&
              results.stateRowsPassed === results.stateRowsTotal &&
              results.bannerContentRowsTotal > 0 &&
              results.bannerContentRowsPassed === results.bannerContentRowsTotal) ? 0 : 1);
