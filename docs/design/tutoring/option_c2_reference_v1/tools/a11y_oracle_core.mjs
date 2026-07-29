/* Option C2 accessibility ORACLE — pure core (no browser, no network).
   Everything in this file is deterministic and unit-testable with plain node.

   Design rules this module enforces (they are the reason the previous
   evidence run was rejected by Independent QA):

   1. Provenance is derived at RUNTIME. A record whose commit/package path was
      hard-coded (or which points outside the checked-out worktree) is INVALID
      evidence and must fail loudly — see validateProvenance().
   2. A row is PASS only when it was actually measured and actually met its
      threshold. `incomplete`, `not-applicable` and `reviewed` are NOT PASS and
      are counted in their own buckets.
   3. A non-text row may only be adjudicated NOT_APPLICABLE when the
      adjudication names the visible feature that identifies the control AND
      that substitute feature is itself measured and passes 3:1. An
      unsubstantiated NOT_APPLICABLE is reported as ADJUDICATION_INVALID, which
      is a failure.
   4. Every row carries expected / actual / result and a stable selector.
*/

export const WCAG = {
  TEXT_NORMAL: 4.5,
  TEXT_LARGE: 3.0,
  NON_TEXT: 3.0,
  FOCUS_INDICATOR: 3.0,
  FOCUS_MIN_THICKNESS_PX: 2.0
};

export const RESULT = {
  PASS: 'PASS',
  FAIL: 'FAIL',
  NOT_APPLICABLE: 'NOT_APPLICABLE',
  ADJUDICATION_INVALID: 'ADJUDICATION_INVALID',
  UNRESOLVED: 'UNRESOLVED'
};

/* ------------------------------ colour maths ----------------------------- */

export function parseColor(c) {
  if (c == null) return null;
  const s = String(c).trim();
  let m = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (m) {
    let h = m[1];
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 };
  }
  m = s.match(/rgba?\(([^)]+)\)/i);
  if (m) {
    const p = m[1].split(/[,\s\/]+/).filter(Boolean).map(Number);
    if (p.length < 3 || p.slice(0, 3).some(Number.isNaN)) return null;
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  }
  return null;
}

export function composite(fg, bg) {
  const a = fg.a == null ? 1 : fg.a;
  return { r: fg.r * a + bg.r * (1 - a), g: fg.g * a + bg.g * (1 - a), b: fg.b * a + bg.b * (1 - a), a: 1 };
}

export function relativeLuminance(c) {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
}

export function contrastRatio(a, b) {
  const ca = typeof a === 'string' ? parseColor(a) : a;
  const cb = typeof b === 'string' ? parseColor(b) : b;
  if (!ca || !cb) throw new Error('contrastRatio: unparsable colour ' + JSON.stringify([a, b]));
  const l1 = relativeLuminance(ca), l2 = relativeLuminance(cb);
  return round2((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05));
}

export function toHex(c) {
  return '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
}

export const round2 = (n) => Math.round(n * 100) / 100;

/* `>=` with a tolerance far smaller than the reporting precision, so a value
   that only reaches the threshold after rounding is NOT accepted. */
function meets(actual, required) { return actual + 1e-9 >= required; }

/* ----------------------------- row evaluation ---------------------------- */

/** TEXT row (WCAG 1.4.3). Large text = >=24px, or >=18.66px and weight >=700. */
export function evaluateTextRow(row) {
  const large = row.large != null
    ? !!row.large
    : (row.fontPx >= 24 || (row.fontPx >= 18.66 && (row.weight || 400) >= 700));
  const required = large ? WCAG.TEXT_LARGE : WCAG.TEXT_NORMAL;
  const actual = row.ratio != null ? row.ratio : contrastRatio(row.fg, row.bg);
  return {
    ...row,
    kind: 'text',
    large,
    sc: large ? '1.4.3 Contrast (Minimum) — large text' : '1.4.3 Contrast (Minimum)',
    expected: '>= ' + required.toFixed(1) + ':1',
    actual: actual.toFixed(2) + ':1',
    ratio: actual,
    required,
    result: meets(actual, required) ? RESULT.PASS : RESULT.FAIL
  };
}

/**
 * NON-TEXT row (WCAG 1.4.11).
 * `adjudication` is REQUIRED for every non-text row and must be one of:
 *   { status:'APPLICABLE', reason }
 *   { status:'NOT_APPLICABLE', reason, identifiedBy:{feature, selector},
 *     substitute:{ fg, bg, ratio } }
 * A NOT_APPLICABLE without a passing measured substitute is ADJUDICATION_INVALID.
 */
export function evaluateNonTextRow(row) {
  const actual = row.ratio != null ? row.ratio : contrastRatio(row.fg, row.bg);
  const adj = row.adjudication;
  const base = {
    ...row,
    sc: '1.4.11 Non-text Contrast',
    expected: '>= ' + WCAG.NON_TEXT.toFixed(1) + ':1',
    actual: actual.toFixed(2) + ':1',
    ratio: actual,
    required: WCAG.NON_TEXT
  };
  if (!adj || !adj.status) {
    return { ...base, result: RESULT.ADJUDICATION_INVALID, adjudicationError: 'no adjudication recorded for this non-text row' };
  }
  if (adj.status === 'APPLICABLE') {
    if (!adj.reason) return { ...base, result: RESULT.ADJUDICATION_INVALID, adjudicationError: 'APPLICABLE without reason' };
    return { ...base, result: meets(actual, WCAG.NON_TEXT) ? RESULT.PASS : RESULT.FAIL };
  }
  if (adj.status === 'NOT_APPLICABLE') {
    if (!adj.reason) return { ...base, result: RESULT.ADJUDICATION_INVALID, adjudicationError: 'NOT_APPLICABLE without reason' };
    if (!adj.identifiedBy || !adj.identifiedBy.feature || !adj.identifiedBy.selector) {
      return { ...base, result: RESULT.ADJUDICATION_INVALID, adjudicationError: 'NOT_APPLICABLE without a named identifying feature' };
    }
    const sub = adj.substitute;
    if (!sub || sub.ratio == null) {
      return { ...base, result: RESULT.ADJUDICATION_INVALID, adjudicationError: 'NOT_APPLICABLE without a measured substitute (the identifying icon/label was never measured)' };
    }
    if (!meets(sub.ratio, WCAG.NON_TEXT)) {
      return {
        ...base,
        result: RESULT.FAIL,
        adjudicationError: 'the named identifying feature itself fails 3:1 (' + sub.ratio.toFixed(2) + ':1), so the boundary/fill cannot be waived',
        substituteRatio: sub.ratio
      };
    }
    return { ...base, result: RESULT.NOT_APPLICABLE, substituteRatio: sub.ratio };
  }
  return { ...base, result: RESULT.ADJUDICATION_INVALID, adjudicationError: 'unknown adjudication status ' + adj.status };
}

/**
 * FOCUS INDICATOR row (WCAG 1.4.11 applied to the keyboard focus indicator).
 * There is no product escape hatch: a visible keyboard focus indicator must
 * independently reach 3:1 against every adjacent colour and be >= 2px thick.
 */
export function evaluateFocusRow(row) {
  const ratios = [];
  if (row.ratioOuter != null) ratios.push(row.ratioOuter);
  if (row.ratioInner != null) ratios.push(row.ratioInner);
  if (!ratios.length && row.ratio != null) ratios.push(row.ratio);
  const worst = ratios.length ? Math.min(...ratios) : null;
  const thickness = row.thicknessPx == null ? 0 : row.thicknessPx;
  const problems = [];
  if (!row.hasIndicator) problems.push('no visible focus indicator (no outline and no box-shadow)');
  if (worst == null) problems.push('focus indicator contrast was not measured');
  else if (!meets(worst, WCAG.FOCUS_INDICATOR)) problems.push('focus indicator contrast ' + worst.toFixed(2) + ':1 < 3.00:1');
  if (row.hasIndicator && thickness < WCAG.FOCUS_MIN_THICKNESS_PX) problems.push('focus indicator thickness ' + thickness + 'px < 2px');
  return {
    ...row,
    kind: 'focus-indicator',
    sc: '1.4.11 Non-text Contrast (focus indicator) + 2.4.7 Focus Visible',
    expected: '>= ' + WCAG.FOCUS_INDICATOR.toFixed(1) + ':1 against every adjacent colour, >= 2px thick',
    actual: (worst == null ? 'not measured' : worst.toFixed(2) + ':1') + ', ' + thickness + 'px',
    ratio: worst,
    required: WCAG.FOCUS_INDICATOR,
    problems,
    result: problems.length ? RESULT.FAIL : RESULT.PASS
  };
}

/* ------------------------------- provenance ------------------------------ */

/**
 * Evidence provenance. Rejects the exact defect class Independent QA found:
 * a hard-coded commit that does not match the tree that was actually measured,
 * and an absolute out-of-tree package path baked into the tool.
 */
export function validateProvenance(p) {
  const errors = [];
  const sha = /^[0-9a-f]{40}$/;
  if (!p || typeof p !== 'object') return { valid: false, errors: ['no provenance record'] };
  if (!sha.test(String(p.commit || ''))) errors.push('commit is not a full 40-character sha: ' + p.commit);
  if (!sha.test(String(p.runtimeHeadCommit || ''))) errors.push('runtimeHeadCommit is not a full 40-character sha: ' + p.runtimeHeadCommit);
  if (p.commit !== p.runtimeHeadCommit) {
    errors.push('recorded commit ' + p.commit + ' does not equal the runtime `git rev-parse HEAD` of the measured tree ' + p.runtimeHeadCommit + ' (stale / hard-coded evidence label)');
  }
  if (p.commitSource !== 'git rev-parse HEAD (runtime)') {
    errors.push('commit was not derived at runtime (commitSource=' + p.commitSource + ')');
  }
  const rel = String(p.packagePathRelativeToRepo || '');
  if (!rel) errors.push('packagePathRelativeToRepo is missing');
  if (rel.startsWith('/') || /^[a-z]:\\/i.test(rel)) errors.push('package path is absolute, not repository-relative: ' + rel);
  if (rel.split('/').includes('..')) errors.push('package path escapes the repository root: ' + rel);
  if (rel && rel !== 'docs/design/tutoring/option_c2_reference_v1') {
    errors.push('package path does not resolve to the Option C2 reference package: ' + rel);
  }
  if (p.workingTreeClean === false) errors.push('the measured worktree was dirty; evidence cannot be attributed to a commit');
  if (!p.browser || !p.browser.version) errors.push('browser version not recorded');
  if (!p.browser || !p.browser.executablePath) errors.push('browser executable not recorded');
  if (!p.os || !p.os.platform) errors.push('OS not recorded');
  if (!p.node) errors.push('node version not recorded');
  return { valid: errors.length === 0, errors };
}

/* -------------------------------- rollup --------------------------------- */

export function rollup(rows) {
  const t = { total: rows.length, pass: 0, fail: 0, notApplicable: 0, adjudicationInvalid: 0, unresolved: 0 };
  for (const r of rows) {
    if (r.result === RESULT.PASS) t.pass++;
    else if (r.result === RESULT.FAIL) t.fail++;
    else if (r.result === RESULT.NOT_APPLICABLE) t.notApplicable++;
    else if (r.result === RESULT.ADJUDICATION_INVALID) t.adjudicationInvalid++;
    else t.unresolved++;
  }
  /* NOT_APPLICABLE / UNRESOLVED are never folded into `pass`. */
  t.blocking = t.fail + t.adjudicationInvalid + t.unresolved;
  return t;
}

export function exitCodeFor(report) {
  const b = [];
  if (!report.provenance || !report.provenance.valid) b.push('provenance');
  if (report.rollups.text.blocking) b.push('text-contrast');
  if (report.rollups.nonText.blocking) b.push('non-text-contrast');
  if (report.rollups.focus.blocking) b.push('focus-indicator');
  if (report.axe && report.axe.violationNodeCountWcagAA) b.push('axe-wcag-aa-violations');
  if (report.axe && report.axe.unresolvedIncompleteColorContrastNodes) b.push('axe-incomplete-color-contrast');
  return { code: b.length ? 1 : 0, blockedBy: b };
}
