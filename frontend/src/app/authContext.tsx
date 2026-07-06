import { createContext, useContext, useMemo, type ReactNode } from 'react';

/**
 * Frontend auth-context + route-guard scaffolding (SAATHI-337 / SAATHI-368).
 * Mirrors the backend actor-context contract. Real identity is wired to the
 * existing P0.2/P0.1 IdP later; for now a placeholder anonymous context is used.
 * S21 rule: lawyer features stay locked until P0.1 verification passes.
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
