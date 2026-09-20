import { useSyncExternalStore, type ReactNode } from 'react';
import { matchPath, Navigate, useLocation } from 'react-router-dom';
import {
  hasRole,
  useAuth,
  useStudentSession,
  type AuthState,
  type StudentSessionPhase,
} from './authContext';
import { screenRoutes } from './screenRegistry';
import type { DisabledProfileCapability } from '../features/student/lib/profileApi';
import { useStudentProfileProjection } from '../features/student/profile/profileHooks';
import { hasStudentLogoutFailure, subscribeStudentAuthTransitionNotice } from '../features/student/lib/studentAuthTransitionNotice';

export type StudentRouteDecision =
  | 'allow'
  | 'pending'
  | 'unavailable'
  | 'anonymous'
  | 'wrong_role';

export function studentRouteDecision(
  phase: StudentSessionPhase,
  auth: AuthState,
): StudentRouteDecision {
  if (phase === 'pending') return 'pending';
  if (phase === 'unavailable') return 'unavailable';
  if (phase === 'anonymous' || !auth.isAuthenticated) return 'anonymous';
  return hasRole(auth, 'student') ? 'allow' : 'wrong_role';
}

/**
 * Owner-approved student route ownership for Sprint 1.
 *
 * Keep both lists literal and reviewable. A screen that is absent from both
 * lists is not implicitly public: `isProtectedStudentScreen` defaults it to
 * PRIVATE so a new registry entry cannot mount before session discovery merely
 * because its ownership was forgotten.
 */
export const PUBLIC_OR_MIXED_STUDENT_SCREENS = Object.freeze([
  'S-01', 'S-02', 'S-03', 'S-04', 'S-05', 'S-06',
  'S-08', 'S-09',
  'S-20', 'S-21',
  'S-25', 'S-26', 'S-27', 'S-28', 'S-29',
  'S-88', 'S-89',
] as const);

export const EXPLICIT_PRIVATE_STUDENT_SCREENS = Object.freeze([
  'S-07',
  'S-10', 'S-11', 'S-12', 'S-13', 'S-14', 'S-15', 'S-16', 'S-17', 'S-18', 'S-19',
  'S-22', 'S-23', 'S-24',
  'S-30', 'S-31', 'S-32', 'S-33', 'S-34', 'S-35',
  'S-50', 'S-51', 'S-52', 'S-53', 'S-54', 'S-55', 'S-56', 'S-57',
  'S-58', 'S-59', 'S-60', 'S-61', 'S-62', 'S-63', 'S-64', 'S-65',
  'S-82', 'S-83', 'S-84', 'S-85', 'S-86', 'S-87',
  'S-90', 'S-91', 'S-92', 'S-93',
] as const);

const PUBLIC_OR_MIXED_STUDENT_SCREEN_SET: ReadonlySet<string> =
  new Set(PUBLIC_OR_MIXED_STUDENT_SCREENS);

export function isProtectedStudentScreen(screenId: string): boolean {
  return !PUBLIC_OR_MIXED_STUDENT_SCREEN_SET.has(screenId);
}

export function isProtectedStudentPath(pathname: string): boolean {
  const route = screenRoutes.find((candidate) => matchPath(
    { path: candidate.path, end: true, caseSensitive: false },
    pathname,
  ));
  if (route) return isProtectedStudentScreen(route.id);
  // Unknown paths in the student namespace are private too. The router may
  // ultimately render Not Found, but it does so only after the session barrier.
  return /^\/s-[^/]+(?:\/.*)?$/i.test(pathname);
}

const CAPABILITY_ROUTES: ReadonlyArray<{
  path: string;
  capability: DisabledProfileCapability;
}> = [
  { path: '/s-50', capability: 'community' },
  { path: '/s-51', capability: 'community' },
  { path: '/s-52', capability: 'community' },
  { path: '/s-53', capability: 'community' },
  { path: '/s-54', capability: 'community' },
  { path: '/s-85', capability: 'sharing' },
];

export function requiredStudentCapability(pathname: string): DisabledProfileCapability | null {
  return CAPABILITY_ROUTES.find((candidate) => matchPath(
    { path: candidate.path, end: true, caseSensitive: false },
    pathname,
  ))?.capability ?? null;
}

function StudentCapabilityBoundary({
  capability,
  children,
}: {
  capability: DisabledProfileCapability;
  children: ReactNode;
}) {
  const profile = useStudentProfileProjection();
  const location = useLocation();

  if (!profile.data && profile.isPending) {
    return (
      <main className="route-loading" data-testid="student-capability-pending" aria-live="polite">
        Checking your access policy…
      </main>
    );
  }

  if (!profile.data || profile.isError) {
    return (
      <main className="route-loading" data-testid="student-capability-unavailable" role="alert">
        <h1>We could not verify access to this feature</h1>
        <p>The feature remains locked until the server profile responds.</p>
        <button type="button" onClick={() => { void profile.refetch(); }}>
          Retry access check
        </button>
      </main>
    );
  }

  if (profile.data.disabledCapabilities.includes(capability)) {
    return <Navigate to="/s-16" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  return <>{children}</>;
}

export function StudentCapabilityGuard({ children }: { children: ReactNode }) {
  const location = useLocation();
  const capability = requiredStudentCapability(location.pathname);
  if (!capability) return <>{children}</>;
  return <StudentCapabilityBoundary capability={capability}>{children}</StudentCapabilityBoundary>;
}

export function StudentRouteGuard({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const session = useStudentSession();
  const location = useLocation();
  const decision = studentRouteDecision(session.phase, auth);
  const logoutFailed = useSyncExternalStore(subscribeStudentAuthTransitionNotice, hasStudentLogoutFailure, () => false);

  if (decision === 'pending') {
    return (
      <main className="route-loading" data-testid="student-session-pending" aria-live="polite">
        Checking your secure session…
      </main>
    );
  }

  if (decision === 'unavailable') {
    return (
      <main className="route-loading" data-testid="student-session-unavailable" role="alert">
        <h1>We could not verify your session</h1>
        {logoutFailed && <p>Sign out could not be confirmed. Your server session may still be active.</p>}
        <p>Your private student page remains locked until the server responds.</p>
        <button type="button" onClick={() => { void session.refresh(); }}>
          Retry session check
        </button>
      </main>
    );
  }

  if (decision === 'anonymous') {
    return <Navigate to="/s-03" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }

  if (decision === 'wrong_role') {
    return (
      <main className="route-loading" data-testid="student-route-wrong-role" role="alert">
        This signed-in account does not have access to the student workspace.
      </main>
    );
  }

  return <StudentCapabilityGuard>{children}</StudentCapabilityGuard>;
}
