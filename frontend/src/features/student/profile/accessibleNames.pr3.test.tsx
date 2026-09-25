import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ProfileSetupFrame, ProfileCompleteView, EmailIdentityPanelView } from './ProfileScreens';
import { ProfileSummaryFrame, ProfileSummaryView } from './ProfileSummaryView';
import { ProfileResumeView } from './ProfileResumeView';
import { DashboardFrame } from '../dashboard/DashboardView';
import { EmailVerificationFrame } from '../auth/EmailVerificationView';
import { GuardianConsentFrame } from '../auth/GuardianConsentView';
import { S06R2, type S06R2State } from '../auth/S06R2';
import type { StudentProfileProjection } from '../lib/profileApi';

const projection: StudentProfileProjection = {
  profileVersion: 1, completionVersion: 'v1', completionPercent: 67,
  completedSections: ['personal', 'academic'], missingRequirements: ['interests.goals'],
  nextIncompleteSection: 'interests', isComplete: false, accessMode: 'full',
  institutionalEmailStatus: 'not_provided', disabledCapabilities: [],
  guardian: { required: false, status: 'not_required' },
  profilePrompt: { shouldShow: false, dismissedForSession: true },
  profile: {
    personal: { firstName: 'Synthetic', middleName: null, lastName: 'Student', dateOfBirth: '', preferredLanguage: 'en', city: '', pronouns: null },
    academic: { college: '', yearOfStudy: '', enrolmentNumber: '', institutionalEmail: null, barEnrolmentNumber: null },
    interests: { interests: [], goals: [] },
  },
};
const noop = () => {};
const render = (view: React.ReactNode) => renderToStaticMarkup(<MemoryRouter>{view}</MemoryRouter>);
const avatar = (html: string) => html.match(/<button[^>]*class="v321-profile__avatar"[^>]*aria-label="([^"]*)"[^>]*><span>([^<]*)<\/span>/)!;

describe('PR3 explicit label-in-name regressions (P18/P19/P21)', () => {
  it.each([
    ['Synthetic', null, 'Student'], ['अनन्या', 'कुमारी', 'नायर'],
    ['李', null, '王'], ['Élodie', null, 'Åström'], ['𠮷', null, '野'],
    ['E\u0301lodie', null, 'Ng'], ['', null, ''], [' ', null, ' '],
  ])('all shared headers contain the exact visible initials for %s / %s / %s', (firstName, middleName, lastName) => {
    const personal = { ...projection.profile.personal, firstName: firstName!, middleName, lastName: lastName! };
    const value = { ...projection, profile: { ...projection.profile, personal } };
    const frames = [
      <ProfileSetupFrame step={1} {...personal}>Content</ProfileSetupFrame>,
      <ProfileSetupFrame step={2} {...personal}>Content</ProfileSetupFrame>,
      <ProfileSetupFrame step={3} {...personal}>Content</ProfileSetupFrame>,
      <ProfileCompleteView {...personal} verification="not_provided" />,
      <ProfileResumeView projection={value} />,
      <DashboardFrame projection={value}>Content</DashboardFrame>,
      <EmailVerificationFrame projection={value}>Content</EmailVerificationFrame>,
      <GuardianConsentFrame projection={value} title="Guardian consent">Content</GuardianConsentFrame>,
      <ProfileSummaryFrame projection={value}>Content</ProfileSummaryFrame>,
    ];
    for (const view of frames) {
      const [, name, visible] = avatar(render(view));
      expect(name.startsWith(`${visible} · Your Profile`)).toBe(true);
      expect(name).not.toMatch(/undefined|null/);
    }
  });
  it('names all projection-unavailable fallback avatars without invented identity', () => {
    for (const view of [<ProfileSummaryFrame>Content</ProfileSummaryFrame>, <DashboardFrame>Content</DashboardFrame>, <EmailVerificationFrame>Content</EmailVerificationFrame>, <GuardianConsentFrame title="Checking">Content</GuardianConsentFrame>]) {
      expect(avatar(render(view)).slice(1)).toEqual(['P · Your Profile', 'P']);
    }
  });
  it('Privacy Centre has its visible name and keeps the same control', () => {
    const html = render(<ProfileSummaryView projection={projection} emailManagement={null}>{null}</ProfileSummaryView>);
    expect(html).toContain('aria-label="Privacy Centre"');
    expect(html).not.toContain('aria-label="Privacy &amp; settings"');
  });
  it('all email action names contain the contiguous visible words, including Make primary', () => {
    const html = render(<EmailIdentityPanelView channelEnabled maxIdentities={3} identities={[{ id: 'verified', emailMasked: 's•••@example.test', state: 'verified', isPrimary: false, verification: { status: 'none', expiresInSeconds: null, resendInSeconds: null, attemptsLeft: null } }]} draftEmail="" draftCodes={{}} error={null} errorTarget={null} busy={false} onDraftEmail={noop} onAdd={noop} onDraftCode={noop} onVerify={noop} onResend={noop} onRemove={noop} onPrimary={noop} />);
    for (const [, name, visible] of html.matchAll(/<button[^>]*aria-label="([^"]*)"[^>]*>([^<]*)<\/button>/g)) {
      expect(name.toLowerCase()).toContain(visible.toLowerCase());
    }
  });
});

describe('PR3 S-06 landmark regression (P7)', () => {
  it.each<S06R2State>(['entry', 'invalidnum', 'submitting', 'challenge', 'wrong', 'cooldown', 'expired', 'locked', 'neterr', 'success'])('brand is readable content, not a nested complementary landmark: %s', state => {
    const html = render(<S06R2 state={state} mobile="" code="" destinationMasked={null} expiresInSeconds={null} resendInSeconds={null} attemptsLeft={null} lockedForSeconds={null} busy={false} authorityReady resendAllowed={false} onMobileChange={noop} onCodeChange={noop} onSend={noop} onVerify={noop} onResend={noop} onChangeNumber={noop} onBack={noop} onRetry={noop} />);
    expect(html).not.toContain('<aside');
    expect(html).not.toContain('role="complementary"');
    expect(html).toContain('<div class="s06-r2__brand">');
    expect(html).toContain('Keep your law-school record in one place.');
    expect(html).toContain('data-screen="S-06"');
  });
});
