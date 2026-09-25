import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ProfileSummaryView } from './ProfileSummaryView';
import type { StudentProfileProjection } from '../lib/profileApi';

const projection: StudentProfileProjection = {
  profileVersion: 1, completionVersion: 'v1', completionPercent: 67,
  completedSections: ['personal', 'academic'], missingRequirements: ['interests.goals'],
  nextIncompleteSection: 'interests', isComplete: false, accessMode: 'full',
  institutionalEmailStatus: 'not_provided', disabledCapabilities: [],
  guardian: { required: false, status: 'not_required' },
  profilePrompt: { shouldShow: false, dismissedForSession: true },
  profile: {
    personal: { firstName: 'Synthetic', middleName: null, lastName: 'Student', dateOfBirth: '', preferredLanguage: 'en', city: 'Synthetic City', pronouns: null },
    academic: { college: 'Synthetic College', yearOfStudy: '3rd', enrolmentNumber: 'TEST/2026', institutionalEmail: null, barEnrolmentNumber: null },
    interests: { interests: [], goals: [] },
  },
};
const render = (value = projection) => renderToStaticMarkup(<MemoryRouter><ProfileSummaryView projection={value} emailManagement={<button>Manage</button>}><section data-testid="email-panel" /></ProfileSummaryView></MemoryRouter>);

describe('NYAY-64 S-17 Revision L profile presentation', () => {
  it('uses the profile identity hierarchy without fabricated prototype identity', () => {
    const html = render();
    for (const value of ['data-screen="S-17"', 'id="S-17-title"', 'Synthetic Student', 'Synthetic College · 3rd year', 'aria-label="SS · Your Profile · Synthetic Student"', '>SS</span>']) expect(html).toContain(value);
    expect(html).not.toMatch(/Aditi|Nair|aditi\.nair|9:41|\+91|Bengaluru/u);
    expect(html.match(/<h1\b/gu)).toHaveLength(1);
  });
  it.each([0, 34, 67, 100] as const)('presents only the server completion value %s', percent => {
    const html = render({ ...projection, completionPercent: percent });
    expect(html).toContain(`Profile ${percent}%`);
    expect(html).toContain(`aria-valuenow="${percent}"`);
  });
  it('removes the completion card only when the server marks the profile complete', () => {
    const html = render({ ...projection, completionPercent: 100, isComplete: true, nextIncompleteSection: null, completedSections: ['personal', 'academic', 'interests'] });
    expect(html).not.toContain('data-testid="profile-completion-card"');
    expect(html).toContain('aria-label="Edit profile"');
    expect(html).toContain('Profile 100%');
  });
  it.each(['not_provided', 'pending', 'verified', 'rejected', 'expired', 'revoked'] as const)('shows truthful email status %s; gold only for verified', status => {
    const html = render({ ...projection, institutionalEmailStatus: status });
    expect(html.includes('v321-profile-summary__chip--verified')).toBe(status === 'verified');
    expect(html.includes('>Email Verified</span>')).toBe(status === 'verified');
  });
  it('retains server-backed information and email-management slots', () => {
    const html = render();
    for (const text of ['Mobile', 'Not available', 'Institutional Email', 'Not provided', 'City', 'Synthetic City', 'Interests', 'Enrolment', 'TEST/2026', 'Preferred language', 'Guardian status', 'Access', '>full<', '>Manage</button>', 'data-testid="email-panel"']) expect(html).toContain(text);
    expect(html).not.toContain('Deletion asks for OTP confirmation');
    expect(html).not.toContain('Download My Data');
  });
  it('does not derive full access from completeness or invent guardian approval', () => {
    const html = render({ ...projection, isComplete: true, completionPercent: 100, accessMode: 'limited', guardian: { required: true, status: 'required_pending' }, disabledCapabilities: ['community', 'sharing'] });
    expect(html).toContain('>limited<');
    expect(html).toContain('required pending');
    expect(html).not.toContain('Email Verified');
  });
  it('has a neutral missing-identity fallback and safely renders Unicode names', () => {
    const html = render({ ...projection, profile: { ...projection.profile, personal: { ...projection.profile.personal, firstName: '', lastName: '' } } });
    expect(html).toContain('>Your profile</h1>');
    expect(html).toContain('>P</span>');
    const unicode = render({ ...projection, profile: { ...projection.profile, personal: { ...projection.profile.personal, firstName: 'राज', lastName: 'शर्मा' } } });
    expect(unicode).toContain('राज शर्मा');
    expect(unicode).toContain('>रश</span>');
  });
  it('keeps S-17 query, disclosure and existing destinations intact', () => {
    const screen = readFileSync('src/features/student/profile/ProfileScreens.tsx', 'utf8').split('export function ProfileView()')[1];
    expect(screen).toContain('useStudentProfileProjection()');
    expect(screen).toContain('useState(false)');
    expect(screen).toContain('<EmailIdentityPanel expanded={emailIdentitiesOpen} />');
    expect(screen).toContain("aria-label={emailIdentitiesOpen ? 'Hide sign-in emails' : 'Manage sign-in emails'}");
    const view = readFileSync('src/features/student/profile/ProfileSummaryView.tsx', 'utf8');
    expect(view).toContain("profileSectionRoute(projection.nextIncompleteSection ?? 'personal')");
    expect(view).toContain('profileResumeDestination(projection)');
    expect(view).toContain("nav('/s-19')");
    expect(view).not.toMatch(/mutate|localStorage|sessionStorage|setTimeout/u);
  });
  it('isolates the canonical S-17 shell and profile styles', () => {
    expect(readFileSync('src/components/shell/AppShell.tsx', 'utf8')).toContain("if (location.pathname === '/s-17')");
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css).toContain(".v321-profile[data-screen='S-17']");
    expect(css).toContain('.v321-profile-summary__identity');
  });
  it('retains the prototype normal body rhythm only within S-17', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css.split('.v321-profile-summary {')[1].split('}')[0]).toContain('line-height: normal;');
    expect(css.split('.v321-profile {')[1].split('}')[0]).toContain('14px/1.5');
  });
  it('uses the exact Revision L edit and privacy icon shapes', () => {
    const html = render();
    expect(html).toContain('M4 20l4-1L19.5 7.5a2 2 0 0 0-3-3L5 16z');
    expect(html).toContain('M12 3.5 5 6v5.2c0 4.4 3 7.4 7 9.3 4-1.9 7-4.9 7-9.3V6z');
    expect(html).toContain('m9.2 11.8 2 2 3.6-3.8');
  });
  it('keeps the prototype intrinsic name column and separate flexible spacer', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css.split('.v321-profile-summary__name {')[1].split('}')[0]).toContain('flex: 0 1 auto;');
    expect(css.split('.v321-profile-summary__spacer {')[1]?.split('}')[0]).toContain('flex: 1;');
    expect(render()).toContain('class="v321-profile-summary__spacer" aria-hidden="true"');
  });
  it('uses the prototype nested 20px icon with its normal inline baseline wrapper', () => {
    const html = render();
    expect(html).toContain('class="v321-profile-summary__finish-icon" aria-hidden="true"><span class="v321-revl-icon"');
    expect(html).toContain('class="v321-profile-summary__privacy-icon" aria-hidden="true"><span class="v321-profile-summary__glyph"');
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css).not.toContain('.v321-profile-summary__finish .v321-revl-icon { height: 22px; }');
    expect(css.split('.v321-profile-summary__glyph {')[1]?.split('}')[0]).toContain('height: 20px;');
  });
});
