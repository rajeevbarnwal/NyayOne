// Passed directly to page.evaluate; intentionally dependency-free.
export function inspectSurface({ reference = false, clocks = false } = {}) {
  const root = reference ? document.querySelector('.vp') : document.body;
  const base = root.getBoundingClientRect();
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
  const visible = element => {
    const rect = element.getBoundingClientRect(), css = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && rect.bottom > base.top && rect.top < base.bottom && css.visibility !== 'hidden' && css.display !== 'none';
  };
  const box = element => {
    const rect = element.getBoundingClientRect();
    return { x: rect.x - base.x, y: rect.y - base.y, width: rect.width, height: rect.height };
  };
  // Keep source text boundaries (including <br>) while excluding CSS-hidden
  // responsive alternatives. innerText alone inserts layout-dependent newlines.
  const renderedText = element => [...element.childNodes].map(node => {
    if (node.nodeType === 3) return node.textContent;
    if (node.nodeType !== 1) return '';
    const css = getComputedStyle(node);
    return css.display === 'none' || css.visibility === 'hidden' ? '' : renderedText(node);
  }).join('');
  const clockElements = clocks ? [...root.querySelectorAll('*')].filter(element => visible(element) && !element.children.length && /^\d{2}:\d{2}$/.test(element.textContent.trim())) : [];
  const mask = clockElements.map(element => ({ kind: 'otp-clock', text: element.textContent.trim(), box: box(element) }));
  const controls = [...root.querySelectorAll('button, a, input:not([type=hidden]), select, textarea, [role=button], [role=combobox]')].filter(visible).map(element => {
    const implicit = { BUTTON: 'button', A: 'link', SELECT: 'combobox', TEXTAREA: 'textbox', INPUT: ['checkbox', 'radio'].includes(element.type) ? element.type : 'textbox' };
    const labels = element.labels ? [...element.labels].map(label => normalize(label.textContent)).join(' ') : '';
    const labelledBy = (element.getAttribute('aria-labelledby') || '').split(' ').filter(Boolean).map(id => document.getElementById(id)?.textContent || '').join(' ');
    return { role: element.getAttribute('role') || implicit[element.tagName], name: normalize(element.getAttribute('aria-label') || labelledBy || labels || element.innerText || element.getAttribute('placeholder')), disabled: element.disabled === true || element.getAttribute('aria-disabled') === 'true', box: box(element) };
  });
  const headings = [...root.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading]')].filter(visible).map(element => ({ text: normalize(renderedText(element)), box: box(element) }));
  let text = normalize(root.innerText);
  if (clocks) for (const item of mask) text = text.replace(item.text, '[OTP_CLOCK]');
  return { controls, headings, text, masks: mask, overflow: Math.max(0, root.scrollWidth - root.clientWidth), dimensions: [base.width, base.height] };
}
