import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { CompletionCard } from './ProfileScreens';
import { profileResumeDestination, profileSaveDestination } from './profileHooks';
import { verifiedHomeShouldAutoOpenDashboard } from '../auth/V34Screens';
import type { ProfileSection, StudentProfileProjection } from '../lib/profileApi';

const projection: StudentProfileProjection = {
  profileVersion: 4, completionVersion: 'v1', completionPercent: 67,
  completedSections: ['personal', 'academic'], missingRequirements: ['interests.goals'],
  nextIncompleteSection: 'interests', isComplete: false, accessMode: 'full',
  institutionalEmailStatus: 'not_provided', disabledCapabilities: [],
  guardian: { required: false, status: 'not_required' },
  profilePrompt: { shouldShow: true, dismissedForSession: false },
  profile: {
    personal: { firstName: 'Synthetic', middleName: null, lastName: 'Student', dateOfBirth: '',
      preferredLanguage: null, city: null, pronouns: null },
    academic: { college: null, yearOfStudy: null, enrolmentNumber: null,
      institutionalEmail: null, barEnrolmentNumber: null },
    interests: { interests: [], goals: [] },
  },
};
const source = (path: string) => readFileSync(join(process.cwd(), 'src', path), 'utf8');
const profileSource = source('features/student/profile/ProfileScreens.tsx');
const authSource = source('features/student/auth/V34Screens.tsx');
const prompt = authSource.slice(authSource.indexOf('export function V34VerifiedHome'), authSource.indexOf('export function V34Register'));
const card = (value: StudentProfileProjection) => renderToStaticMarkup(<MemoryRouter><CompletionCard projection={value}/></MemoryRouter>);

describe('NYAY-10 completion UX contracts', () => {
  for (const [section, route] of [['personal','/s-10?section=personal'],['academic','/s-10?section=academic'],['interests','/s-11']] as [ProfileSection,string][]) {
    it(`completion card exposes a resumable server-selected ${section} destination`, () => {
      const html = card({ ...projection, nextIncompleteSection: section });
      expect(html).toContain(`href="${route}"`);
      expect(html).toMatch(/>Continue profile<\/a>/u);
    });
  }
  it('server save errors receive programmatic focus without losing form data', () => {
    const block = profileSource.slice(profileSource.indexOf('function SaveError'), profileSource.indexOf('function profileSectionSummary'));
    expect(block).toContain('tabIndex={-1}');
    expect(block).toMatch(/\.current\?\.focus\(\)/u);
    expect(block).not.toMatch(/set(?:FirstName|College|Interests)\(/u);
  });
  it('failed dismissal focuses its accessible error and leaves the dialog open', () => {
    expect(prompt).toContain('ref={dismissErrorRef}');
    expect(prompt).toMatch(/dismissErrorRef\.current\?\.focus\(\)/u);
    expect(prompt).toContain('tabIndex={-1} role="alert" data-testid="profile-save-error"');
  });
  it('the mobile prompt is a bottom sheet, not the desktop-centered overlay', () => {
    const css = source('styles/student-v34.css');
    expect(css).toMatch(/@media\s*\(max-width:\s*600px\)\s*\{[^}]*\.v34-dialog-backdrop\s*\{[^}]*align-items:\s*end/su);
    expect(css).toContain('env(safe-area-inset-bottom)');
  });
  it('completion navigation cannot race an in-flight dismissal', () => {
    expect(prompt).toMatch(/disabled=\{dismiss\.isPending\}[^>]*>Complete Profile</u);
  });
});

describe('NYAY-10 inherited authority preservation', () => {
  it('uses the server percentage unchanged and hides only for server completion', () => {
    expect(card({ ...projection, completionPercent: 34 })).toContain('34%');
    expect(card({ ...projection, isComplete: true, completionPercent: 100 })).toBe('');
  });
  it('server session dismissal bypasses only the prompt, never completion', () => {
    expect(verifiedHomeShouldAutoOpenDashboard(projection, false)).toBe(false);
    expect(verifiedHomeShouldAutoOpenDashboard({ ...projection, profilePrompt:{shouldShow:false,dismissedForSession:true}}, false)).toBe(true);
    expect(verifiedHomeShouldAutoOpenDashboard(projection, true)).toBe(false);
    expect(projection.isComplete).toBe(false);
  });
  it('resume and limited-access navigation remain server-derived', () => {
    expect(profileResumeDestination(projection)).toBe('/s-11');
    expect(profileSaveDestination({ ...projection, accessMode:'limited' },'next')).toBe('/s-16');
  });
  it('dismissal awaits server success before navigation and resets only on error', () => {
    const block = prompt.slice(prompt.indexOf('async function dismissAndContinue'),prompt.indexOf('function trapDialogKeys'));
    expect(block.indexOf('await dismiss.mutateAsync()')).toBeLessThan(block.indexOf('nav(PROFILE_PROMPT_DISMISS_NAVIGATION'));
    expect(block).toMatch(/catch \(error\) \{\s*dismissInFlight.current = false/u);
    expect(block).not.toContain('finally');
  });
  it('keeps keyboard containment and an inert background', () => {
    expect(prompt).toContain("background.setAttribute('inert', '')");
    expect(prompt).toContain("event.key === 'Escape'");
    expect(prompt).toContain("event.key !== 'Tab'");
    expect(prompt).toContain('headingRef.current?.focus()');
    expect(prompt).toContain('aria-modal="true"');
  });
  it('retains explicit conflict review before overwriting a newer server version', () => {
    expect(profileSource).toContain("error.code !== 'profile_version_conflict'");
    expect(profileSource).toContain('Use current version and review my draft');
    expect(profileSource).toContain('expectedProfileVersion: hydratedVersion');
  });
  it('does not add client storage as completion or dismissal authority', () => {
    expect(prompt).not.toMatch(/localStorage|sessionStorage|document\.cookie/u);
    expect(source('features/student/profile/profileHooks.ts')).toContain('captureStudentContextFence');
  });
});
