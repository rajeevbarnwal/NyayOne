import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type { StudentProfileProjection } from '../lib/profileApi';
import { STUDENT_PROFILE_QUERY_KEY } from '../profile/profileHooks';
import { V34VerifiedHome, verifiedHomeShouldAutoOpenDashboard } from './V34Screens';

const projection: StudentProfileProjection = {
  profileVersion: 4, completionVersion: 'v1', completionPercent: 34,
  completedSections: ['personal'], missingRequirements: ['academic.college'],
  nextIncompleteSection: 'academic', isComplete: false,
  institutionalEmailStatus: 'not_provided', guardian: { required: false, status: 'not_required' },
  accessMode: 'full', disabledCapabilities: [],
  profilePrompt: { shouldShow: true, dismissedForSession: false },
  profile: {
    personal: {
      firstName: 'Synthetic', middleName: 'Test', lastName: 'Student', dateOfBirth: '2000-01-01',
      preferredLanguage: 'en', city: 'Synthetic City', pronouns: null,
    },
    academic: { college: null, yearOfStudy: null, enrolmentNumber: null, institutionalEmail: null, barEnrolmentNumber: null },
    interests: { interests: [], goals: [] },
  },
};

function render(value = projection): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(STUDENT_PROFILE_QUERY_KEY, value);
  return renderToStaticMarkup(<QueryClientProvider client={client}><MemoryRouter><V34VerifiedHome/></MemoryRouter></QueryClientProvider>);
}

describe('NYAY-49 S-07 profile prompt presentation', () => {
  it('keeps the two primary choices in reference order and sign out inside the dialog in a separate area', () => {
    const html = render();
    const dialog = html.slice(html.indexOf('data-testid="profile-completion-dialog"'));
    const actions = dialog.match(/class="v34-s07-actions"[^>]*>([\s\S]*?)<\/div>/u)?.[1] ?? '';
    expect(actions.match(/<button /gu)).toHaveLength(2);
    expect(actions.indexOf('Complete Profile')).toBeLessThan(actions.indexOf('Maybe Later'));
    expect(actions).not.toContain('Sign out');
    expect(dialog).toMatch(/class="v34-s07-session-actions"[^>]*>[\s\S]*?<button[^>]*>Sign out<\/button>/u);
  });

  it('uses the server percentage for the caption and accessible progress indicator', () => {
    for (const completionPercent of [0, 34, 67] as const) {
      const html = render({ ...projection, completionPercent });
      expect(html).toContain(`Profile · ${completionPercent}% complete · S-07`);
      expect(html).toMatch(new RegExp(`role="progressbar"[^>]*aria-valuenow="${completionPercent}"[^>]*aria-valuemin="0"[^>]*aria-valuemax="100"`, 'u'));
      expect(html).toContain(`style="width:${completionPercent}%"`);
    }
  });

  it('retains the approved heading and descriptive close name with the reference explanation', () => {
    const html = render();
    expect(html).toContain('id="profile-completion-dialog-title">Complete your profile</h2>');
    expect(html).toContain('aria-label="Close profile prompt"');
    expect(html).toContain('Add your academic background and interests for more relevant internships, learning and research suggestions. You can do this now or return from Profile at any time.');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-describedby="profile-completion-dialog-description"');
  });

  it('renders the reference home composition under the S-07 prompt with server identity', () => {
    const html = render();
    expect(html).toContain('class="v34-s07-background"');
    expect(html).toContain('data-testid="profile-prompt-background" aria-hidden="true"');
    expect(html).toContain('aria-label="Your Profile · Synthetic Test Student"');
    expect(html).toContain('>SS</span>');
    expect(html).toContain('Your legal journey, in one place.');
    expect(html.match(/class="v34-s07-tile"/gu)).toHaveLength(4);
    expect(html.match(/Preview only/gu)).toHaveLength(4);
    expect(html).toContain('Why complete your profile?');
    expect(html).not.toContain('Aditi');
    expect(html).not.toContain('data-screen="S-14"');
    expect(html).not.toContain('data-testid="profile-completion-card"');
  });

  it('derives email and limited-access notices from the server projection', () => {
    expect(render()).toContain('Institutional email not verified yet, so some listings stay locked.');
    const verified = render({ ...projection, institutionalEmailStatus: 'verified' });
    expect(verified).toContain('Institutional email verified.');
    expect(verified).not.toContain('Verify Now');
    const limited = render({ ...projection, accessMode: 'limited', disabledCapabilities: ['community', 'sharing'], guardian: { required: true, status: 'required_pending' } });
    expect(limited).toContain('Community and sharing stay off until guardian consent is recorded.');
    expect(limited).toContain('Guardian Consent');
  });

  it('preserves the immediate dashboard continuation for server-dismissed or complete profiles', () => {
    const dismissed = { ...projection, profilePrompt: { shouldShow: false, dismissedForSession: true } };
    const complete: StudentProfileProjection = { ...projection, isComplete: true, completionPercent: 100 };
    for (const value of [dismissed, complete]) {
      expect(verifiedHomeShouldAutoOpenDashboard(value, false)).toBe(true);
      expect(render(value)).not.toContain('data-testid="profile-completion-dialog"');
    }
    expect(verifiedHomeShouldAutoOpenDashboard(projection, false)).toBe(false);
    expect(verifiedHomeShouldAutoOpenDashboard(dismissed, true)).toBe(false);
    expect(verifiedHomeShouldAutoOpenDashboard(undefined, false)).toBe(false);
  });
});
