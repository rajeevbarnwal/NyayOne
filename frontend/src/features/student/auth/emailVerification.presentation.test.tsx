import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { EmailVerify } from './AuthScreens';
import type { StudentProfileProjection } from '../lib/profileApi';
import { STUDENT_PROFILE_QUERY_KEY } from '../profile/profileHooks';

const projection: StudentProfileProjection = {
  profileVersion: 1, completionVersion: 'v1', completionPercent: 67,
  completedSections: ['personal', 'academic'], missingRequirements: ['interests.interests', 'interests.goals'],
  nextIncompleteSection: 'interests', isComplete: false, institutionalEmailStatus: 'not_provided',
  guardian: { required: false, status: 'not_required' }, accessMode: 'full', disabledCapabilities: [],
  profilePrompt: { shouldShow: false, dismissedForSession: true },
  profile: {
    personal: { firstName: 'Synthetic', middleName: null, lastName: 'Student', dateOfBirth: '2000-01-01', preferredLanguage: 'en', city: 'Synthetic City', pronouns: null },
    academic: { college: 'Synthetic College', yearOfStudy: '3', enrolmentNumber: 'KA/1234/2023', institutionalEmail: null, barEnrolmentNumber: null },
    interests: { interests: [], goals: [] },
  },
};
function render(status: StudentProfileProjection['institutionalEmailStatus'] = 'not_provided', email: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(STUDENT_PROFILE_QUERY_KEY, { ...projection, institutionalEmailStatus: status, profile: { ...projection.profile, academic: { ...projection.profile.academic, institutionalEmail: email } } });
  return renderToStaticMarkup(<QueryClientProvider client={client}><MemoryRouter><EmailVerify /></MemoryRouter></QueryClientProvider>);
}
describe('NYAY-62 S-15 Revision L presentation with server-only verification authority', () => {
  it('owns the branded verification shell, exact heading and server-derived avatar', () => {
    const html = render();
    expect(html).toContain('class="v321-profile" data-screen="S-15"');
    expect(html).toContain('Verify your institutional email.');
    expect(html).toContain('NyayOne — Legal, on the record');
    expect(html).toContain('Your Profile · Synthetic Student');
    expect(html).toContain('>SS</span>');
    expect(html).toContain('Why complete your profile?');
    expect(html).not.toMatch(/Aditi|Nair|aditi\.|9:41/);
  });
  it('does not invent an address, verification request or editable identity selector', () => {
    const html = render();
    expect(html).toContain('Not provided');
    expect(html).toContain('Add institutional email');
    expect(html).toContain('Back to dashboard');
    expect(html).not.toMatch(/<input|<select|We sent|Resend Link|Gold Seal Active|Verification Pending/);
  });
  it.each(['pending', 'rejected', 'expired', 'revoked'] as const)('keeps the saved %s email and real non-authorizing request action', status => {
    const html = render(status, 'synthetic@example.edu');
    expect(html).toContain('synthetic@example.edu');
    expect(html).toContain('Request verification review');
    expect(html).toContain('only an authorized review');
    expect(html).not.toMatch(/We sent|Resend Link|Gold Seal Active|Check Verification Status|<input/);
  });
  it('shows verified only from the projection and keeps the request disabled', () => {
    const html = render('verified', 'synthetic@example.edu');
    expect(html).toContain('Verified');
    expect(html).toContain('disabled=""');
    expect(html).toContain('Already verified');
    expect(html).not.toContain('Email sign-in is now available');
  });
  it('scopes the owned shell and AA error text to S-15 without touching other routes', () => {
    const shell = readFileSync('src/components/shell/AppShell.tsx', 'utf8');
    expect(shell).toContain("location.pathname === '/s-15'");
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css).toContain(".v321-profile[data-screen='S-15'] .ui-state[role='alert']");
  });
  it('keeps the icon label at 22px and the status at native line-height to match Revision L geometry', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    const label = css.split('.v321-verification__label {')[1].split('}')[0];
    const status = css.split('.v321-verification__status {')[1].split('}')[0];
    expect(label).toContain('min-height: 22px');
    expect(status).toContain('line-height: normal');
  });
  it('matches the reference action padding without adding vertical height to wrapped labels', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css).toContain('.v321-verification .v321-profile__button { padding: 0 10px; }');
    expect(css).not.toContain('.v321-verification__note > svg { flex: 0 0 18px; }');
  });
});
