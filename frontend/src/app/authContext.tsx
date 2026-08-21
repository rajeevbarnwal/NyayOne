import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { defaultKvStore, type KvStore } from '../lib/kvStore';
import { loadAuthSnapshot, clearAuthSnapshot, subscribeAuthChange } from '../features/auth/lib/authPersistence';
import {
  getStudentSession,
  STUDENT_AUTH_CHANGED_EVENT,
  type StudentSessionActor,
} from '../features/student/lib/registrationApi';

/**
 * Frontend auth-context + route-guard scaffolding (SAATHI-337 / SAATHI-368).
 * Mirrors the backend actor-context contract. Identity is derived from the
 * persisted P0.1 lawyer verification snapshot (secret-free); the server remains
 * authoritative for real authorization — see deriveAuthState for the honest
 * boundary note. S21 rule: lawyer features stay locked until P0.1 verification
 * passes.
 */
// Identity-lifecycle roles (P0.1/P0.2). The legal-workspace functional roles
// (senior_advocate / firm_partner / associate / clerk / billing_admin) are
// authorisation claims within a verified lawyer workspace — see `filingRole`.
export type Role =
  | 'student' | 'tutor' | 'lawyer' | 'admin' | 'moderator' | 'safety_officer' | 'legal_reviewer'
  | 'senior_advocate' | 'firm_partner' | 'associate' | 'clerk' | 'billing_admin';
export type VerificationStatus = 'draft' | 'submitted' | 'needs_info' | 'verified' | 'rejected';

export interface AuthState {
  isAuthenticated: boolean;
  userId: string | null;
  roles: Role[];
  studentVerification: VerificationStatus;
  lawyerVerification: VerificationStatus;
  /**
   * Verified legal-workspace authorisation claim — the functional role a member
   * holds inside a verified lawyer workspace (lawyer / senior_advocate /
   * firm_partner / associate / clerk / billing_admin). Modelled SEPARATELY from
   * the P0.1 identity role; null when there is no verified workspace claim. The
   * downstream actor id is always the opaque `userId` (subject), never this role.
   */
  filingRole: string | null;
  isMinor: boolean;
}

export const ANONYMOUS_AUTH: AuthState = {
  isAuthenticated: false,
  userId: null,
  roles: [],
  studentVerification: 'draft',
  lawyerVerification: 'draft',
  filingRole: null,
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
/** True when a subject id is a stable opaque value (not a masked contact / email / BCI). */
export function isOpaqueSubjectId(subjectId: string | null | undefined, maskedContact: string | null | undefined): boolean {
  const s = (subjectId ?? '').trim();
  if (!s) return false;
  if (s === (maskedContact ?? '')) return false; // must not be the masked contact
  if (s.includes('*') || s.includes('@')) return false; // reject masked contact / email shapes
  return true;
}

export function deriveAuthState(
  store: KvStore = defaultKvStore(),
  now: number = Date.now(),
  options: { allowLegacyClientDemo?: boolean } = {},
): AuthState {
  // Production must never derive identity from a browser-writable snapshot.
  // The opt-in exists only for isolated unit coverage of the retired lawyer
  // prototype and is never passed by application code.
  if (!options.allowLegacyClientDemo) {
    // This runs inside the session refresh subscriber. Publishing another auth
    // event here would recursively start a third anonymous session request.
    clearAuthSnapshot('lawyer', store, { notifyAuthChanged: false });
    return ANONYMOUS_AUTH;
  }
  const snap = loadAuthSnapshot('lawyer', store);
  if (!snap) return ANONYMOUS_AUTH;
  // Snapshot integrity: a record under the lawyer key MUST carry the lawyer role.
  // Storage-key placement is not authorisation — a mismatched role is malformed.
  if (snap.role !== 'lawyer') {
    clearAuthSnapshot('lawyer', store, { notifyAuthChanged: false });
    return ANONYMOUS_AUTH;
  }
  if (now - snap.updatedAt > SESSION_MAX_AGE_MS) return ANONYMOUS_AUTH; // expired session
  const subjectOk = isOpaqueSubjectId(snap.subjectId, snap.destinationMasked);
  // A verified session without a stable opaque subject id is malformed — never
  // fabricate an identity from a masked contact. Clear + deny.
  if (snap.phase === 'verified' && !subjectOk) {
    clearAuthSnapshot('lawyer', store, { notifyAuthChanged: false });
    return ANONYMOUS_AUTH;
  }
  const lawyerVerification: VerificationStatus =
    snap.phase === 'verified' ? 'verified'
    : snap.phase === 'rejected' ? 'rejected'
    : snap.phase === 'manual_review' ? 'needs_info'
    : 'submitted';
  return {
    isAuthenticated: true,
    userId: subjectOk ? snap.subjectId!.trim() : `pending_${snap.phase}`,
    roles: ['lawyer'],
    studentVerification: 'draft',
    lawyerVerification,
    // The verified workspace authorisation claim: an explicit filingRole from the
    // snapshot, else the base verified 'lawyer'. Only populated once verified with
    // a valid opaque subject; unknown values are rejected downstream (never
    // silently upgraded). Absent while unverified.
    filingRole: lawyerVerification === 'verified' && subjectOk ? (snap.filingRole ?? 'lawyer') : null,
    isMinor: false,
  };
}

function studentActorToAuth(actor: StudentSessionActor): AuthState {
  const allowedRoles: Role[] = [
    'student', 'tutor', 'lawyer', 'admin', 'moderator', 'safety_officer', 'legal_reviewer',
  ];
  return {
    isAuthenticated: true,
    userId: actor.sub,
    roles: actor.roles.filter((role): role is Role => allowedRoles.includes(role as Role)),
    studentVerification: actor.student_verification,
    lawyerVerification: 'draft',
    filingRole: null,
    isMinor: actor.is_minor,
  };
}

/**
 * Reactive auth state: re-derives immediately on P0.1 snapshot create / update /
 * clear (in-tab event) and on cross-tab storage changes — no full reload needed.
 */
export function useDerivedAuth(): AuthState {
  const [auth, setAuth] = useState<AuthState>(() => deriveAuthState());
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const actor = await getStudentSession();
        if (active) setAuth(actor ? studentActorToAuth(actor) : deriveAuthState());
      } catch {
        // The server is authoritative. No cookie/session means anonymous unless
        // the separate verified-lawyer snapshot is present.
        if (active) setAuth(deriveAuthState());
      }
    };
    void refresh();
    const unsubscribe = subscribeAuthChange(() => { void refresh(); });
    const onStudentAuthChanged = () => { void refresh(); };
    window.addEventListener(STUDENT_AUTH_CHANGED_EVENT, onStudentAuthChanged);
    return () => {
      active = false;
      unsubscribe();
      window.removeEventListener(STUDENT_AUTH_CHANGED_EVENT, onStudentAuthChanged);
    };
  }, []);
  return auth;
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
