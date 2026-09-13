import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { V34AuthGate } from './V34Screens';

describe('NYAY-81 S-03 Revision L entry screen', () => {
  const render = () => renderToStaticMarkup(<MemoryRouter><V34AuthGate theme="light" /></MemoryRouter>);

  it('uses the approved visible labels as accessible names, without stale overrides', () => {
    const html = render();
    expect(html).toContain('aria-label="Sign In Securely"');
    expect(html).toContain('aria-label="Create Student Account"');
    expect(html).not.toContain('aria-label="Sign in"');
    expect(html).not.toContain('aria-label="Register as a student"');
  });

  it('keeps all five sealed producer selectors exact against the aligned labels', () => {
    const nyay5 = readFileSync('scripts/nyay5-profile-browser.mjs', 'utf8');
    const journey = readFileSync('scripts/v34-s01-s10-e2e.mjs', 'utf8');
    expect(nyay5.match(/name: 'Sign In Securely', exact: true/g)).toHaveLength(2);
    expect(nyay5.match(/name: 'Create Student Account', exact: true/g)).toHaveLength(2);
    expect(journey.match(/name: 'Sign In Securely', exact: true/g)).toHaveLength(1);
    for (const source of [nyay5, journey]) {
      expect(source).not.toContain("name: 'Sign in', exact: true");
      expect(source).not.toContain("name: 'Register as a student', exact: true");
    }
  });

  it('orders the desktop header before the benefits panel in the reading order', () => {
    const html = render();
    expect(html.indexOf('class="v321-topbar"')).toBeLessThan(html.indexOf('class="v321-brandpanel"'));
    expect(html.indexOf('class="v321-brandpanel"')).toBeLessThan(html.indexOf('id="main-content"'));
  });

  it('retains working legal links rather than copying inert prototype text', () => {
    const html = render();
    expect(html).toContain('<a href="/s-19">Privacy Notice</a>');
    expect(html).toContain('<a href="/terms">Terms</a>');
    expect(html).toContain('<a href="/accessibility">Accessibility</a>');
    expect(html.match(/href="\/s-19"/g)).toHaveLength(2);
  });

  it('uses S-03-only regular link typography without removing its affordance or hit target', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css).toMatch(/\[data-screen="S-03"\] \.v321-consent a\s*\{[^}]*font-weight:\s*400;[^}]*text-decoration:\s*underline;/);
    expect(css).toMatch(/\.v321-consent a\s*\{[^}]*min-height:\s*44px;/);
  });

  it('keeps the two auth destinations and persona-return focus contract', () => {
    const source = readFileSync('src/features/student/auth/V34Screens.tsx', 'utf8');
    const gateway = source.slice(source.indexOf('export function V34AuthGate'), source.indexOf('export function V34VerifiedHome'));
    expect(gateway).toContain("nav('/s-04')");
    expect(gateway).toContain("nav('/s-08')");
    expect(gateway).toContain("?.nyay7Focus !== 'persona'");
    expect(gateway).toContain('data-nyayone-persona-trigger');
    expect(gateway).toContain("consumeStudentAuthTransitionNotice('account_deletion_accepted')");
    expect(gateway).not.toContain('localStorage');
  });
});
