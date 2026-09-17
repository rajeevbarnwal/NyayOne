import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import * as profileScreens from './ProfileScreens';

const source = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

describe('NYAY-57 S-10 Revision L presentation', () => {
  function frame(step: 1 | 2) {
    return renderToStaticMarkup(createElement(MemoryRouter, null,
      createElement(profileScreens.ProfileSetupFrame, {
        step, firstName: 'Synthetic', middleName: '', lastName: 'Student',
        children: createElement('input', { id: 'preserved-form-control', 'aria-label': 'Preserved field' }),
      })));
  }
  it.each([1, 2] as const)('renders the scoped shell and honest step %s without prototype authority', (step) => {
    const markup = frame(step);
    expect(markup).toContain('data-screen="S-10"');
    expect(markup).toContain('class="v321-profile"');
    expect(markup).toContain('Profile setup');
    expect(markup).toContain(`Profile · step ${step} of 3`);
    expect(markup).toContain(step === 1 ? 'About you.' : 'Your academic record.');
    expect(markup).toContain('NyayOne — Legal, on the record');
    expect(markup).toContain('Your Profile · Synthetic Student');
    expect(markup).toContain('>SS</span>');
    expect(markup).toContain('id="preserved-form-control"');
    expect(markup).toContain('Why complete your profile?');
    expect(markup).not.toMatch(/Aditi|Nair|Mark Fields Corrected|All fields valid|2 fields need attention/u);
    expect(markup).not.toMatch(/data-screen="S-(?:11|12|13|17)"/u);
  });
  it('retains both existing server-backed forms, additional fields and both save destinations', () => {
    const text = source('src/features/student/profile/ProfileScreens.tsx');
    const personal = text.slice(text.indexOf('export function ProfileStep1'), text.indexOf('function AcademicStep'));
    const academic = text.slice(text.indexOf('function AcademicStep'), text.indexOf('export function ProfileStep2'));
    for (const [form, step] of [[personal, 1], [academic, 2]] as const) {
      expect(form).toContain(`<ProfileSetupFrame step={${step}}`);
      expect(form).toContain('<Progress projection={query.data} />');
      expect(form).toContain('<ErrorSummary errors={errors} ids={ids} />');
      expect(form).toContain('<ProfileConflictReview');
      expect(form).toContain('expectedProfileVersion: hydratedVersion');
      expect(form).toContain('nav(profileSaveDestination');
      expect(form).toContain("persist('next')");
      expect(form).toContain("persist('exit')");
      expect(form).toContain('Save & continue');
      expect(form).toContain('Save and exit');
    }
    expect(personal).toContain('profile-personal-date-of-birth');
    expect(personal).toContain('profile-personal-pronouns');
    expect(academic).toContain('profile-academic-email');
    expect(academic).toContain('profile-academic-bar-enrolment');
  });
  it('keeps the icon-bearing first-name label aligned with the middle-name label', () => {
    const css = source('src/styles/student-option321.css');
    const selector = ".v321-profile[data-screen='S-10'] .v321-profile__names .v321-profile__pair .st-field__label";
    const rule = css.slice(css.indexOf(selector)).split('}')[0];
    expect(css).toContain(selector);
    expect(rule).toContain('min-height: 24px');
    // The generic icon label is 20px; the name pair must not inherit that
    // shorter label and lift only the first input four pixels above its peer.
    expect(css.indexOf(selector)).toBeGreaterThan(css.indexOf('.v321-profile__icon-field .st-field__label'));
  });
  it('matches the adjacent last-name label height without shifting the language/city inputs', () => {
    const css = source('src/styles/student-option321.css');
    const lastName = ".v321-profile[data-screen='S-10'] .v321-profile__names > .st-field > .st-field__label";
    const languageCity = ".v321-profile[data-screen='S-10'] .v321-profile__names + .v321-profile__pair .st-field__label";
    expect(css.includes(lastName)).toBe(true);
    expect(css.slice(css.indexOf(lastName)).split('}')[0]).toContain('line-height: normal');
    expect(css.includes(languageCity)).toBe(true);
    expect(css.slice(css.indexOf(languageCity)).split('}')[0]).toContain('min-height: 24px');
  });
  it('matches Revision L 22px icon labels only in the S-10 academic view', () => {
    const css = source('src/styles/student-option321.css');
    const selector = ".v321-profile[data-screen='S-10'][data-profile-step='2'] .v321-profile__icon-field .st-field__label";
    expect(css.includes(selector)).toBe(true);
    expect(css.slice(css.indexOf(selector)).split('}')[0]).toContain('min-height: 22px');
  });
});

describe('NYAY-5 server-authoritative frontend boundary', () => {
  it('does not derive persisted profile state or completion from the memory-only draft', () => {
    const screens = source('src/features/student/profile/ProfileScreens.tsx');
    const dashboard = source('src/features/student/dashboard/Dashboard.tsx');
    expect(screens).not.toContain('seedResumeDraft');
    expect(screens).not.toContain('profileTier(');
    expect(dashboard).not.toContain('getProfileDraft');
    expect(dashboard).not.toContain('profileCompletionPct(');
  });

  it('retires every legacy draft-derived routing, completion, and tier authority seam', () => {
    const profile = source('src/features/student/lib/profile.ts');
    const profileStore = source('src/features/student/lib/profileStore.ts');
    const dashboard = source('src/features/student/lib/dashboard.ts');
    const authScreens = source('src/features/student/auth/AuthScreens.tsx');
    expect(profile).not.toContain('export function isStepComplete');
    expect(profile).not.toContain('export function nextIncompleteStep');
    expect(profile).not.toContain('export function isProfileComplete');
    expect(profile).not.toContain('export function profileTier');
    expect(profile).not.toContain('verified_student');
    expect(profileStore).not.toContain('export function seedResumeDraft');
    expect(profileStore).not.toContain("fullName: 'Student'");
    expect(dashboard).not.toContain('export function profileCompletionPct');
    expect(authScreens).not.toContain('updateProfileDraft');
  });

  it('removes fabricated profile percentages and verification labels', () => {
    const v34 = source('src/features/student/auth/V34Screens.tsx');
    const screens = source('src/features/student/profile/ProfileScreens.tsx');
    expect(v34).not.toContain('<b className="v34-stat">82%</b>');
    expect(screens).not.toContain("return isProfileComplete(d) ? 'verified_student' : 'incomplete'");
  });

  it('keeps a form bound to its hydrated version after a conflict refresh', () => {
    const screens = source('src/features/student/profile/ProfileScreens.tsx');
    const conflictDraftStore = source('src/features/student/profile/profileConflictDraftStore.ts');
    const v34 = source('src/features/student/auth/V34Screens.tsx');
    const studentMutation = source('src/features/student/lib/useStudentMutation.ts');
    expect(screens).not.toContain('expectedProfileVersion: query.data.profileVersion');
    expect(screens.match(/expectedProfileVersion: hydratedVersion/gu)).toHaveLength(3);
    expect(screens.match(/setHydratedVersion\(query\.data\.profileVersion\)/gu)).toHaveLength(3);
    expect(screens.match(/const conflictReview = useProfileConflictReview/gu)).toHaveLength(3);
    expect(screens.match(/conflictReview\.capture\(error\)/gu)).toHaveLength(3);
    expect(screens).toContain('setHydratedVersion(conflict.profileVersion);');
    expect(screens).toContain('Current server version {conflict.profileVersion}');
    expect(screens).toContain('Your retained draft:');
    expect(screens).toContain('Use current version and review my draft');
    expect(screens).toContain('Nothing will be overwritten until you explicitly adopt');
    expect(screens.match(/disabled=\{save\.isPending \|\| Boolean\(conflictReview\.conflict\)\}/gu)).toHaveLength(6);
    expect(screens.match(/preserveProfileConflictDraft\(/gu)).toHaveLength(2);
    expect(screens).toContain("takeProfileConflictDraft('academic')");
    expect(screens).toContain("takeProfileConflictDraft('interests')");
    expect(screens.match(/data-testid="profile-conflict-draft-restored"/gu)).toHaveLength(2);
    expect(conflictDraftStore).not.toMatch(/localStorage|sessionStorage|indexedDB|caches\./u);
    expect(screens.match(/isStudentMutationCancellation\(error\)/gu)).toHaveLength(3);
    expect(v34.match(/isStudentMutationCancellation\(error\)/gu)).toHaveLength(1);
    expect(studentMutation).toContain('settleStudentMutationForCaller');
  });

  it('routes every profile surface through the canonical projection adapter', () => {
    for (const path of [
      'src/features/student/auth/V34Screens.tsx',
      'src/features/student/profile/ProfileScreens.tsx',
      'src/features/student/dashboard/Dashboard.tsx',
    ]) {
      expect(source(path), path).toContain('profileApi');
    }

    const settingsApi = source('src/features/student/lib/settingsApi.ts');
    expect(settingsApi).not.toContain("'/api/v1/student/profile'");
    expect(settingsApi).not.toContain('export async function getStudentProfile');
    expect(settingsApi).not.toContain('export async function updateStudentProfile');
  });

  it('keeps S-01 pending until server session discovery settles', () => {
    const v34 = source('src/features/student/auth/V34Screens.tsx');
    const splash = v34.slice(
      v34.indexOf('export function V34Splash'),
      v34.indexOf('const ONBOARDING ='),
    );
    expect(splash).toContain('useStudentSession');
    expect(splash).not.toContain('setTimeout');
    expect(splash).not.toContain('auth.isAuthenticated');
  });

  it('keeps the NYAY-2 and NYAY-19 memory teardown literals intact', () => {
    const boundary = source('src/features/student/lib/studentBrowserContext.ts');
    const hooks = source('src/features/student/profile/profileHooks.ts');
    expect(boundary).toContain('resetProfileDraft();');
    expect(boundary).toContain('clearProfileConflictDraft();');
    expect(boundary).toContain('clearActorSensitiveQueryState();');
    expect(boundary).toContain('studentBrowserContextGeneration += 1;');
    expect(boundary).toContain('export function captureStudentContextFence');
    expect(boundary).toContain('export function isStudentContextFenceCurrent');
    expect(hooks).toContain('onMutate: captureStudentContextFence');
    expect(hooks).toContain('return useStudentMutation(createProjectionMutationOptions');
    expect(hooks.match(/isStudentContextFenceCurrent\(fence\)/gu)).toHaveLength(2);
    expect(boundary).toContain(
      "const ACTOR_INDEPENDENT_QUERY_ROOTS = new Set([\n  'public-credential-verification',\n  'public-internship-risk-labels',\n]);",
    );
  });

  it('projects S-15/S-16 status from the canonical query and sends no email selector', () => {
    const authScreens = source('src/features/student/auth/AuthScreens.tsx');
    const registrationApi = source('src/features/student/lib/registrationApi.ts');
    const profileApi = source('src/features/student/lib/profileApi.ts');
    expect(authScreens).toContain('useStudentProfileProjection');
    expect(authScreens).not.toContain('auth.isMinor');
    expect(authScreens).toContain('useRequestInstitutionalEmailVerification');
    expect(authScreens).not.toContain('Verification link sent');
    expect(registrationApi).not.toContain('requestInstitutionalEmailVerification');
    expect(profileApi).toContain('export async function requestInstitutionalEmailVerification');
    expect(registrationApi).toMatch(/saveAcademicProfile[\s\S]*getStudentProfileProjection[\s\S]*updateAcademicProfile/u);
  });

  it('keeps S-08 registration limited to core identity, mobile, DOB, and consent', () => {
    const v34 = source('src/features/student/auth/V34Screens.tsx');
    const registrationApi = source('src/features/student/lib/registrationApi.ts');
    const registerScreen = v34.slice(
      v34.indexOf('export function V34Register'),
      v34.indexOf('export function V34OtpVerify'),
    );
    const registerInput = registrationApi.slice(
      registrationApi.indexOf('export interface RegisterStudentInput'),
      registrationApi.indexOf('export interface AcademicProfileInput'),
    );
    const registerRequest = registrationApi.slice(
      registrationApi.indexOf('export async function registerStudent'),
      registrationApi.indexOf('export async function verifyStudentOtp'),
    );
    expect(registerScreen).not.toContain('updateProfileDraft');
    expect(registerScreen).not.toContain('INSTITUTIONAL EMAIL');
    expect(registerScreen).not.toContain('COLLEGE OR UNIVERSITY');
    expect(registerScreen).not.toContain('YEAR OF STUDY');
    expect(registerScreen).not.toContain('BAR ENROLMENT');
    expect(registerInput).not.toMatch(/college\??:/u);
    expect(registerRequest).not.toMatch(/college:\s*input\.college/u);
  });
});
