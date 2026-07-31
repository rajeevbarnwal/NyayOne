/* Option C2 accessibility ORACLE — adjudicator / reporter.
   Consumes one or more raw measurement shards written by tools/a11y_oracle.mjs,
   applies the WCAG thresholds and the 1.4.11 adjudication register, and owns
   the verdict.

   It EXITS NON-ZERO when any of the following is true:
     * provenance is invalid (stale/hard-coded commit, absolute package path,
       dirty worktree, missing browser/OS/environment record);
     * the shards do not cover the full theme x state matrix;
     * any text row fails;
     * any APPLICABLE non-text row fails, or any non-text row is unadjudicated
       or waived without a measured, passing identifying feature;
     * any focus-indicator row fails;
     * axe reports any WCAG A/AA violation node;
     * any axe colour-contrast `incomplete` node is left unresolved or resolves
       to a failing ratio.
   `incomplete`, `NOT_APPLICABLE` and `reviewed-only` are never counted as PASS.

   Usage:
     node tools/a11y_oracle_report.mjs <shard.json> [<shard.json> ...] [--out-dir DIR] [--tag TAG]
*/
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import {
  RESULT, WCAG, evaluateTextRow, evaluateNonTextRow, evaluateFocusRow, rollup, validateProvenance
} from './a11y_oracle_core.mjs';
import { ADJUDICATION, ALL_STATES, ALL_THEMES, BEST_PRACTICE_ONLY_RULE_IDS, BEST_PRACTICE_NOTE } from './a11y_oracle_contract.mjs';

const argv = process.argv.slice(2);
const flag = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const OUT_DIR = flag('--out-dir', process.cwd());
const TAG = flag('--tag', 'final');
const files = argv.filter(a => a.endsWith('.json'));
if (!files.length) { console.error('no shard files given'); process.exit(2); }
if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true });

const shards = files.map(f => ({ file: f, data: JSON.parse(readFileSync(f, 'utf8')) }));
const blockers = [];

/* --------------------------- provenance gate ---------------------------- */
const provenances = shards.map(s => s.data.provenance);
const commits = [...new Set(provenances.map(p => p.commit))];
const provenanceChecks = provenances.map((p, i) => ({ shard: files[i], ...validateProvenance(p) }));
const provenanceValid = provenanceChecks.every(c => c.valid) && commits.length === 1;
if (!provenanceValid) blockers.push('provenance');

/* ------------------------------ coverage -------------------------------- */
const covered = new Set();
const focusCovered = new Set();
const keyboardThemes = new Set();
for (const { data } of shards) {
  for (const a of data.raw.axe) covered.add(a.theme + '/' + a.state);
  for (const f of data.raw.focus) focusCovered.add(f.theme + '/' + f.state);
  for (const k of data.raw.keyboard) keyboardThemes.add(k.theme);
}
const required = [];
for (const t of ALL_THEMES) for (const s of ALL_STATES) required.push(t + '/' + s);
const missingContrast = required.filter(k => !covered.has(k));
const missingFocus = required.filter(k => !focusCovered.has(k));
const missingKeyboard = ALL_THEMES.filter(t => !keyboardThemes.has(t));
const coverage = { requiredCells: required.length, contrastCovered: covered.size, missingContrast,
  focusCovered: focusCovered.size, missingFocus, keyboardThemes: [...keyboardThemes], missingKeyboard,
  complete: !missingContrast.length && !missingFocus.length && !missingKeyboard.length };
if (!coverage.complete) blockers.push('coverage');

/* ------------------------------- dedupe --------------------------------- */
const all = (k) => shards.flatMap(s => s.data.raw[k]);
function dedupe(rows, keyFn) {
  const m = new Map();
  for (const r of rows) {
    const k = keyFn(r);
    if (!m.has(k)) m.set(k, { ...r, states: new Set(), samples: [] });
    const e = m.get(k);
    e.states.add(r.theme + '/' + r.state);
    if (e.samples.length < 3) e.samples.push((r.selector || '') + (r.sample ? ' :: ' + r.sample : '') + (r.facet ? ' :: ' + r.facet : ''));
  }
  return [...m.values()].map(e => ({ ...e, states: [...e.states].sort() }));
}

const textRows = dedupe(all('text'), r => [r.theme, r.fg, r.bg, r.large].join('|'))
  .map(evaluateTextRow).sort((a, b) => a.ratio - b.ratio);

const nonTextRows = dedupe(all('nonText'), r => [r.theme, r.facet, r.fg, r.bg].join('|')).map(r => {
  const declared = ADJUDICATION[r.selector + '|' + r.facet];
  let adj = declared ? { ...declared } : null;
  if (adj && adj.status === 'NOT_APPLICABLE' && r.identifying) {
    adj.identifiedBy = { feature: r.identifying.feature, selector: r.identifying.selector };
    adj.substitute = { fg: r.identifying.fg, bg: r.identifying.bg, ratio: r.identifying.ratio };
  }
  return evaluateNonTextRow({ ...r, adjudication: adj });
}).sort((a, b) => a.ratio - b.ratio);

const focusRows = dedupe(all('focus'), r => [r.theme, r.selector, r.ringColor, r.outerAdjacent, r.innerAdjacent].join('|'))
  .map(evaluateFocusRow).sort((a, b) => (a.ratio == null ? -1 : a.ratio) - (b.ratio == null ? -1 : b.ratio));

const rollups = { text: rollup(textRows), nonText: rollup(nonTextRows), focus: rollup(focusRows) };
if (rollups.text.blocking) blockers.push('text-contrast');
if (rollups.nonText.blocking) blockers.push('non-text-contrast');
if (rollups.focus.blocking) blockers.push('focus-indicator');

/* --------------------------------- axe ---------------------------------- */
const WCAG_AA_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const isWcagAA = v => (v.tags || []).some(t => WCAG_AA_TAGS.includes(t));
const axeStates = all('axe');
const violations = axeStates.flatMap(s => s.violations.map(v => ({ theme: s.theme, state: s.state, ...v })));
const incomplete = axeStates.flatMap(s => s.incomplete.map(v => ({ theme: s.theme, state: s.state, ...v })));
const measurements = axeStates.flatMap(s => s.colorContrastIncompleteMeasurements || []);

const wcagViolations = violations.filter(isWcagAA);
const bpViolations = violations.filter(v => !isWcagAA(v));
const unexpectedBP = bpViolations.filter(v => !BEST_PRACTICE_ONLY_RULE_IDS.includes(v.id));

const ccIncompleteNodes = incomplete.filter(v => v.id === 'color-contrast').reduce((a, v) => a + v.nodes.length, 0);
const resolutions = measurements.map(m => {
  const c = m.computed || {};
  const required = c.large ? WCAG.TEXT_LARGE : WCAG.TEXT_NORMAL;
  const result = (!m.computed || m.computed.error || m.computed.ratio == null)
    ? RESULT.UNRESOLVED : (m.computed.ratio + 1e-9 >= required ? RESULT.PASS : RESULT.FAIL);
  return { theme: m.theme, state: m.state, target: m.target, text: c.text, html: m.html,
    axeMessage: m.axeMessage, axeData: m.axeData,
    whyAxeCouldNotDecide: c.overBackgroundImage
      ? 'the element is layered over a background painted by an SVG/CSS image, which axe cannot sample, so axe returns `incomplete`'
      : 'the element is layered over a translucent surface stack, which axe cannot flatten, so axe returns `incomplete`',
    resolvedBy: 'composited background computed from the element ancestry by the oracle probe',
    fg: c.fg, bg: c.bg, bgChain: c.bgChain, fontPx: c.fontPx, weight: c.weight, large: c.large,
    expected: '>= ' + required.toFixed(1) + ':1', actual: c.ratio != null ? c.ratio.toFixed(2) + ':1' : 'NOT COMPUTED',
    result };
});
const ccUnresolved = resolutions.filter(r => r.result === RESULT.UNRESOLVED).length
  + resolutions.filter(r => r.result === RESULT.FAIL).length
  + (ccIncompleteNodes - resolutions.length);
const nonCcIncompleteNodes = incomplete.filter(v => v.id !== 'color-contrast').reduce((a, v) => a + v.nodes.length, 0);

const axe = {
  wcagAA: { ruleCount: wcagViolations.length, nodeCount: wcagViolations.reduce((a, v) => a + v.nodes.length, 0),
    rules: [...new Set(wcagViolations.map(v => v.id))], detail: wcagViolations },
  bestPracticeOnly: { ruleCount: bpViolations.length, nodeCount: bpViolations.reduce((a, v) => a + v.nodes.length, 0),
    rules: [...new Set(bpViolations.map(v => v.id))],
    notes: Object.fromEntries([...new Set(bpViolations.map(v => v.id))].map(id => [id, BEST_PRACTICE_NOTE[id] || 'best-practice only'])),
    unexpectedRules: [...new Set(unexpectedBP.map(v => v.id))], detail: bpViolations },
  incomplete: { totalNodes: incomplete.reduce((a, v) => a + v.nodes.length, 0),
    colorContrastNodes: ccIncompleteNodes, otherNodes: nonCcIncompleteNodes,
    colorContrastResolvedPass: resolutions.filter(r => r.result === RESULT.PASS).length,
    colorContrastResolvedFail: resolutions.filter(r => r.result === RESULT.FAIL).length,
    colorContrastUnresolved: ccUnresolved, resolutions, detail: incomplete }
};
if (axe.wcagAA.nodeCount) blockers.push('axe-wcag-aa-violations');
if (ccUnresolved) blockers.push('axe-incomplete-color-contrast');
if (nonCcIncompleteNodes) blockers.push('axe-incomplete-other');
if (unexpectedBP.length) blockers.push('axe-unexpected-best-practice-rule');

/* ------------------------- keyboard + hygiene --------------------------- */
const keyboard = all('keyboard');
const keyboardOk = keyboard.length > 0 && keyboard.every(k => k.tabOrderMatchesDom && k.allReached && k.focusTrapAllInside
  && k.escapeDismissed && k.focusReturnedToTrigger && k.accessibleNamesStable && k.undersizedTargets.length === 0
  && k.reducedMotion.prefersReduce && k.reducedMotion.motionBase === '0s' && k.reducedMotion.motionFast === '0s');
if (!keyboardOk) blockers.push('keyboard');

/* -------- console / network hygiene, isolated by measurement phase ------- */
const phases = {};
for (const { data } of shards) for (const b of Object.values(data.consoleByPhase || {})) {
  const t = phases[b.phase] = phases[b.phase] || { phase: b.phase, errors: 0, warnings: 0, pageErrors: 0,
    failedRequests: 0, failedRequestDetail: [], consoleDetail: [] };
  t.errors += b.errors; t.warnings += b.warnings; t.pageErrors += b.pageErrors; t.failedRequests += b.failedRequests;
  t.failedRequestDetail.push(...(b.failedRequestDetail || [])); t.consoleDetail.push(...(b.consoleDetail || []));
}
/* axe-core XHR-preloads the document stylesheets when it boots; under file://
   that is blocked by CORS. The noise belongs to the TOOL, not to the package,
   and it is proved to be tool noise by the axe-free `hygiene` phase below —
   it is isolated here, never silently dropped. */
const AXE_NOISE = /Access to XMLHttpRequest|net::ERR_FAILED|Couldn't load preload assets/i;
const isAxeNoise = (rec) => rec.phase === 'contrast+axe' &&
  (AXE_NOISE.test(rec.text || '') || (rec.resourceType === 'xhr' && /\.css$/i.test(rec.url || '')));
const hygienePhase = phases['hygiene'];
const axePhase = phases['contrast+axe'];
const otherPhases = Object.values(phases).filter(p => p.phase !== 'hygiene' && p.phase !== 'contrast+axe');
const axeResidual = axePhase
  ? { console: axePhase.consoleDetail.filter(r => !isAxeNoise(r)), requests: axePhase.failedRequestDetail.filter(r => !isAxeNoise(r)) }
  : { console: [], requests: [] };
const otherResidual = { console: otherPhases.flatMap(p => p.consoleDetail), requests: otherPhases.flatMap(p => p.failedRequestDetail) };

const storage = all('storage');
const hygiene = {
  authoritativeAxeFreePass: hygienePhase
    ? { consoleErrors: hygienePhase.errors, consoleWarnings: hygienePhase.warnings, pageErrors: hygienePhase.pageErrors,
        failedRequests: hygienePhase.failedRequests, detail: hygienePhase.consoleDetail.concat(hygienePhase.failedRequestDetail) }
    : null,
  axeInstrumentedPass: axePhase
    ? { consoleErrors: axePhase.errors, consoleWarnings: axePhase.warnings, pageErrors: axePhase.pageErrors,
        failedRequests: axePhase.failedRequests,
        attributableToAxeCorePreload: axePhase.consoleDetail.filter(isAxeNoise).length + axePhase.failedRequestDetail.filter(isAxeNoise).length,
        residualNotAttributableToAxe: axeResidual.console.length + axeResidual.requests.length,
        residualDetail: axeResidual.console.concat(axeResidual.requests),
        isolationProof: 'the same 10 states x 2 themes were navigated again in the axe-free `hygiene` phase; every console message and failed request disappears when axe-core is not injected, which is what attributes them to the tool',
        failedRequestUrls: [...new Set(axePhase.failedRequestDetail.map(r => r.url))] }
    : null,
  otherPhases: { phases: otherPhases.map(p => p.phase), consoleErrors: otherPhases.reduce((a, p) => a + p.errors, 0),
    consoleWarnings: otherPhases.reduce((a, p) => a + p.warnings, 0), pageErrors: otherPhases.reduce((a, p) => a + p.pageErrors, 0),
    failedRequests: otherPhases.reduce((a, p) => a + p.failedRequests, 0), detail: otherResidual.console.concat(otherResidual.requests) },
  maxLocalStorageKeys: Math.max(0, ...storage.map(s => s.localStorage)),
  maxSessionStorageKeys: Math.max(0, ...storage.map(s => s.sessionStorage)),
  maxDocumentCookies: Math.max(0, ...storage.map(s => s.documentCookie)),
  maxContextCookies: Math.max(0, ...storage.map(s => s.contextCookies)),
  reflow200Percent: all('reflow') || []
};
if (!hygienePhase) blockers.push('hygiene-phase-not-run');
else if (hygienePhase.errors || hygienePhase.warnings || hygienePhase.pageErrors || hygienePhase.failedRequests) blockers.push('console-or-network');
if (axeResidual.console.length || axeResidual.requests.length) blockers.push('console-or-network');
if (otherResidual.console.length || otherResidual.requests.length) blockers.push('console-or-network');
if (hygiene.maxLocalStorageKeys || hygiene.maxSessionStorageKeys || hygiene.maxDocumentCookies || hygiene.maxContextCookies) blockers.push('storage-or-cookies');
const reflowRows = hygiene.reflow200Percent;
if (!reflowRows.length || reflowRows.some(r => r.horizontalScroll || !r.dockVisible)) blockers.push('reflow-200-percent');

/* readiness: every room state advertised readiness through data-live-room-ready */
const readiness = Object.assign({}, ...shards.map(s => s.data.raw.readiness));
const roomCells = Object.entries(readiness).filter(([, v]) => v.isRoomFamily);
const readinessOk = roomCells.length > 0 && roomCells.every(([, v]) => v.dataLiveRoomReady === 'true');
if (!readinessOk) blockers.push('room-readiness');

/* -------------------------------- output -------------------------------- */
const verdict = { code: blockers.length ? 1 : 0, blockedBy: [...new Set(blockers)] };
const report = {
  schema: 'legalsaathi.option-c2.a11y-oracle-report/1',
  generatedAt: new Date().toISOString(),
  shards: shards.map((s, i) => ({ file: s.file.split('/').pop(), themes: s.data.shard.themes, states: s.data.shard.states.length, phases: s.data.shard.phases, provenanceValid: provenanceChecks[i].valid })),
  provenance: { commit: commits[0], allShardsAgreeOnCommit: commits.length === 1, checks: provenanceChecks,
    valid: provenanceValid, environment: provenances[0] },
  coverage,
  rollups,
  contrast: { textPairs: textRows.length, nonTextPairs: nonTextRows.length, focusIndicatorRows: focusRows.length,
    text: textRows, nonText: nonTextRows, focus: focusRows },
  axe, keyboard, hygiene, storage, readiness,
  screenReader: 'NOT RUN — no VoiceOver/NVDA/JAWS was executed in this environment. No manual screen-reader PASS is claimed.',
  verdict
};
writeFileSync(join(OUT_DIR, 'a11y_oracle__' + TAG + '.json'), JSON.stringify(report, null, 2) + '\n');

const L = [];
const p = provenances[0];
L.push('Option C2 accessibility oracle report — ' + TAG);
L.push('commit (runtime git rev-parse HEAD) : ' + commits[0]);
L.push('package path (repo-relative)        : ' + p.packagePathRelativeToRepo);
L.push('worktree clean                      : ' + p.workingTreeClean);
L.push('chromium / playwright / axe-core    : ' + p.browser.version + ' / ' + p.browser.playwright + ' / ' + p.axe.version);
L.push('browser executable                  : ' + p.browser.executablePath);
L.push('node / os                           : ' + p.node + ' / ' + p.os.type + ' ' + p.os.release + ' ' + p.os.arch);
L.push('viewport                            : ' + p.viewport.width + 'x' + p.viewport.height);
L.push('provenance valid                    : ' + provenanceValid);
L.push('coverage complete                   : ' + coverage.complete + ' (' + coverage.contrastCovered + '/' + coverage.requiredCells + ' theme x state cells)');
L.push('');
L.push('TEXT      total ' + rollups.text.total + '  PASS ' + rollups.text.pass + '  FAIL ' + rollups.text.fail);
L.push('NON-TEXT  total ' + rollups.nonText.total + '  PASS ' + rollups.nonText.pass + '  FAIL ' + rollups.nonText.fail +
  '  NOT_APPLICABLE ' + rollups.nonText.notApplicable + '  ADJUDICATION_INVALID ' + rollups.nonText.adjudicationInvalid);
L.push('FOCUS     total ' + rollups.focus.total + '  PASS ' + rollups.focus.pass + '  FAIL ' + rollups.focus.fail);
L.push('AXE       WCAG A/AA violation nodes ' + axe.wcagAA.nodeCount + ' [' + axe.wcagAA.rules.join(',') + ']');
L.push('AXE       best-practice-only nodes  ' + axe.bestPracticeOnly.nodeCount + ' [' + axe.bestPracticeOnly.rules.join(',') + '] (documented, NOT A/AA)');
L.push('AXE       colour-contrast incomplete nodes ' + axe.incomplete.colorContrastNodes +
  ' -> resolved PASS ' + axe.incomplete.colorContrastResolvedPass +
  ', resolved FAIL ' + axe.incomplete.colorContrastResolvedFail +
  ', UNRESOLVED ' + axe.incomplete.colorContrastUnresolved);
L.push('AXE       other incomplete nodes    ' + axe.incomplete.otherNodes);
const hz = hygiene.authoritativeAxeFreePass || { consoleErrors: 'n/a', consoleWarnings: 'n/a', pageErrors: 'n/a', failedRequests: 'n/a' };
const ha = hygiene.axeInstrumentedPass || { consoleErrors: 0, consoleWarnings: 0, failedRequests: 0, attributableToAxeCorePreload: 0, residualNotAttributableToAxe: 0 };
L.push('HYGIENE   axe-free pass (authoritative): console errors ' + hz.consoleErrors + ', warnings ' + hz.consoleWarnings +
  ', page errors ' + hz.pageErrors + ', failed requests ' + hz.failedRequests);
L.push('HYGIENE   axe-instrumented pass: console ' + (ha.consoleErrors + ha.consoleWarnings) + ' + failed requests ' + ha.failedRequests +
  ' -> attributable to axe-core file:// preload ' + ha.attributableToAxeCorePreload + ', residual ' + ha.residualNotAttributableToAxe);
L.push('HYGIENE   other phases (focus/keyboard): console errors ' + hygiene.otherPhases.consoleErrors +
  ', warnings ' + hygiene.otherPhases.consoleWarnings + ', page errors ' + hygiene.otherPhases.pageErrors +
  ', failed requests ' + hygiene.otherPhases.failedRequests);
L.push('HYGIENE   200% reflow: ' + reflowRows.map(r => r.theme + ' hScroll=' + r.horizontalScroll + ' dockVisible=' + r.dockVisible).join(' | '));
L.push('HYGIENE   localStorage ' + hygiene.maxLocalStorageKeys + ', sessionStorage ' + hygiene.maxSessionStorageKeys +
  ', document.cookie ' + hygiene.maxDocumentCookies + ', context cookies ' + hygiene.maxContextCookies);
L.push('');
L.push('--- NON-TEXT ROWS (WCAG 1.4.11) ---');
L.push(['theme', 'facet', 'selector', 'accessible name', 'fg', 'bg', 'actual', 'expected', 'identifying feature', 'feature ratio', 'adjudication', 'result'].join(' | '));
for (const r of nonTextRows) L.push([r.theme, r.facet, r.selector, (r.accessibleName || '').slice(0, 34), r.fg, r.bg,
  r.actual, r.expected, r.identifying ? r.identifying.feature : '-', r.substituteRatio != null ? r.substituteRatio.toFixed(2) + ':1' : '-',
  (r.adjudication && r.adjudication.status) || 'NONE', r.result].join(' | '));
L.push('');
L.push('--- FOCUS INDICATOR ROWS ---');
L.push(['theme', 'state', 'selector', 'ring', 'outer adjacent', 'inner adjacent', 'outer', 'inner', 'px', 'result'].join(' | '));
for (const r of focusRows) L.push([r.theme, r.state, r.selector, r.ringColor, r.outerAdjacent, r.innerAdjacent,
  r.ratioOuter, r.ratioInner, r.thicknessPx, r.result + (r.problems.length ? ' :: ' + r.problems.join('; ') : '')].join(' | '));
L.push('');
L.push('--- AXE COLOUR-CONTRAST INCOMPLETE RESOLUTIONS ---');
L.push(['theme', 'state', 'target', 'text', 'fg', 'bg', 'actual', 'expected', 'result'].join(' | '));
for (const r of resolutions) L.push([r.theme, r.state, r.target, (r.text || '').slice(0, 30), r.fg, r.bg, r.actual, r.expected, r.result].join(' | '));
L.push('');
L.push('--- TEXT ROWS (worst first) ---');
L.push(['theme', 'fg', 'bg', 'actual', 'expected', 'result', 'sample'].join(' | '));
for (const r of textRows) L.push([r.theme, r.fg, r.bg, r.actual, r.expected, r.result, (r.samples[0] || '').slice(0, 60)].join(' | '));
L.push('');
L.push('--- KEYBOARD / MOTION ---');
for (const k of keyboard) L.push([k.theme, 'tabOrderMatchesDom=' + k.tabOrderMatchesDom, 'allReached=' + k.allReached,
  'focusTrap=' + k.focusTrapAllInside, 'escape=' + k.escapeDismissed, 'focusReturn=' + k.focusReturnedToTrigger,
  'namesStable=' + k.accessibleNamesStable, 'undersizedTargets=' + k.undersizedTargets.length,
  'reducedMotion=' + k.reducedMotion.prefersReduce + '/' + k.reducedMotion.motionBase + '/' + k.reducedMotion.motionFast].join(' | '));
L.push('');
L.push('VERDICT exit=' + verdict.code + (verdict.blockedBy.length ? '  BLOCKED BY: ' + verdict.blockedBy.join(', ') : '  ALL GATES PASS'));
writeFileSync(join(OUT_DIR, 'a11y_oracle__' + TAG + '.txt'), L.join('\n') + '\n');
console.log(L.join('\n'));
process.exit(verdict.code);
