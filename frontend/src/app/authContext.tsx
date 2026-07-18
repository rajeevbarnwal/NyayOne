import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { defaultKvStore, type KvStore } from '../lib/kvStore';
import { loadAuthSnapshot } from '../features/auth/lib/authPersistence';

/**
 * Frontend auth-context + route-guard scaffolding (SAATHI-337 / SAATHI-368).
 * Mirrors the backend actor-context contract. Identity is derived from the
 * persisted P0.1 lawyer verification snapshot (secret-free); the server remains
 * authoritative for real authorization — see deriveAuthState for the honest
 * boundary note. S21 rule: lawyer features stay locked until P0.1 verification
 * passes.
 */
export type Role = 'student' | 'tutor' | 'lawyer' | 'admin' | 'moderator';
export type VerificationStatus = 'draft' | 'submitted' | 'needs_info' | 'verified' | 'rejected';

export interface AuthState {
  isAuthenticated: boolean;
  userId: string | null;
  roles: Role[];
  studentVerification: VerificationStatus;
  lawyerVerification: VerificationStatus;
  isMinor: boolean;
}

export const ANONYMOUS_AUTH: AuthState = {
  isAuthenticated: false,
  userId: null,
  roles: [],
  studentVerification: 'draft',
  lawyerVerification: 'draft',
  isMinor: false,
};

export function hasRole(auth: AuthState, role: Role): boolean {
  return auth.roles.includes(role);
}
export function isStudentVerified(auth: AuthState): boolean {
  return auth.studentVerification === 'verified';
}
export function canUseLawyerFeatures(auth: AuthState): boolean {
  // S21 gate.
  return auth.roles.includes('lawyer') && auth.lawyerVerification === 'verified';
}

const AuthContext = createContext<AuthState>(ANONYMOUS_AUTH);

export function AuthProvider({ value, children }: { value?: AuthState; children: ReactNode }) {
  const auth = useMemo(() => value ?? ANONYMOUS_AUTH, [value]);
  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

/**
 * Session freshness window mirrored from the P0.3 refresh policy. A persisted
 * verification snapshot older than this is treated as an expired session and
 * denied. (The server is authoritative; this is a client-side derived state.)
 */
export const SESSION_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Derive the live AuthState from the persisted, secret-free lawyer verification
 * snapshot. Anonymous when there is no snapshot or the session has expired.
 *
 * SECURITY NOTE (honest boundary): this is CLIENT-SIDE derived state for gating
 * UI and supplying an actor identity — it is NOT production-grade authorization.
 * The server must remain authoritative for privilege decisions; the service-layer
 * role check (see filingWorkflow.canFinalize) is defence in depth, not a backend.
 */
export function deriveAuthState(store: KvStore = defaultKvStore(), now: number = Date.now()): AuthState {
  const snap = loadAuthSnapshot('lawyer', store);
  if (!snap) return ANONYMOUS_AUTH;
  if (now - snap.updatedAt > SESSION_MAX_AGE_MS) return ANONYMOUS_AUTH; // expired session
  const lawyerVerification: VerificationStatus =
    snap.phase === 'verified' ? 'verified'
    : snap.phase === 'rejected' ? 'rejected'
    : snap.phase === 'manual_review' ? 'needs_info'
    : 'submitted';
  return {
    isAuthenticated: true,
    userId: snap.destinationMasked ?? 'lawyer',
    roles: ['lawyer'],
    studentVerification: 'draft',
    lawyerVerification,
    isMinor: false,
  };
}

export type GuardRule = 'authenticated' | 'student-verified' | 'lawyer-features';

/** Returns null when allowed, or a reason string when the guard blocks access. */
export function evaluateGuard(auth: AuthState, rule: GuardRule): string | null {
  switch (rule) {
    case 'authenticated':
      return auth.isAuthenticated ? null : 'Authentication required';
    case 'student-verified':
      return isStudentVerified(auth) ? null : 'Student verification required';
    case 'lawyer-features':
      return canUseLawyerFeatures(auth)
        ? null
        : 'Lawyer features locked until P0.1 verification is complete';
    default:
      return null;
  }
}
