/* Option C2 accessibility ORACLE — in-page probes.
   These two functions are SERIALISED INTO THE BROWSER by both the oracle driver
   (tools/a11y_oracle.mjs) and the oracle self-tests
   (tests/a11y_oracle_selftest.mjs), so the self-tests exercise exactly the same
   measurement code that produces the published evidence.
   They must stay dependency-free and must not reference module scope. */

/* ============================== page probes ============================== */
/* Serialised into the page. Kept dependency-free and mirroring the core maths. */
export const PROBE = function (payload) {
  const CONTROLS = payload.controls;
  const parse = (c) => {
    const s = String(c == null ? '' : c).trim();
    let m = s.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (m) { let h = m[1]; if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
      return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 }; }
    m = s.match(/rgba?\(([^)]+)\)/i);
    if (!m) return null;
    const p = m[1].split(/[,\s\/]+/).filter(Boolean).map(Number);
    if (p.length < 3) return null;
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return Math.round(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)) * 100) / 100; };
  const hex = (c) => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const stable = (el) => {
    if (!el || el.nodeType !== 1) return null;
    const t = el.getAttribute && el.getAttribute('data-testid');
    if (t) return '[data-testid=' + t + ']';
    if (el.id) return '#' + el.id;
    const cls = (el.getAttribute && el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
    const parentSel = el.parentElement ? stable(el.parentElement) : '';
    const own = el.tagName.toLowerCase() + (cls ? '.' + cls : '');
    return (parentSel && parentSel.indexOf('[data-testid') === 0 ? parentSel + ' > ' : '') + own;
  };
  const visible = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) return false;
    if (el.closest('[inert],[aria-hidden=true],#reviewer')) return false;
    const r = el.getBoundingClientRect();
    /* An element whose own box collapsed to zero width can still PAINT its text
       (it overflows). Excluding it would hide real contrast failures, so any
       element with a non-zero extent in either axis is treated as visible. */
    return r.width > 0 || r.height > 0;
  };
  /* effective background: composite every non-transparent ancestor down to an opaque one */
  const effBg = (el) => {
    const stack = []; let n = el;
    while (n && n.nodeType === 1) {
      const cs = getComputedStyle(n);
      const c = parse(cs.backgroundColor);
      const img = cs.backgroundImage && cs.backgroundImage !== 'none';
      if (c && c.a > 0) stack.push({ c: c, el: n, img: img });
      if (c && c.a >= 1) break;
      n = n.parentElement;
    }
    let base = { r: 255, g: 255, b: 255, a: 1 };
    const last = stack[stack.length - 1];
    if (last && last.c.a >= 1) base = last.c;
    let acc = base;
    for (let i = stack.length - (last && last.c.a >= 1 ? 2 : 1); i >= 0; i--) acc = over(stack[i].c, acc);
    return { color: acc, chain: stack.map(s => stable(s.el) + ':' + hex(s.c) + (s.c.a < 1 ? '@' + s.c.a : '') + (s.img ? '+bgimage' : '')) };
  };
  const ownBg = (el) => { /* the element's own painted surface, over its parent */
    const cs = getComputedStyle(el);
    const c = parse(cs.backgroundColor);
    const parent = effBg(el.parentElement || document.body).color;
    if (!c || c.a === 0) return { color: parent, painted: false };
    return { color: c.a < 1 ? over(c, parent) : c, painted: true };
  };

  /* ---------------- TEXT rows ---------------- */
  const text = [];
  for (const el of document.querySelectorAll('*')) {
    if (!visible(el)) continue;
    const own = [].slice.call(el.childNodes).filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent.trim()).join(' ');
    if (!own) continue;
    const cs = getComputedStyle(el);
    const fgRaw = parse(cs.color); if (!fgRaw) continue;
    const bg = effBg(el);
    const fg = fgRaw.a < 1 ? over(fgRaw, bg.color) : fgRaw;
    const fsPx = parseFloat(cs.fontSize), fw = parseInt(cs.fontWeight, 10) || 400;
    text.push({ selector: stable(el), tag: el.tagName.toLowerCase(), sample: own.slice(0, 48),
      fg: hex(fg), bg: hex(bg.color), bgChain: bg.chain.slice(0, 3), fontPx: Math.round(fsPx * 10) / 10, weight: fw,
      large: fsPx >= 24 || (fsPx >= 18.66 && fw >= 700), ratio: ratio(fg, bg.color),
      overBackgroundImage: bg.chain.some(c => c.indexOf('+bgimage') >= 0) });
  }

  /* ---------------- NON-TEXT rows ---------------- */
  const nonText = [];
  for (const ctl of CONTROLS) {
    const el = document.querySelector(ctl.sel);
    if (!el || !visible(el)) continue;
    const cs = getComputedStyle(el);
    const parent = effBg(el.parentElement || document.body);
    const fill = ownBg(el);
    /* identifying feature: the icon glyph stroke, measured against the control's OWN surface */
    const icon = document.querySelector(ctl.identify.selector);
    let identifying = null;
    if (icon) {
      const ics = getComputedStyle(icon);
      const strokeEl = icon.querySelector('.s');
      const strokeRaw = parse(strokeEl ? getComputedStyle(strokeEl).stroke : ics.color) || parse(ics.color);
      if (strokeRaw) {
        const behind = fill.painted ? fill.color : parent.color;
        const stroke = strokeRaw.a < 1 ? over(strokeRaw, behind) : strokeRaw;
        identifying = { feature: ctl.identify.feature, selector: ctl.identify.selector,
          fg: hex(stroke), bg: hex(behind), ratio: ratio(stroke, behind) };
      }
    }
    /* visible text label inside the control, if any */
    let label = null;
    const labelText = [].slice.call(el.querySelectorAll('span,b,strong'))
      .filter(n => visible(n) && n.textContent.trim())[0];
    if (labelText) {
      const lcs = getComputedStyle(labelText);
      const lfg = parse(lcs.color); const behind = effBg(labelText).color;
      if (lfg) label = { text: labelText.textContent.trim().slice(0, 32), fg: hex(lfg.a < 1 ? over(lfg, behind) : lfg), bg: hex(behind),
        ratio: ratio(lfg.a < 1 ? over(lfg, behind) : lfg, behind) };
    }
    if (fill.painted) {
      nonText.push({ facet: 'surface', selector: ctl.sel, accessibleName: el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 40) || ctl.name,
        feature: 'control fill vs the surface behind it', fg: hex(fill.color), bg: hex(parent.color),
        bgChain: parent.chain.slice(0, 3), ratio: ratio(fill.color, parent.color), identifying: identifying, label: label,
        pressed: el.getAttribute('aria-pressed') });
    }
    const bw = parseFloat(cs.borderTopWidth) || 0;
    const bcRaw = parse(cs.borderTopColor);
    if (bw > 0 && bcRaw && bcRaw.a > 0) {
      const bc = bcRaw.a < 1 ? over(bcRaw, parent.color) : bcRaw;
      nonText.push({ facet: 'border', selector: ctl.sel, accessibleName: el.getAttribute('aria-label') || (el.textContent || '').trim().slice(0, 40) || ctl.name,
        feature: 'control boundary vs the surface behind it', fg: hex(bc), bg: hex(parent.color),
        bgChain: parent.chain.slice(0, 3), borderWidthPx: bw, ratio: ratio(bc, parent.color),
        identifying: identifying, label: label, pressed: el.getAttribute('aria-pressed') });
    }
  }
  return { text: text, nonText: nonText };
};

/* focus indicator probe: read the CURRENTLY focused element's indicator */
export const FOCUS_PROBE = function () {
  const parse = (c) => {
    const s = String(c == null ? '' : c).trim();
    const m = s.match(/rgba?\(([^)]+)\)/i);
    if (!m) return null;
    const p = m[1].split(/[,\s\/]+/).filter(Boolean).map(Number);
    if (p.length < 3) return null;
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return Math.round(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)) * 100) / 100; };
  const hex = (c) => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const stable = (el) => {
    const t = el.getAttribute && el.getAttribute('data-testid');
    if (t) return '[data-testid=' + t + ']';
    if (el.id) return '#' + el.id;
    return el.tagName.toLowerCase();
  };
  const effBg = (el) => {
    let n = el, stack = [];
    while (n && n.nodeType === 1) {
      const cs = getComputedStyle(n); const c = parse(cs.backgroundColor);
      if (c && c.a > 0) stack.push(c);
      if (c && c.a >= 1) break;
      n = n.parentElement;
    }
    let base = { r: 255, g: 255, b: 255, a: 1 };
    const last = stack[stack.length - 1];
    if (last && last.a >= 1) base = last;
    let acc = base;
    for (let i = stack.length - (last && last.a >= 1 ? 2 : 1); i >= 0; i--) acc = over(stack[i], acc);
    return acc;
  };
  const a = document.activeElement;
  if (!a || a === document.body) return null;
  const cs = getComputedStyle(a);
  const outlineStyle = cs.outlineStyle;
  const outlineWidth = parseFloat(cs.outlineWidth) || 0;
  const outlineOffset = parseFloat(cs.outlineOffset) || 0;
  const outlineColor = parse(cs.outlineColor);
  const shadow = cs.boxShadow && cs.boxShadow !== 'none' ? cs.boxShadow : null;
  const parentBg = effBg(a.parentElement || document.body);
  const ownBgRaw = parse(cs.backgroundColor);
  const ownBg = ownBgRaw && ownBgRaw.a > 0 ? (ownBgRaw.a < 1 ? over(ownBgRaw, parentBg) : ownBgRaw) : parentBg;
  const hasOutline = outlineStyle && outlineStyle !== 'none' && outlineWidth > 0 && outlineColor && outlineColor.a > 0;
  let ringHex = null, ratioOuter = null, ratioInner = null, innerAdjacent = null;
  if (hasOutline) {
    const ring = outlineColor.a < 1 ? over(outlineColor, parentBg) : outlineColor;
    ringHex = hex(ring);
    ratioOuter = ratio(ring, parentBg);
    /* a positive outline-offset puts the parent surface in the gap; a zero or
       negative offset makes the control's own surface the inner neighbour */
    const inner = outlineOffset > 0 ? parentBg : ownBg;
    innerAdjacent = hex(inner);
    ratioInner = ratio(ring, inner);
  }
  return {
    selector: stable(a),
    accessibleName: (a.getAttribute('aria-label') || (a.textContent || '').trim()).slice(0, 48),
    hasIndicator: !!(hasOutline || shadow),
    indicatorType: hasOutline ? 'outline' : (shadow ? 'box-shadow' : 'none'),
    outline: outlineStyle + ' ' + outlineWidth + 'px ' + cs.outlineColor + ' offset ' + outlineOffset + 'px',
    boxShadow: shadow ? shadow.slice(0, 80) : null,
    ringColor: ringHex, outerAdjacent: hex(parentBg), innerAdjacent: innerAdjacent,
    thicknessPx: hasOutline ? outlineWidth : 0,
    ratioOuter: ratioOuter, ratioInner: ratioInner
  };
};
