/* Merges the sharded measurement partials into MEASURED_GEOMETRY_RESULTS.json.
   Deterministic: rows are sorted by (pass, viewport, theme, state index). */
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { requireDirectory, failFast } from './env_paths.mjs';
const PKG = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
globalThis.C2Fixtures = require(join(PKG, 'reference/fixtures.js'));
const St = require(join(PKG, 'reference/states.js'));
const idx = Object.fromEntries(St.STATES.map(s => [s.id, s.index]));
/* The shard directory is caller-owned scratch: it has no repository-relative
   default, so it must be supplied and is validated with a typed error. */
const dir = failFast(() => requireDirectory(process.argv[2], 'C2_PARTIALS_DIR',
  'PARTIALS_DIR_REQUIRED', 'the measurement partials directory'));

const parts = readdirSync(dir).filter(f => f.endsWith('.json')).sort()
  .map(f => JSON.parse(readFileSync(join(dir, f), 'utf8')));
const rows = parts.flatMap(p => p.rows);
const captures = parts.flatMap(p => p.captures || []);
const consoleErrors = parts.flatMap(p => p.consoleErrors || []);
const failures = parts.flatMap(p => p.failures || []);
const PASS_ORDER = ['main', 'reduced-motion', 'zoom-200', 'safe-area'];
rows.sort((a, b) => PASS_ORDER.indexOf(a.pass) - PASS_ORDER.indexOf(b.pass)
  || a.viewport.localeCompare(b.viewport) || a.theme.localeCompare(b.theme) || idx[a.state] - idx[b.state]);

/* compaction: drop empty violation arrays and null room controls */
for (const r of rows) {
  for (const k of ['targetsUnder44', 'controlsOutsideViewportX', 'improperOverlaps', 'railControlsUnreachable',
                   'hiddenInputDelegates', 'controlsUnreachable', 'controlsOutsideViewportY', 'violations'])
    if (Array.isArray(r[k]) && r[k].length === 0) delete r[k];
  for (const k of Object.keys(r)) if (r[k] === null || r[k] === undefined) delete r[k];
}

const counts = rows.reduce((a, r) => (a[r.verdict || r.status] = (a[r.verdict || r.status] || 0) + 1, a), {});
const room = rows.filter(r => r.family === 'room');
const byPass = {};
for (const r of rows) { byPass[r.pass] = byPass[r.pass] || { rows: 0, PASS: 0, FAIL: 0 }; byPass[r.pass].rows++; byPass[r.pass][r.verdict] = (byPass[r.pass][r.verdict] || 0) + 1; }
const byViewportTheme = {};
for (const r of rows.filter(r => r.pass === 'main')) {
  const k = `${r.viewport} ${r.theme}`;
  byViewportTheme[k] = byViewportTheme[k] || { rows: 0, PASS: 0, FAIL: 0 };
  byViewportTheme[k].rows++; byViewportTheme[k][r.verdict] = (byViewportTheme[k][r.verdict] || 0) + 1;
}
const liveRoomBoundary = room.filter(r => r.pass === 'main' && r.state === 's35-room-live')
  .map(r => ({ viewport: r.viewport, theme: r.theme, verticalScrollPx: r.verticalScrollPx,
    horizontalOverflowPx: r.horizontalOverflowPx, minTargetPx: r.minTargetPx,
    roomRootHeightPx: r.roomRootHeightPx, clientHeight: r.clientHeight,
    dockVisible: r.dockVisible, sheetAddsNoHeight: r.sheetAddsNoHeight,
    focusMovedIntoSheet: r.focusMovedIntoSheet, focusRestoredOnClose: r.focusRestoredOnClose, verdict: r.verdict }));

const out = {
  schema: 'legalsaathi.tutoring.measured-geometry/1',
  provenance: 'BROWSER_MEASURED',
  package: 'docs/design/tutoring/option_c2_reference_v1',
  engine: 'headless Chromium via Playwright, deviceScaleFactor 1, offline file:// origin',
  supersedes: 'sources/MOBILE_GEOMETRY_RESULTS_HISTORICAL_pending.json (status pending_measured_run) — the historical file is preserved unchanged inside its own approved package and is copied here read-only for provenance.',
  fixtureChecksum: globalThis.C2Fixtures.CHECKSUM,
  budgets: parts[0].budgets,
  totals: { rows: rows.length, ...counts, consoleErrors: consoleErrors.length, readyFailures: failures.filter(f => f.error).length },
  byPass, byViewportTheme,
  roomTotals: { rows: room.length, pass: room.filter(r => r.verdict === 'PASS').length, fail: room.filter(r => r.verdict !== 'PASS').length },
  liveRoomBoundary,
  consoleErrors, failures, captures, rows
};
writeFileSync(join(PKG, 'MEASURED_GEOMETRY_RESULTS.json'), JSON.stringify(out, null, 1) + '\n');
console.log('rows', rows.length, counts, 'room', out.roomTotals, 'captures', captures.length, 'consoleErrors', consoleErrors.length);
console.log('byPass', JSON.stringify(byPass));
console.log('live-room boundary rows:'); liveRoomBoundary.forEach(r => console.log(' ', JSON.stringify(r)));
