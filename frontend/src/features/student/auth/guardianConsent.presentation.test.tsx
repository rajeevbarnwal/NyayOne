import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { RestrictedDashboard } from './AuthScreens';
import type { StudentProfileProjection } from '../lib/profileApi';
import { STUDENT_PROFILE_QUERY_KEY } from '../profile/profileHooks';

const projection: StudentProfileProjection = {
  profileVersion: 1, completionVersion: 'v1', completionPercent: 67,
  completedSections: ['personal', 'academic'], missingRequirements: ['interests.interests'],
  nextIncompleteSection: 'interests', isComplete: false, institutionalEmailStatus: 'not_provided',
  guardian: { required: true, status: 'required_pending' }, accessMode: 'limited',
  disabledCapabilities: ['community', 'sharing'], profilePrompt: { shouldShow: false, dismissedForSession: true },
  profile: {
    personal: { firstName: 'Synthetic', middleName: null, lastName: 'Student', dateOfBirth: '2011-01-01', preferredLanguage: 'en', city: null, pronouns: null },
    academic: { college: null, yearOfStudy: null, enrolmentNumber: null, institutionalEmail: null, barEnrolmentNumber: null },
    interests: { interests: [], goals: [] },
  },
};
function render(value: StudentProfileProjection | undefined = projection) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (value) client.setQueryData(STUDENT_PROFILE_QUERY_KEY, value);
  return renderToStaticMarkup(<QueryClientProvider client={client}><MemoryRouter><RestrictedDashboard /></MemoryRouter></QueryClientProvider>);
}
describe('NYAY-63 S-16 Revision L presentation, server-owned guardian authority', () => {
  it('owns the Revision L guardian frame and uses the real profile identity', () => {
    const html = render();
    expect(html).toContain('class="v321-profile" data-screen="S-16"');
    expect(html).toContain('A guardian’s consent is needed first.');
    expect(html).toContain('NyayOne — Legal, on the record');
    expect(html).toContain('Your Profile · Synthetic Student');
    expect(html).toContain('>SS</span>');
    expect(html).not.toMatch(/R\. Nair|91234|Aditi|9:41/);
  });
  it('labels unavailable contact details without collecting or fabricating them', () => {
    const html = render();
    expect(html).toContain('Guardian’s Name');
    expect(html).toContain('Guardian’s Mobile');
    expect(html.match(/>Not available</g)).toHaveLength(2);
    expect(html).not.toMatch(/<input|<select|Resend Consent Request|Consent Requested|SMS|approval link/);
  });
  it('preserves the exact server restrictions and both existing safe actions', () => {
    const html = render();
    expect(html).toContain('Disabled capabilities: community, sharing.');
    expect(html).toContain('Guardian consent is required');
    expect(html).toContain('No client action can mark consent verified.');
    expect(html).toContain('View limited home');
    expect(html).toContain('Continue profile');
    expect(html).not.toMatch(/>\s*(Approve|Verify guardian|Grant access)\s*</);
  });
  it.each([
    ['required_pending', 'Consent required'], ['rejected', 'Consent rejected'], ['revoked', 'Consent revoked'],
  ] as const)('reports %s without claiming a request was sent', (status, label) => {
    const html = render({ ...projection, guardian: { required: true, status } });
    expect(html).toContain(`>${label}</div>`);
    expect(html).not.toContain('Consent Requested');
    expect(html).not.toContain('Verified</div>');
  });
  it('does not infer guardian requirements from age or invent consent for another limited account', () => {
    const html = render({ ...projection, guardian: { required: false, status: 'not_required' }, disabledCapabilities: ['sharing'] });
    expect(html).toContain('Your account has limited access.');
    expect(html).toContain('Your server-issued profile currently has limited access.');
    expect(html).toContain('Disabled capabilities: sharing.');
    expect(html).not.toContain('Guardian’s Mobile');
    expect(html).not.toContain('consent is needed first');
  });
  it('does not contradict verified guardian status when another server restriction remains', () => {
    const html = render({ ...projection, guardian: { required: true, status: 'verified' } });
    expect(html).toContain('Your account has limited access.');
    expect(html).toContain('Guardian consent verified');
    expect(html).not.toContain('consent is needed first');
  });
  it('keeps the full-access redirect pending and never renders stale guardian controls', () => {
    const html = render({ ...projection, accessMode: 'full' });
    expect(html).toContain('Checking access…');
    expect(html).not.toContain('Continue profile');
    const controller = readFileSync('src/features/student/auth/AuthScreens.tsx', 'utf8').split('export function RestrictedDashboard()')[1];
    expect(controller).toContain("profile.data?.accessMode === 'full'");
    expect(controller).toContain("nav('/s-14', { replace: true })");
  });
  it('has one heading and an S-16-only shell without an inherited status bar', () => {
    const html = render();
    expect(html.match(/<h1\b/g)).toHaveLength(1);
    expect(html).toContain('aria-labelledby="S-16-title"');
    expect(readFileSync('src/components/shell/AppShell.tsx', 'utf8')).toContain("location.pathname === '/s-16'");
  });
  it.each(['font-size: 14px', 'line-height: normal', 'gap: 9px'])('uses Revision L action %s in S-16 only', declaration => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css.split(".v321-profile[data-screen='S-16'] .v321-profile__button {")[1]?.split('}')[0]).toContain(declaration);
  });
  it('keeps scoped AA error text and reference aside rhythm', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css).toContain(".v321-profile[data-screen='S-16'] .ui-state[role='alert']");
    expect(css).toContain(".v321-profile[data-screen='S-16'] .v321-profile__card p { line-height: 1.55; }");
  });
  it('matches the reference intro metrics and guardian/name icon presentation', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css.split('.v321-guardian__intro {')[1].split('}')[0]).toContain('font-size: 13.5px');
    expect(css.split('.v321-guardian__heading-icon {')[1].split('}')[0]).toContain('color: #7a5a10');
    const view = readFileSync('src/features/student/auth/GuardianConsentView.tsx', 'utf8');
    expect(view).toContain('<NyayOneRevLIcon name="users" />Guardian’s Name');
  });
});
