import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { Dashboard } from './Dashboard';
import type { StudentProfileProjection } from '../lib/profileApi';

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
function render(value = projection) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['student-profile-projection'], value);
  client.setQueryData(['calendar', 'view-preferences'], { timezone: 'Asia/Kolkata' });
  client.setQueryData(['calendar', 'dashboard-events', 'Asia/Kolkata'], { items: [] });
  const html = renderToStaticMarkup(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/s-14']}><Dashboard /></MemoryRouter></QueryClientProvider>);
  client.clear();
  return html;
}

describe('NYAY-61 S-14 Revision L dashboard presentation', () => {
  it('renders advancing product dates rather than importing the fixed conformance date', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2026-01-01T09:00:00Z'));
      expect(render()).toContain('Thursday, 1 January');
      vi.setSystemTime(new Date('2026-01-02T09:00:00Z'));
      expect(render()).toContain('Friday, 2 January');
    } finally { vi.useRealTimers(); }
  });
  it('renders the approved hierarchy with server-derived identity, not prototype claims', () => {
    const html = render();
    for (const value of ['data-screen="S-14"', 'id="S-14-title"', 'Your legal journey, in one place.', 'Complete Your Profile', '>Finish</a>', 'Moot Court', 'Research', 'Mentors', 'Your Profile · Synthetic Student']) expect(html).toContain(value);
    expect(html).not.toMatch(/Aditi|Nair|9:41|Saturday, 16 August|3 new matches|Meera Krishnan|Wed 6:30|Memorial workspace/u);
  });
  it.each([0, 34, 67, 100] as const)('uses the server percentage %s without substituting prototype progress', percent => {
    const html = render({ ...projection, completionPercent: percent });
    expect(html).toContain(`aria-valuenow="${percent}"`);
    expect(html).toContain(`--dashboard-progress:${percent}%`);
    expect(html).toContain(`>${percent}%</b>`);
  });
  it.each([
    ['personal', '/s-10?section=personal'], ['academic', '/s-10?section=academic'], ['interests', '/s-11'],
  ] as const)('retains the server-selected %s completion destination', (section, path) => {
    expect(render({ ...projection, nextIncompleteSection: section })).toContain(`href="${path}"`);
  });
  it('hides the completion card only when the server says complete', () => {
    expect(render({ ...projection, isComplete: true, completionPercent: 100, nextIncompleteSection: null })).not.toContain('data-testid="profile-completion-card"');
    expect(render({ ...projection, completionPercent: 100 })).toContain('data-testid="profile-completion-card"');
  });
  it('uses the actual verification status and preserves the verification route', () => {
    const html = render();
    expect(html).toContain('Institutional email not verified yet');
    expect(html).toContain('href="/s-15"');
    const verified = render({ ...projection, institutionalEmailStatus: 'verified' });
    expect(verified).toContain('Institutional email verified');
    expect(verified).not.toContain('Verify Now');
  });
  it('retains calendar, momentum and every released module without enabling unreleased capabilities', () => {
    const html = render();
    for (const value of ['Unified calendar this week', 'Open calendar', 'Next actions across modules', 'profile-momentum-percent', 'Clinical Hours', 'Community', 'Exam Prep', 'Coming soon']) expect(html).toContain(value);
    expect(html).toMatch(/disabled=""[^>]*class="v321-dashboard__tile"[^>]*>[\s\S]*?Moot Court/u);
    expect(html).toMatch(/disabled=""[^>]*class="v321-dashboard__tile"[^>]*>[\s\S]*?Research/u);
  });
  it('retains server-issued community restrictions and limited-access disclosure', () => {
    const html = render({ ...projection, accessMode: 'limited', disabledCapabilities: ['community', 'sharing'] });
    expect(html).toContain('Limited access.');
    expect(html).toContain('href="/s-16"');
    expect(html).toContain('Community — restricted by your server-issued access policy');
  });
  it('owns only the canonical S-14 shell and preserves dismissal focus, query and calendar authority', () => {
    expect(readFileSync('src/components/shell/AppShell.tsx', 'utf8')).toContain("if (location.pathname === '/s-14')");
    const source = readFileSync('src/features/student/dashboard/Dashboard.tsx', 'utf8');
    for (const value of ['useStudentProfileProjection()', 'getCalendarViewPreferences', 'listCalendarEvents({ timezone })', 'focusProfilePromptDestination', 'headingRef.current?.focus()', 'profileQuery.refetch()']) expect(source).toContain(value);
    expect(readFileSync('src/styles/student-option321.css', 'utf8')).toContain(".v321-profile[data-screen='S-14']");
  });
  it('uses the exact Revision L brief/moot/book paths and a sequential tile heading level', () => {
    const html = render();
    for (const value of ['M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3.5 12h17', 'M6 11.5a6 6 0 0 0 12 0M12 17.5V20', 'M5 4.5h6a2 2 0 0 1 2 2V20a2 2 0 0 0-2-1.5H5zM19 4.5h-6a0 0 0 0 0 0 0V20a2 2 0 0 1 2-1.5h4z']) expect(html).toContain(`d="${value}"`);
    expect(html.match(/role="heading" aria-level="2"/g)).toHaveLength(4);
  });
});
