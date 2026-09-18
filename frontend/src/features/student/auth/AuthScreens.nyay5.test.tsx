import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { StudentProfileProjection } from '../lib/profileApi';
import { STUDENT_PROFILE_QUERY_KEY } from '../profile/profileHooks';
import { EmailVerify, RestrictedDashboard } from './AuthScreens';
import {
  PROFILE_PROMPT_DISMISS_NAVIGATION,
  V34VerifiedHome,
  verifiedHomeShouldAutoOpenDashboard,
} from './V34Screens';

const PROJECTION: StudentProfileProjection = {
  profileVersion: 4,
  completionVersion: 'v1',
  completionPercent: 67,
  completedSections: ['personal', 'academic'],
  missingRequirements: ['interests.interests', 'interests.goals'],
  nextIncompleteSection: 'interests',
  isComplete: false,
  institutionalEmailStatus: 'rejected',
  guardian: { required: false, status: 'not_required' },
  accessMode: 'full',
  disabledCapabilities: [],
  profilePrompt: { shouldShow: true, dismissedForSession: false },
  profile: {
    personal: {
      firstName: 'Aditi', middleName: null, lastName: 'Nair',
      dateOfBirth: '2002-03-14', preferredLanguage: 'en', city: 'Pune', pronouns: null,
    },
    academic: {
      college: 'NLSIU', yearOfStudy: '3', enrolmentNumber: 'KA/1234/2023',
      institutionalEmail: 'aditi@example.edu', barEnrolmentNumber: null,
    },
    interests: { interests: [], goals: [] },
  },
};

function renderWithProjection(
  Component: () => React.JSX.Element,
  projection: StudentProfileProjection,
): string {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Number.POSITIVE_INFINITY } },
  });
  client.setQueryData(STUDENT_PROFILE_QUERY_KEY, projection);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter><Component /></MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('NYAY-5 canonical verification and access surfaces', () => {
  it('lets the explicit prompt dismissal restore focus on S-14 and keeps a failed dismissal open', () => {
    const promptHtml = renderWithProjection(() => <V34VerifiedHome />, PROJECTION);
    expect(promptHtml).toContain('data-testid="profile-completion-dialog"');
    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    const verifiedHome = source.slice(
      source.indexOf('export function V34VerifiedHome'),
      source.indexOf('export function V34Register'),
    );
    expect(verifiedHome).toContain(
      'verifiedHomeShouldAutoOpenDashboard(profile.data, dismissInFlight.current)',
    );
    expect(verifiedHome).toContain(
      'nav(PROFILE_PROMPT_DISMISS_NAVIGATION.to, PROFILE_PROMPT_DISMISS_NAVIGATION.options)',
    );

    const dismissedProjection: StudentProfileProjection = {
      ...PROJECTION,
      profilePrompt: { shouldShow: false, dismissedForSession: true },
    };
    expect(verifiedHomeShouldAutoOpenDashboard(dismissedProjection, true)).toBe(false);
    expect(PROFILE_PROMPT_DISMISS_NAVIGATION).toEqual({
      to: '/s-14',
      options: { replace: true, state: { focusProfilePromptDestination: true } },
    });

    // A rejected mutation leaves the authoritative projection unchanged, so
    // the prompt remains mounted and no automatic dashboard navigation begins.
    expect(verifiedHomeShouldAutoOpenDashboard(PROJECTION, false)).toBe(false);

    const dismissalSource = source.slice(
      source.indexOf('async function dismissAndContinue()'),
      source.indexOf('function trapDialogKeys'),
    );
    expect(dismissalSource).not.toMatch(
      /finally\s*\{\s*dismissInFlight\.current = false;/u,
    );
    expect(dismissalSource).toMatch(
      /catch \(error\) \{\s*dismissInFlight\.current = false;/u,
    );
  });

  it('uses only the resolved process-memory handoff before the legacy login fallback', () => {
    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/AuthScreens.tsx'), 'utf8');
    expect(source).toContain("resolvedProfileReauthResumeRoute() ?? '/s-14'");
  });

  it('allows only a non-authorizing request for the saved institutional email', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const html = renderWithProjection(EmailVerify, PROJECTION);

    expect(html).toContain('Request verification review');
    const requestButton = html.match(/<button\b[^>]*>(?:(?!<\/button>)[\s\S])*Request verification review<\/button>/u)?.[0];
    expect(requestButton).toBeDefined();
    expect(requestButton).not.toContain('disabled=""');
    expect(html).not.toContain('Verification link sent');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('keeps the idempotent request action available while the saved email is pending', () => {
    const html = renderWithProjection(EmailVerify, {
      ...PROJECTION,
      institutionalEmailStatus: 'pending',
    });

    expect(html).toContain('Request verification review');
    expect(html).not.toContain('Verification review pending');
    const requestButton = html.match(/<button\b[^>]*>(?:(?!<\/button>)[\s\S])*Request verification review<\/button>/u)?.[0];
    expect(requestButton).toBeDefined();
    expect(requestButton).not.toContain('disabled=""');
  });

  it('renders the exact server-disabled capabilities for limited access', () => {
    const html = renderWithProjection(RestrictedDashboard, {
      ...PROJECTION,
      guardian: { required: true, status: 'required_pending' },
      accessMode: 'limited',
      disabledCapabilities: ['community', 'sharing'],
    });

    expect(html).toContain('Disabled capabilities: community, sharing.');
    expect(html).toContain('Guardian consent is required');
  });
});
