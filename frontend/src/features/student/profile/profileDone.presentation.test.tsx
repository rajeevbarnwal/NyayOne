import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ProfileCompleteView } from './ProfileScreens';
import type { InstitutionalEmailStatus } from '../lib/profileApi';

const render = (verification: InstitutionalEmailStatus) => renderToStaticMarkup(createElement(MemoryRouter, null,
  createElement(ProfileCompleteView, { firstName: 'Synthetic', middleName: null, lastName: 'Student', verification })));

describe('NYAY-59 S-12 Revision L completion presentation', () => {
  it('renders the approved completion hierarchy and both destination actions', () => {
    const html = render('not_provided');
    for (const value of ['data-screen="S-12"', 'id="S-12-title"', 'Your NyayOne profile is ready', 'Profile details complete', 'Go to Dashboard', 'Review Profile', 'Your Profile · Synthetic Student', 'v321-profile-done__check']) expect(html).toContain(value);
    expect(html).not.toMatch(/Aditi|Nair|9:41|You’re ready/u);
  });

  it.each([
    ['not_provided', 'Institutional email not provided'],
    ['pending', 'Email Verification Pending'],
    ['verified', 'Institutional email verified'],
    ['rejected', 'Institutional email verification rejected'],
    ['expired', 'Institutional email verification expired'],
    ['revoked', 'Institutional email verification revoked'],
  ] as const)('derives the %s badge from the server projection', (status, copy) => {
    const html = render(status);
    expect(html).toContain(copy);
    expect(html.includes('v321-profile-done__verification--verified')).toBe(status === 'verified');
    expect(html.includes('>Profile complete<')).toBe(status === 'verified');
  });

  it('keeps incomplete-profile redirect and server read intact', () => {
    const source = readFileSync('src/features/student/profile/ProfileScreens.tsx', 'utf8');
    const done = source.slice(source.indexOf('export function ProfileDone()'), source.indexOf('/* -------------------------------------------------------------------------- */', source.indexOf('export function ProfileDone()')));
    expect(done).toContain('useStudentProfileProjection()');
    expect(done).toContain('if (query.data && !query.data.isComplete) nav(profileSectionRoute(query.data.nextIncompleteSection), { replace: true })');
    expect(done).toContain('if (!query.data || !query.data.isComplete) return <ProfileLoadState');
    expect(done).toContain('verification={query.data.institutionalEmailStatus}');
    expect(done).not.toMatch(/mutate|localStorage|sessionStorage/u);
    const view = source.slice(source.indexOf('export function ProfileCompleteView'), source.indexOf('export function ProfileDone()'));
    expect(view).toContain("nav('/s-14')");
    expect(view).toContain("nav('/s-17')");
  });

  it('owns only the S-12 shell and keeps desktop/mobile styles scoped', () => {
    const shell = readFileSync('src/components/shell/AppShell.tsx', 'utf8');
    expect(shell).toContain("if (location.pathname === '/s-12')");
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    for (const value of [".v321-profile[data-screen='S-12']", '.v321-profile-done__check', 'width: 92px', 'height: 92px', '.v321-profile-done__actions', 'min-height: 54px']) expect(css).toContain(value);
  });

  it('matches the normal line heights of the 13px eyebrow and 24px verification chip', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    for (const selector of [".v321-profile[data-screen='S-12'] .v321-profile__eyebrow {", '.v321-profile-done__verification {']) {
      expect(css.slice(css.indexOf(selector)).split('}')[0]).toContain('line-height: normal');
    }
  });

  it('preserves the prototype inline icon wrapper in Review Profile rather than shifting the glyph', () => {
    expect(render('pending')).toContain('<span class="v321-profile-done__review-icon"><span class="v321-revl-icon"');
  });
});
