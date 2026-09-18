import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ProfileResumeView } from './ProfileResumeView';
import { profileResumeDestination } from './profileHooks';
import type { ProfileSection, StudentProfileProjection } from '../lib/profileApi';

const projection: StudentProfileProjection = {
  profileVersion: 4, completionVersion: 'v1', completionPercent: 67,
  completedSections: ['personal', 'academic'], missingRequirements: ['interests.goals'],
  nextIncompleteSection: 'interests', isComplete: false, accessMode: 'full',
  institutionalEmailStatus: 'not_provided', disabledCapabilities: [],
  guardian: { required: false, status: 'not_required' },
  profilePrompt: { shouldShow: false, dismissedForSession: true },
  profile: {
    personal: { firstName: 'Synthetic', middleName: null, lastName: 'Student', dateOfBirth: '', preferredLanguage: null, city: null, pronouns: null },
    academic: { college: null, yearOfStudy: null, enrolmentNumber: null, institutionalEmail: null, barEnrolmentNumber: null },
    interests: { interests: [], goals: [] },
  },
};
const render = (value = projection) => renderToStaticMarkup(<MemoryRouter><ProfileResumeView projection={value} /></MemoryRouter>);

describe('NYAY-60 S-13 Revision L resume presentation', () => {
  it('renders the reference hierarchy and all three resume/dashboard actions', () => {
    const html = render();
    for (const value of ['data-screen="S-13"', 'id="S-13-title"', 'Welcome back', 'Pick up where you left off.', 'Complete Your Profile', '>Finish</button>', '>Resume Setup</button>', '>Not Now</button>', 'Personal · Academic', 'Interests (step 3)']) expect(html).toContain(value);
    expect(html).not.toMatch(/Aditi|Nair|9:41|Browse first|Continue here/u);
  });
  it.each([0, 34, 67, 100] as const)('uses the server percentage %s without deriving authority from the visual ring', percent => {
    const html = render({ ...projection, completionPercent: percent });
    expect(html).toContain(`aria-valuenow="${percent}"`);
    expect(html).toContain(`>${percent}%</b>`);
    expect(html).toContain(`--resume-progress:${percent}%`);
  });
  it.each([
    ['personal', [], '/s-10?section=personal', 'Personal (step 1)'],
    ['academic', ['personal'], '/s-10?section=academic', 'Academic (step 2)'],
    ['interests', ['personal', 'academic'], '/s-11', 'Interests (step 3)'],
  ] as [ProfileSection, ProfileSection[], string, string][])('preserves the server-selected %s resume destination and truthful saved/remaining rows', (section, completed, route, label) => {
    const value = { ...projection, nextIncompleteSection: section, completedSections: completed };
    expect(profileResumeDestination(value)).toBe(route);
    const html = render(value);
    expect(html).toContain(label);
    expect(html).toContain(`data-next-section="${section}"`);
    if (!completed.length) expect(html).toContain('>None yet</b>');
  });
  it('does not offer Finish or claim interests remain for a completed profile', () => {
    const value: StudentProfileProjection = { ...projection, isComplete: true, completionPercent: 100, completedSections: ['personal', 'academic', 'interests'], nextIncompleteSection: null };
    expect(profileResumeDestination(value)).toBe('/s-14');
    const html = render(value);
    expect(html).toContain('Your setup is complete');
    expect(html).toContain('Open dashboard');
    expect(html).toContain('>None</b>');
    expect(html).not.toContain('>Finish</button>');
    expect(html).not.toContain('Complete Your Profile');
  });
  it('keeps profile reads, loading/error behavior and read-only navigation intact', () => {
    const source = readFileSync('src/features/student/profile/ProfileScreens.tsx', 'utf8');
    const resume = source.slice(source.indexOf('export function ProfileResume()'), source.indexOf('/** S-12 presentation'));
    expect(resume).toContain('useStudentProfileProjection()');
    expect(resume).toContain('if (!query.data) return <ProfileLoadState screenId="S-13"');
    expect(resume).toContain('projection={query.data}');
    const view = readFileSync('src/features/student/profile/ProfileResumeView.tsx', 'utf8');
    expect(view).toContain('nav(profileResumeDestination(projection))');
    expect(view).toContain("nav('/s-14')");
    expect(view).toContain("nav('/s-17')");
    expect(view).not.toMatch(/mutate|localStorage|sessionStorage|setTimeout/u);
  });
  it('owns only the canonical S-13 shell with scoped responsive styles', () => {
    expect(readFileSync('src/components/shell/AppShell.tsx', 'utf8')).toContain("if (location.pathname === '/s-13')");
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    for (const value of [".v321-profile[data-screen='S-13']", '.v321-profile-resume__card', '.v321-profile-resume__ring', 'width: 52px', 'height: 52px', '.v321-profile-resume__row']) expect(css).toContain(value);
  });
});
