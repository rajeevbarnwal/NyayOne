/* Option C2 — FAIL-CLOSED banner CONTENT-geometry oracle.

   Why this file exists
   -------------------
   The S-35 adverse-state matrix asserted only CONTAINER geometry (root height,
   no scroll, three grid rows, dock visible, target size, control overlap). That
   is why it could report 72/72 PASS while its own committed screenshot showed a
   315x315 warning icon and a 0px-wide message column (defect D-1). Container
   geometry is not what a user reads. This oracle asserts the geometry of the
   CONTENT inside every provider-error / reconnect banner.

   Fail-closed contract
   --------------------
   Absence of evidence is FAILURE, never a pass:
     * a missing banner in a state whose model declares one            -> FAIL
     * a missing icon, title, detail or message column                 -> FAIL
     * a null / errored probe                                          -> FAIL
     * a banner-bearing state that is not covered by this oracle       -> FAIL
     * `data-live-room-ready="true"` on its own                        -> NEVER a pass
   Every rule defaults to false and must be positively proven true.

   The nine rules (per banner state, per viewport x theme pair)
   ------------------------------------------------------------
     g1 status/warning icon width AND height each within 18..24 px
     g2 title and detail each have non-zero rendered width and are visible
     g3 message column width >= max(120px, 40% of the banner width)
     g4 title and detail rects stay within the banner rect
     g5 icon rect and message-column/title/detail rects do not overlap
     g6 scrollWidth <= clientWidth for the title/detail container (and for the
        title and the detail themselves) — no horizontally overflowing text
     g7 no text clipped by an overflow:hidden/clip/auto/scroll ancestor
     g8 the banner stays inside the mentor tile AND inside the stage
     g9 readiness is awaited, but `data-live-room-ready="true"` never counts as a
        visual pass by itself: g9 is true only when readiness is true AND g1..g8
        all hold independently.
*/

export const RULE_IDS = [
  'g1_iconBox', 'g2_textRendered', 'g3_textColumnWidth', 'g4_textWithinBanner',
  'g5_noIconTextOverlap', 'g6_noHorizontalOverflow', 'g7_noClippedText',
  'g8_bannerWithinTile', 'g9_readinessNotSufficient'
];

export const RULE_TEXT = {
  g1_iconBox: 'status/warning icon width AND height each within 18-24px',
  g2_textRendered: 'title and detail each have non-zero rendered width and are visible',
  g3_textColumnWidth: 'message column >= max(120px, 40% of banner width)',
  g4_textWithinBanner: 'title and detail rects stay within the banner rect',
  g5_noIconTextOverlap: 'icon rect and text rects do not overlap',
  g6_noHorizontalOverflow: 'scrollWidth <= clientWidth for the title/detail container',
  g7_noClippedText: 'no text clipped by an overflow:hidden ancestor',
  g8_bannerWithinTile: 'banner stays inside the mentor tile / stage',
  g9_readinessNotSufficient: 'readiness awaited; data-live-room-ready alone is never a visual pass'
};

/* Icon box budget. `.ic` is a 20x20 token; +-2px absorbs sub-pixel rounding and
   nothing else. A 315px icon, a 26px icon and a 0px icon all fail. */
export const ICON_MIN = 18;
export const ICON_MAX = 24;
export const COL_MIN_PX = 120;
export const COL_MIN_FRACTION = 0.40;
const TOL = 1;              /* +-1px sub-pixel tolerance, matching the addendum */

/* ------------------------------------------------------------------ *
 * In-page probe. Serialised into Chromium by the caller. Pure reads.
 * ------------------------------------------------------------------ */
export const BANNER_PROBE = function () {
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: +r.x.toFixed(2), y: +r.y.toFixed(2), w: +r.width.toFixed(2), h: +r.height.toFixed(2),
             left: +r.left.toFixed(2), top: +r.top.toFixed(2), right: +r.right.toFixed(2), bottom: +r.bottom.toFixed(2) };
  };
  const visible = (el) => {
    if (!el) return false;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity) > 0 &&
           r.width > 0 && r.height > 0;
  };
  const box = (el) => el ? { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,
                             scrollHeight: el.scrollHeight, clientHeight: el.clientHeight } : null;

  const room   = document.querySelector('.route.room') || document.querySelector('.live');
  const tile   = document.querySelector('[data-testid=remote-tile]');
  const stage  = document.querySelector('.stage');
  const banner = document.querySelector('[data-testid=room-banner]');

  const readyAttr = room ? (room.getAttribute('data-live-room-ready') || null) : null;
  if (!room)   return { fatal: 'LIVE_ROOT_NOT_FOUND', readyAttr };
  if (!banner) return { fatal: 'BANNER_NOT_FOUND', readyAttr, hasTile: !!tile };

  const icon   = banner.querySelector(':scope > svg');
  const column = banner.querySelector(':scope > div');
  const title  = banner.querySelector('.bt');
  const detail = banner.querySelector('.bd2');

  /* every clipping ancestor between the text and the document */
  const clippers = [];
  for (const start of [title, detail]) {
    if (!start) continue;
    let n = start.parentElement;
    while (n) {
      const cs = getComputedStyle(n);
      const ox = cs.overflowX, oy = cs.overflowY;
      const clips = /hidden|clip|auto|scroll/.test(ox) || /hidden|clip|auto|scroll/.test(oy) ||
                    (cs.contain || '').indexOf('strict') >= 0 || (cs.contain || '').indexOf('paint') >= 0;
      if (clips) {
        const r = n.getBoundingClientRect();
        const bw = (s) => parseFloat(getComputedStyle(n).getPropertyValue(s)) || 0;
        clippers.push({
          who: start === title ? 'title' : 'detail',
          sel: (n.getAttribute('data-testid') || n.className || n.tagName).toString().slice(0, 40),
          overflowX: ox, overflowY: oy,
          clientRect: { left: +(r.left + bw('border-left-width')).toFixed(2), top: +(r.top + bw('border-top-width')).toFixed(2),
                        right: +(r.right - bw('border-right-width')).toFixed(2), bottom: +(r.bottom - bw('border-bottom-width')).toFixed(2) },
          textRect: rect(start)
        });
      }
      n = n.parentElement;
    }
  }

  return {
    readyAttr,
    icon: rect(icon), iconPresent: !!icon, iconVisible: visible(icon),
    iconClass: icon ? (icon.getAttribute('class') || '') : null,
    banner: rect(banner), bannerBox: box(banner),
    column: rect(column), columnPresent: !!column, columnBox: box(column),
    title: rect(title), titlePresent: !!title, titleVisible: visible(title), titleBox: box(title),
    titleText: title ? (title.textContent || '').trim() : null,
    detail: rect(detail), detailPresent: !!detail, detailVisible: visible(detail), detailBox: box(detail),
    detailText: detail ? (detail.textContent || '').trim() : null,
    tile: rect(tile), stage: rect(stage),
    clippers
  };
};

/* Enumerate every room state whose model declares a banner. Used for the
   coverage assertion so a NEW banner state cannot silently escape the oracle. */
export const BANNER_STATE_DISCOVERY = function () {
  const M = window.C2States;
  if (!M || !Array.isArray(M.STATES)) return { fatal: 'STATE_MODEL_NOT_FOUND' };
  return {
    states: M.STATES
      .filter(s => s.layoutFamily === 'room' && s.delta && Array.isArray(s.delta.banner))
      .map(s => ({ id: s.id, tone: s.delta.banner[0], title: s.delta.banner[1], detail: s.delta.banner[2] }))
  };
};

/* ------------------------------------------------------------------ *
 * Pure evaluation. No DOM, no browser — unit-testable.
 * ------------------------------------------------------------------ */
const overlap = (a, b) => {
  if (!a || !b) return null;
  const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return (x > TOL && y > TOL) ? { x: +x.toFixed(2), y: +y.toFixed(2) } : null;
};
const within = (inner, outer) => !!(inner && outer) &&
  inner.left >= outer.left - TOL && inner.top >= outer.top - TOL &&
  inner.right <= outer.right + TOL && inner.bottom <= outer.bottom + TOL;

export function evaluateBannerGeometry(probe, meta) {
  const m = meta || {};
  const rules = {};
  const failures = [];
  RULE_IDS.forEach(id => { rules[id] = false; });          /* fail-closed default */

  const fail = (id, why) => { rules[id] = false; failures.push(id + ': ' + why); };

  if (!probe || probe.fatal) {
    RULE_IDS.forEach(id => failures.push(id + ': ' + ((probe && probe.fatal) || 'NO_PROBE')));
    return { pass: false, rules, failures, measured: null,
             fatal: (probe && probe.fatal) || 'NO_PROBE', meta: m };
  }

  const ic = probe.icon, bn = probe.banner, col = probe.column, ti = probe.title, de = probe.detail;

  /* g1 — icon box */
  if (!probe.iconPresent || !ic) fail('g1_iconBox', 'status icon element missing');
  else if (!probe.iconVisible) fail('g1_iconBox', 'status icon not visible');
  else if (ic.w < ICON_MIN || ic.w > ICON_MAX || ic.h < ICON_MIN || ic.h > ICON_MAX)
    fail('g1_iconBox', 'icon ' + ic.w + 'x' + ic.h + ' outside ' + ICON_MIN + '-' + ICON_MAX + 'px');
  else rules.g1_iconBox = true;

  /* g2 — title and detail actually rendered */
  const g2problems = [];
  if (!probe.titlePresent || !ti) g2problems.push('title element missing');
  else { if (!(ti.w > 0)) g2problems.push('title rendered width ' + ti.w); if (!probe.titleVisible) g2problems.push('title not visible'); }
  if (!probe.detailPresent || !de) g2problems.push('detail element missing');
  else { if (!(de.w > 0)) g2problems.push('detail rendered width ' + de.w); if (!probe.detailVisible) g2problems.push('detail not visible'); }
  if (g2problems.length) fail('g2_textRendered', g2problems.join('; ')); else rules.g2_textRendered = true;

  /* g3 — message column width budget */
  const required = bn ? Math.max(COL_MIN_PX, COL_MIN_FRACTION * bn.w) : Infinity;
  if (!probe.columnPresent || !col) fail('g3_textColumnWidth', 'message column element missing');
  else if (!bn) fail('g3_textColumnWidth', 'banner rect missing');
  else if (col.w + TOL < required)
    fail('g3_textColumnWidth', 'column ' + col.w + 'px < required ' + (+required.toFixed(2)) +
         'px (max(' + COL_MIN_PX + ', ' + (COL_MIN_FRACTION * 100) + '% of banner ' + bn.w + '))');
  else rules.g3_textColumnWidth = true;

  /* g4 — text inside the banner */
  if (!ti || !de || !bn) fail('g4_textWithinBanner', 'missing title, detail or banner rect');
  else {
    const bad = [];
    if (!within(ti, bn)) bad.push('title escapes banner');
    if (!within(de, bn)) bad.push('detail escapes banner');
    if (bad.length) fail('g4_textWithinBanner', bad.join('; ')); else rules.g4_textWithinBanner = true;
  }

  /* g5 — icon does not overlap the text */
  if (!ic || !col || !ti || !de) fail('g5_noIconTextOverlap', 'missing icon or text rects');
  else {
    const hits = [['column', overlap(ic, col)], ['title', overlap(ic, ti)], ['detail', overlap(ic, de)]]
      .filter(p => p[1]).map(p => p[0] + ' ' + JSON.stringify(p[1]));
    if (hits.length) fail('g5_noIconTextOverlap', 'icon overlaps ' + hits.join(', ')); else rules.g5_noIconTextOverlap = true;
  }

  /* g6 — no horizontal overflow in the text container */
  const boxes = [['column', probe.columnBox], ['title', probe.titleBox], ['detail', probe.detailBox]];
  const missingBox = boxes.filter(b => !b[1]).map(b => b[0]);
  if (missingBox.length) fail('g6_noHorizontalOverflow', 'missing box metrics for ' + missingBox.join(', '));
  else {
    const over = boxes.filter(b => b[1].scrollWidth > b[1].clientWidth + TOL)
      .map(b => b[0] + ' scrollWidth ' + b[1].scrollWidth + ' > clientWidth ' + b[1].clientWidth);
    if (over.length) fail('g6_noHorizontalOverflow', over.join('; ')); else rules.g6_noHorizontalOverflow = true;
  }

  /* g7 — no clipping ancestor cuts the text */
  if (!Array.isArray(probe.clippers)) fail('g7_noClippedText', 'clipper chain not probed');
  else if (!ti || !de) fail('g7_noClippedText', 'missing text rects');
  else {
    const clipped = probe.clippers.filter(c => !within(c.textRect, c.clientRect))
      .map(c => c.who + ' clipped by ' + c.sel + ' (' + c.overflowX + '/' + c.overflowY + ')');
    if (clipped.length) fail('g7_noClippedText', clipped.join('; ')); else rules.g7_noClippedText = true;
  }

  /* g8 — banner inside the mentor tile and the stage */
  if (!bn || !probe.tile || !probe.stage) fail('g8_bannerWithinTile', 'missing banner, tile or stage rect');
  else {
    const bad = [];
    if (!within(bn, probe.tile)) bad.push('banner ' + bn.w + 'x' + bn.h + ' escapes mentor tile ' + probe.tile.w + 'x' + probe.tile.h);
    if (!within(bn, probe.stage)) bad.push('banner escapes stage ' + probe.stage.w + 'x' + probe.stage.h);
    if (bad.length) fail('g8_bannerWithinTile', bad.join('; ')); else rules.g8_bannerWithinTile = true;
  }

  /* g9 — readiness is necessary, never sufficient */
  const geometryHeld = ['g1_iconBox', 'g2_textRendered', 'g3_textColumnWidth', 'g4_textWithinBanner',
                        'g5_noIconTextOverlap', 'g6_noHorizontalOverflow', 'g7_noClippedText',
                        'g8_bannerWithinTile'].every(id => rules[id] === true);
  if (probe.readyAttr !== 'true') fail('g9_readinessNotSufficient', 'data-live-room-ready=' + String(probe.readyAttr));
  else if (!geometryHeld) fail('g9_readinessNotSufficient',
    'data-live-room-ready="true" but the visual content geometry failed — readiness alone is not a visual PASS');
  else rules.g9_readinessNotSufficient = true;

  return {
    pass: RULE_IDS.every(id => rules[id] === true),
    rules, failures,
    measured: {
      readyAttr: probe.readyAttr,
      iconW: ic ? ic.w : null, iconH: ic ? ic.h : null,
      titleW: ti ? ti.w : null, detailW: de ? de.w : null,
      columnW: col ? col.w : null, bannerW: bn ? bn.w : null, bannerH: bn ? bn.h : null,
      requiredColumnW: isFinite(required) ? +required.toFixed(2) : null,
      titleText: probe.titleText, detailText: probe.detailText
    },
    meta: m
  };
}

/* Coverage assertion — a banner state the oracle does not test is a FAILURE. */
export function assertBannerStateCoverage(discovered, covered) {
  if (!discovered || discovered.fatal || !Array.isArray(discovered.states))
    return { pass: false, reason: (discovered && discovered.fatal) || 'STATE_DISCOVERY_FAILED', missing: [], extra: [] };
  const ids = discovered.states.map(s => s.id);
  const missing = ids.filter(id => covered.indexOf(id) < 0);
  const extra = covered.filter(id => ids.indexOf(id) < 0);
  return { pass: missing.length === 0 && extra.length === 0,
           reason: missing.length ? 'UNCOVERED_BANNER_STATES' : (extra.length ? 'COVERED_STATE_NOT_IN_MODEL' : 'ok'),
           discovered: ids, covered, missing, extra };
}
