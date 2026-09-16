import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { V34Register } from './V34Screens';

describe('NYAY-86 S-08 Revision L account creation', () => {
  const render = () => renderToStaticMarkup(<MemoryRouter><V34Register theme="light"/></MemoryRouter>);

  it('orders the top navigation before the brand panel and form in the reading order', () => {
    const html = render();
    const topbar = html.indexOf('class="v321-topbar"');
    const brand = html.indexOf('class="v321-brandpanel"');
    const main = html.indexOf('id="main-content"');
    expect(topbar).toBeGreaterThanOrEqual(0);
    expect(topbar).toBeLessThan(brand);
    expect(brand).toBeLessThan(main);
  });

  it('uses the approved visible field labels and inline optional marker', () => {
    const html = render();
    for (const [id, label] of [['first', 'First Name'], ['middle', 'Middle Name (Optional)'], ['last', 'Last Name'], ['mobile', 'Mobile Number'], ['dob', 'Date of Birth']]) {
      const markup = html.match(new RegExp(`<label[^>]*for="v34-${id}"[^>]*>(.*?)</label>`, 'su'))?.[1];
      expect(markup?.replace(/<[^>]*>/gu, '')).toBe(label);
    }
  });

  it('matches the visible Create Account CTA with its accessible name and tooltip', () => {
    const buttons = [...render().matchAll(/<button\b[^>]*>.*?<\/button>/gsu)].map(([button]) => button);
    const create = buttons.find(button => button.includes('<span>Create Account</span>'));
    expect(create).toContain('aria-label="Create Account"');
    expect(create).toContain('data-tip="Create Account"');
    expect(create).toMatch(/<svg[^>]*aria-hidden="true"/u);
    expect(create).not.toContain('Send one time code');
  });

  it('keeps the approved NYAY-7 security supersession: empty identity and two unchecked required consents', () => {
    const html = render();
    for (const id of ['first', 'middle', 'last', 'mobile', 'dob']) {
      expect(html).toMatch(new RegExp(`<input(?=[^>]*id="v34-${id}")(?=[^>]*value="")[^>]*>`, 'u'));
    }
    for (const id of ['terms', 'privacy']) {
      const input = html.match(new RegExp(`<input(?=[^>]*id="v34-${id}")[^>]*>`, 'u'))?.[0];
      expect(input).toContain('type="checkbox"');
      expect(input).toContain('required=""');
      expect(input).not.toContain('checked=""');
    }
    expect(html).toContain('I accept the Terms.');
    expect(html).toContain('I acknowledge the Privacy Notice.');
  });

  it('preserves native date entry, the eligibility help and required control semantics', () => {
    const html = render();
    expect(html).toMatch(/<input(?=[^>]*id="v34-dob")(?=[^>]*type="date")(?=[^>]*required="")[^>]*>/u);
    expect(html).toContain('More information about Date of Birth');
    expect(html).toContain('Not shown on your profile.');
    expect(html).toMatch(/autocomplete="given-name"/iu);
    expect(html).toMatch(/autocomplete="tel-national"/iu);
  });

  it('renders footer notices as inert text without navigation or tab stops', () => {
    const footer = render().match(/<footer class="v321-legal">(.*?)<\/footer>/su)?.[1];
    expect(footer).toBeDefined();
    for (const text of ['Privacy Notice', 'Terms', 'Accessibility']) expect(footer).toContain(`<span>${text}</span>`);
    expect(footer).not.toMatch(/<(?:a|button|input)\b|\bhref=|\btabindex=|\brole="(?:link|button)"/iu);
  });

  it('scopes heading, field alignment and input-border corrections to S-08', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css).toMatch(/\[data-screen='S-08'\] \.v321-form > div:has\(> \.v34-title\)\s*\{\s*gap: 2px;/u);
    expect(css).toMatch(/\[data-screen='S-08'\] \.v34-fieldset > \.v34-row\s*\{[^}]*gap: 10px;/u);
    expect(css).toMatch(/\[data-screen='S-08'\] \.v34-field__top > label\s*\{[^}]*display: inline-flex;[^}]*align-items: center;[^}]*gap: 6px;/u);
    expect(css).toMatch(/\[data-screen='S-08'\] \.v34-field__control > input\s*\{[^}]*min-height: 46px;[^}]*border:/u);
  });
});
