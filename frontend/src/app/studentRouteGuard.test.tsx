import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ANONYMOUS_AUTH,
  AuthProvider,
  type AuthState,
  type StudentSessionPhase,
} from './authContext';
import {
  EXPLICIT_PRIVATE_STUDENT_SCREENS,
  PUBLIC_OR_MIXED_STUDENT_SCREENS,
  StudentRouteGuard,
  isProtectedStudentScreen,
  isProtectedStudentPath,
  requiredStudentCapability,
  studentRouteDecision,
} from './StudentRouteGuard';
import type { StudentProfileProjection } from '../features/student/lib/profileApi';
import { STUDENT_PROFILE_QUERY_KEY } from '../features/student/profile/profileHooks';

const STUDENT: AuthState = {
  isAuthenticated: true,
  userId: 'opaque-student',
  roles: ['student'],
  studentVerification: 'draft',
  lawyerVerification: 'draft',
  filingRole: null,
  isMinor: false,
};

const FULL_PROFILE: StudentProfileProjection = {
  profileVersion: 4,
  completionVersion: 'v1',
  completionPercent: 100,
  completedSections: ['personal', 'academic', 'interests'],
  nextIncompleteSection: null,
  isComplete: true,
  institutionalEmailStatus: 'not_provided',
  guardian: { required: false, status: 'not_required' },
  accessMode: 'full',
  disabledCapabilities: [],
  profilePrompt: { shouldShow: false, dismissedForSession: false },
  profile: {
    personal: { firstName: 'A', middleName: null, lastName: 'B', dateOfBirth: '2000-01-01', preferredLanguage: 'en', city: 'Pune', pronouns: null },
    academic: { college: 'NLSIU', yearOfStudy: '3', enrolmentNumber: 'KA/1/2023', institutionalEmail: null, barEnrolmentNumber: null },
    interests: { interests: ['Tax'], goals: ['Litigation'] },
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderGuard(
  phase: StudentSessionPhase,
  auth: AuthState = ANONYMOUS_AUTH,
  path = '/s-10?section=personal',
  projection?: StudentProfileProjection,
  child = <div data-private-canary>Private profile</div>,
): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (projection) client.setQueryData(STUDENT_PROFILE_QUERY_KEY, projection);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AuthProvider
        value={auth}
        studentSession={{ phase, refresh: vi.fn(async () => undefined) }}
      >
        <MemoryRouter initialEntries={[path]}>
          <StudentRouteGuard>{child}</StudentRouteGuard>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe('protected student route guard', () => {
  it('uses the approved exhaustive public/private ownership map', () => {
    expect(PUBLIC_OR_MIXED_STUDENT_SCREENS).toEqual([
      'S-01', 'S-02', 'S-03', 'S-04', 'S-05', 'S-06',
      'S-08', 'S-09',
      'S-20', 'S-21',
      'S-25', 'S-26', 'S-27', 'S-28', 'S-29',
      'S-88', 'S-89',
    ]);
    expect(EXPLICIT_PRIVATE_STUDENT_SCREENS).toEqual([
      'S-07',
      'S-10', 'S-11', 'S-12', 'S-13', 'S-14', 'S-15', 'S-16', 'S-17', 'S-18', 'S-19',
      'S-22', 'S-23', 'S-24',
      'S-30', 'S-31', 'S-32', 'S-33', 'S-34', 'S-35',
      'S-50', 'S-51', 'S-52', 'S-53', 'S-54', 'S-55', 'S-56', 'S-57',
      'S-58', 'S-59', 'S-60', 'S-61', 'S-62', 'S-63', 'S-64', 'S-65',
      'S-82', 'S-83', 'S-84', 'S-85', 'S-86', 'S-87',
      'S-90', 'S-91', 'S-92', 'S-93',
    ]);

    for (const screenId of PUBLIC_OR_MIXED_STUDENT_SCREENS) {
      const path = `/${screenId.toLowerCase()}`;
      expect(isProtectedStudentScreen(screenId), screenId).toBe(false);
      expect(isProtectedStudentPath(path), path).toBe(false);
      expect(isProtectedStudentPath(`${path}/`), `${path}/`).toBe(false);
    }
    for (const screenId of EXPLICIT_PRIVATE_STUDENT_SCREENS) {
      const path = `/${screenId.toLowerCase()}`;
      expect(isProtectedStudentScreen(screenId), screenId).toBe(true);
      expect(isProtectedStudentPath(path), path).toBe(true);
      expect(isProtectedStudentPath(`${path}/`), `${path}/`).toBe(true);
    }
  });

  it('defaults every unmapped student screen to private and denies it before mount', () => {
    const childRender = vi.fn();
    function UnmappedChild() { childRender(); return <div data-unmapped-private-canary />; }

    expect(PUBLIC_OR_MIXED_STUDENT_SCREENS).not.toContain('S-36');
    expect(EXPLICIT_PRIVATE_STUDENT_SCREENS).not.toContain('S-36');
    expect(isProtectedStudentScreen('S-36')).toBe(true);
    expect(isProtectedStudentPath('/s-36')).toBe(true);
    const html = renderGuard('anonymous', ANONYMOUS_AUTH, '/s-36', undefined, <UnmappedChild />);
    expect(html).not.toContain('data-unmapped-private-canary');
    expect(childRender).not.toHaveBeenCalled();
  });

  it('leaves every approved anonymous entry route outside the private guard', () => {
    for (const screenId of PUBLIC_OR_MIXED_STUDENT_SCREENS) {
      expect(isProtectedStudentPath(`/${screenId.toLowerCase()}`), screenId).toBe(false);
    }
  });

  it('does not mount private children while session discovery is pending', () => {
    const childRender = vi.fn();
    function PrivateChild() { childRender(); return <div data-private-canary>Private profile</div>; }
    const html = renderGuard('pending', ANONYMOUS_AUTH, '/s-10', undefined, <PrivateChild />);
    expect(html).toContain('data-testid="student-session-pending"');
    expect(html).not.toContain('data-private-canary');
    expect(childRender).not.toHaveBeenCalled();
  });

  it('keeps a failed discovery fail-closed and offers an explicit retry', () => {
    const html = renderGuard('unavailable');
    expect(html).toContain('data-testid="student-session-unavailable"');
    expect(html).toContain('Retry session check');
    expect(html).not.toContain('data-private-canary');
  });

  it('denies every private and unmapped route when Web Locks are unsupported', async () => {
    vi.stubGlobal('window', new EventTarget());
    vi.stubGlobal('document', {});
    vi.stubGlobal('navigator', {});
    vi.stubGlobal('BroadcastChannel', class UnsupportedLocksChannel {});
    vi.resetModules();
    const { subscribeStudentAuthTransitions } = await import(
      '../features/student/lib/studentBrowserContext'
    );
    let phase: StudentSessionPhase = 'pending';
    const subscription = subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: () => { phase = 'unavailable'; },
    });

    expect(subscription.available).toBe(false);
    expect(phase).toBe('unavailable');
    for (const screenId of [...EXPLICIT_PRIVATE_STUDENT_SCREENS, 'S-36']) {
      const childRender = vi.fn();
      function PrivateChild() { childRender(); return <div data-unsupported-private-canary />; }
      const html = renderGuard(
        phase,
        STUDENT,
        `/${screenId.toLowerCase()}`,
        undefined,
        <PrivateChild />,
      );
      expect(html, screenId).toContain('data-testid="student-session-unavailable"');
      expect(html, screenId).not.toContain('data-unsupported-private-canary');
      expect(childRender, screenId).not.toHaveBeenCalled();
    }
  });

  it('permits only a settled authenticated student actor', () => {
    expect(studentRouteDecision('authenticated', STUDENT)).toBe('allow');
    expect(studentRouteDecision('pending', STUDENT)).toBe('pending');
    expect(studentRouteDecision('unavailable', STUDENT)).toBe('unavailable');
    expect(studentRouteDecision('anonymous', ANONYMOUS_AUTH)).toBe('anonymous');
    expect(studentRouteDecision('authenticated', { ...STUDENT, roles: ['moderator'] })).toBe('wrong_role');
    expect(renderGuard('authenticated', STUDENT)).toContain('data-private-canary');
  });

  it('maps only the approved direct capability routes, including trailing slashes', () => {
    for (let number = 50; number <= 54; number += 1) {
      expect(requiredStudentCapability(`/s-${number}`)).toBe('community');
      expect(requiredStudentCapability(`/s-${number}/`)).toBe('community');
    }
    expect(requiredStudentCapability('/s-85')).toBe('sharing');
    expect(requiredStudentCapability('/s-85/')).toBe('sharing');
    for (const control of ['/s-17', '/s-82', '/s-83', '/s-84', '/s-86']) {
      expect(requiredStudentCapability(control), control).toBeNull();
    }
  });

  it('does not mount a direct capability child until its canonical projection settles', () => {
    const childRender = vi.fn();
    function PrivateChild() { childRender(); return <div data-capability-canary />; }
    const html = renderGuard('authenticated', STUDENT, '/s-50/?tab=latest', undefined, <PrivateChild />);
    expect(html).toContain('data-testid="student-capability-pending"');
    expect(html).not.toContain('data-capability-canary');
    expect(childRender).not.toHaveBeenCalled();
  });

  it('denies disabled direct capability routes and permits full-access controls', () => {
    const limited: StudentProfileProjection = {
      ...FULL_PROFILE,
      guardian: { required: true, status: 'required_pending' },
      accessMode: 'limited',
      disabledCapabilities: ['community', 'sharing'],
    };
    expect(renderGuard('authenticated', STUDENT, '/s-50', limited)).not.toContain('data-private-canary');
    expect(renderGuard('authenticated', STUDENT, '/s-85?mode=share', limited)).not.toContain('data-private-canary');
    expect(renderGuard('authenticated', STUDENT, '/s-82', limited)).toContain('data-private-canary');
    expect(renderGuard('authenticated', STUDENT, '/s-50', FULL_PROFILE)).toContain('data-private-canary');
  });
});
