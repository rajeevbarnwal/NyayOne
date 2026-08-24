import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ANONYMOUS_AUTH,
  canUseLawyerFeatures,
  evaluateGuard,
  hasRole,
  isStudentVerified,
  applyStudentSessionDiscovery,
  applyStudentSessionDiscoveryFailure,
  deriveAuthState,
  reduceStudentSessionState,
  SESSION_MAX_AGE_MS,
  type StudentSessionState,
  type AuthState,
} from './authContext';
import { queryClient } from './queryClient';
import { InMemoryKvStore } from '../lib/kvStore';
import {
  clearAuthSnapshot,
  saveAuthSnapshot,
  subscribeAuthChange,
} from '../features/auth/lib/authPersistence';
import type { AuthSnapshot, AuthPhase } from '../features/auth/lib/authLifecycle';
import {
  captureStudentContextFence,
  clearStudentBrowserContext,
  isStudentContextFenceCurrent,
  observeStudentSessionActor,
} from '../features/student/lib/studentBrowserContext';
import {
  captureActiveProfileReauthDraft,
  clearProfileReauthHandoff,
  hasProfileReauthHandoff,
  profileReauthResumeRoute,
  resolveProfileReauthActor,
  restoreCapturedProfileReauthDraft,
  stageActiveProfileReauthDraft,
  takeResolvedProfileReauthDraft,
} from '../features/student/profile/profileReauthHandoff';

const ACTOR_A = '00000000-0000-4000-8000-0000000000a1';
const ACTOR_B = '00000000-0000-4000-8000-0000000000b2';

function retainPersonalDraft(): void {
  stageActiveProfileReauthDraft(Symbol('personal-form'), ACTOR_A, {
    section: 'personal',
    value: {
      firstName: 'Aditi',
      middleName: null,
      lastName: 'Rao',
      dateOfBirth: '2000-01-01',
      preferredLanguage: 'en',
      city: 'Pune',
      pronouns: null,
    },
  });
  const captured = captureActiveProfileReauthDraft();
  clearProfileReauthHandoff();
  restoreCapturedProfileReauthDraft(captured!);
}

const student: AuthState = {
  isAuthenticated: true,
  userId: 'u1',
  roles: ['student'],
  studentVerification: 'verified',
  lawyerVerification: 'draft',
  filingRole: null,
  isMinor: false,
};

afterEach(() => {
  clearProfileReauthHandoff();
  clearStudentBrowserContext();
  queryClient.clear();
  vi.unstubAllGlobals();
});

describe('frontend auth context', () => {
  it('anonymous is not authenticated and guards block', () => {
    expect(ANONYMOUS_AUTH.isAuthenticated).toBe(false);
    expect(evaluateGuard(ANONYMOUS_AUTH, 'authenticated')).toBeTruthy();
  });

  it('verified student passes auth + student-verified guards', () => {
    expect(hasRole(student, 'student')).toBe(true);
    expect(isStudentVerified(student)).toBe(true);
    expect(evaluateGuard(student, 'authenticated')).toBeNull();
    expect(evaluateGuard(student, 'student-verified')).toBeNull();
  });

  it('lawyer features stay locked until P0.1 verified (S21)', () => {
    expect(canUseLawyerFeatures(student)).toBe(false);
    const lawyer: AuthState = { ...student, roles: ['lawyer'], lawyerVerification: 'verified' };
    expect(canUseLawyerFeatures(lawyer)).toBe(true);
    const pending: AuthState = { ...student, roles: ['lawyer'], lawyerVerification: 'submitted' };
    expect(evaluateGuard(pending, 'lawyer-features')).toBeTruthy();
  });

  it('lawyer-features guard matrix: only a verified lawyer is allowed', () => {
    const client: AuthState = { ...student, roles: [], studentVerification: 'draft' };
    const unverifiedLawyer: AuthState = { ...student, roles: ['lawyer'], lawyerVerification: 'submitted' };
    const verifiedLawyer: AuthState = { ...student, roles: ['lawyer'], lawyerVerification: 'verified' };
    // denied
    for (const a of [ANONYMOUS_AUTH, student, client, unverifiedLawyer]) {
      expect(evaluateGuard(a, 'lawyer-features')).toBeTruthy();
    }
    // allowed
    expect(evaluateGuard(verifiedLawyer, 'lawyer-features')).toBeNull();
  });
});

describe('server-authoritative student session discovery', () => {
  const authenticated: StudentSessionState = {
    auth: student,
    phase: 'authenticated',
    generation: 4,
  };

  it('unmounts private authority as soon as a newer discovery begins', () => {
    expect(reduceStudentSessionState(authenticated, {
      type: 'begin',
      generation: 5,
    })).toEqual({
      auth: ANONYMOUS_AUTH,
      phase: 'pending',
      generation: 5,
    });
  });

  it('does not let an older session response overwrite a newer pending probe', () => {
    const pending = reduceStudentSessionState(authenticated, {
      type: 'begin',
      generation: 5,
    });
    expect(reduceStudentSessionState(pending, {
      type: 'resolved',
      generation: 4,
      actor: {
        sub: 'stale-actor',
        roles: ['student'],
        student_profile_id: null,
        student_verification: 'verified',
        is_minor: false,
        consent_state: [],
      },
    })).toBe(pending);
  });

  it('does not let an older session probe rotate browser ownership after a newer actor wins', () => {
    observeStudentSessionActor({ subject: 'actor-B', studentProfileId: 'profile-B' });
    const actorBFence = captureStudentContextFence();
    queryClient.setQueryData(['student-profile'], { owner: 'B' });

    expect(applyStudentSessionDiscovery(4, 5, {
      sub: 'actor-A',
      roles: ['student'],
      student_profile_id: 'profile-A',
      student_verification: 'draft',
      is_minor: false,
      consent_state: ['privacy_notice', 'terms'],
    })).toBe(false);

    expect(isStudentContextFenceCurrent(actorBFence)).toBe(true);
    expect(queryClient.getQueryData(['student-profile'])).toEqual({ owner: 'B' });
  });

  it('distinguishes an unavailable probe from a proven anonymous session', () => {
    const pending: StudentSessionState = {
      auth: ANONYMOUS_AUTH,
      phase: 'pending',
      generation: 6,
    };
    expect(reduceStudentSessionState(pending, {
      type: 'failed',
      generation: 6,
    })).toEqual({
      auth: ANONYMOUS_AUTH,
      phase: 'unavailable',
      generation: 6,
    });
    expect(reduceStudentSessionState(pending, {
      type: 'resolved',
      generation: 6,
      actor: null,
    })).toEqual({
      auth: ANONYMOUS_AUTH,
      phase: 'anonymous',
      generation: 6,
    });
  });

  it('keeps a canonical-401 handoff while anonymous so the user can reauthenticate', () => {
    retainPersonalDraft();

    expect(applyStudentSessionDiscovery(7, 7, null)).toBe(true);

    expect(hasProfileReauthHandoff()).toBe(true);
    expect(profileReauthResumeRoute(ACTOR_A)).toBeNull();
  });

  it('resolves route and values only after authoritative discovery proves the same actor', () => {
    retainPersonalDraft();

    expect(applyStudentSessionDiscovery(8, 8, {
      sub: ACTOR_A,
      roles: ['student'],
      student_profile_id: '00000000-0000-4000-8000-0000000000a2',
      student_verification: 'verified',
      is_minor: false,
      consent_state: ['privacy_notice', 'terms'],
    })).toBe(true);

    expect(profileReauthResumeRoute(ACTOR_A)).toBe('/s-10?section=personal');
    expect(takeResolvedProfileReauthDraft(ACTOR_A, 'personal')).toEqual(expect.objectContaining({
      firstName: 'Aditi',
      city: 'Pune',
    }));
  });

  it('erases the handoff when a different actor or failed session discovery wins', () => {
    retainPersonalDraft();
    expect(applyStudentSessionDiscovery(9, 9, {
      sub: ACTOR_B,
      roles: ['student'],
      student_profile_id: '00000000-0000-4000-8000-0000000000b3',
      student_verification: 'draft',
      is_minor: false,
      consent_state: ['privacy_notice', 'terms'],
    })).toBe(true);
    expect(resolveProfileReauthActor(ACTOR_A)).toBe(false);
    expect(hasProfileReauthHandoff()).toBe(false);

    retainPersonalDraft();
    expect(applyStudentSessionDiscoveryFailure(10, 10)).toBe(true);
    expect(hasProfileReauthHandoff()).toBe(false);
  });
});

describe('retired lawyer snapshot derivation is test-only', () => {
  const legacyDemo = { allowLegacyClientDemo: true } as const;
  const snap = (phase: AuthPhase, updatedAt: number, extra: Partial<AuthSnapshot> = {}): AuthSnapshot => ({
    role: 'lawyer', phase, destinationMasked: '98******10', challenge: null, consentAt: null,
    subjectId: 'subj_ab12cd', updatedAt, ...extra,
  });

  it('anonymous when there is no snapshot', () => {
    const store = new InMemoryKvStore();
    expect(deriveAuthState(store, 1000).isAuthenticated).toBe(false);
    expect(evaluateGuard(deriveAuthState(store, 1000), 'lawyer-features')).toBeTruthy();
  });

  it('a fresh verified snapshot with an opaque subjectId yields a verified lawyer', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('verified', 10_000), store);
    const auth = deriveAuthState(store, 10_000, legacyDemo);
    expect(auth.isAuthenticated).toBe(true);
    expect(auth.roles).toEqual(['lawyer']);
    expect(auth.userId).toBe('subj_ab12cd'); // stable opaque subject, not the masked contact
    expect(auth.userId).not.toBe('98******10');
    expect(canUseLawyerFeatures(auth)).toBe(true);
    expect(evaluateGuard(auth, 'lawyer-features')).toBeNull();
  });

  it('a pending snapshot is authenticated but lawyer features stay locked', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('pending', 10_000), store);
    const auth = deriveAuthState(store, 10_000, legacyDemo);
    expect(auth.isAuthenticated).toBe(true);
    expect(canUseLawyerFeatures(auth)).toBe(false);
    expect(evaluateGuard(auth, 'lawyer-features')).toBeTruthy();
  });

  it('an expired session (stale snapshot) is denied', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('verified', 0), store);
    const auth = deriveAuthState(store, SESSION_MAX_AGE_MS + 1, legacyDemo);
    expect(auth.isAuthenticated).toBe(false);
    expect(evaluateGuard(auth, 'lawyer-features')).toBeTruthy();
  });

  it('a wrong-role snapshot under the lawyer key is malformed → cleared + denied', () => {
    const store = new InMemoryKvStore();
    // a student-role record stored under ls-auth-lawyer must NOT become a lawyer
    store.set('ls-auth-lawyer', { ...snap('verified', 10_000), role: 'student' });
    const auth = deriveAuthState(store, 10_000, legacyDemo);
    expect(auth.isAuthenticated).toBe(false);
    expect(store.get('ls-auth-lawyer')).toBeNull(); // cleared
  });

  it('a verified snapshot without an opaque subjectId is malformed → cleared + denied', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('verified', 10_000, { subjectId: null }), store);
    expect(deriveAuthState(store, 10_000, legacyDemo).isAuthenticated).toBe(false);
    expect(store.get('ls-auth-lawyer')).toBeNull();
  });

  it('never fabricates identity from a masked contact / email subjectId', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('verified', 10_000, { subjectId: '98******10' }), store);
    expect(deriveAuthState(store, 10_000, legacyDemo).isAuthenticated).toBe(false); // masked contact is not a subject id
    const store2 = new InMemoryKvStore();
    saveAuthSnapshot(snap('verified', 10_000, { subjectId: 'user@example.com' }), store2);
    expect(deriveAuthState(store2, 10_000, legacyDemo).isAuthenticated).toBe(false);
  });

  it('reactive source: verification unlocks and logout/clear immediately re-locks (no reload)', () => {
    const store = new InMemoryKvStore();
    // before verification → denied
    expect(evaluateGuard(deriveAuthState(store, 10_000), 'lawyer-features')).toBeTruthy();
    // P0.1 completes in-SPA → derive immediately reflects verified (live, no reload)
    saveAuthSnapshot(snap('verified', 10_000), store);
    expect(evaluateGuard(deriveAuthState(store, 10_000, legacyDemo), 'lawyer-features')).toBeNull();
    // logout/clear → immediately re-locked
    clearAuthSnapshot('lawyer', store);
    expect(deriveAuthState(store, 10_000).isAuthenticated).toBe(false);
    expect(evaluateGuard(deriveAuthState(store, 10_000), 'lawyer-features')).toBeTruthy();
  });

  it('production rejects and erases even a valid-looking client snapshot', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('verified', 10_000), store);
    expect(deriveAuthState(store, 10_000)).toEqual(ANONYMOUS_AUTH);
    expect(store.get('ls-auth-lawyer')).toBeNull();
  });

  it('settles the anonymous StrictMode bootstrap without a third session refresh', () => {
    const browserWindow = new EventTarget();
    vi.stubGlobal('window', browserWindow);
    const store = new InMemoryKvStore();
    store.set('ls-auth-lawyer', snap('verified', 10_000));
    let sessionGetCount = 0;
    let authEventCount = 0;
    const refresh = () => {
      authEventCount += 1;
      sessionGetCount += 1;
    };
    const unsubscribe = subscribeAuthChange(refresh);

    // React.StrictMode performs the effect setup twice in development.
    sessionGetCount += 2;
    expect(sessionGetCount).toBe(2);

    // The active anonymous completion derives and retires the forbidden legacy
    // snapshot without publishing AUTH_CHANGE_EVENT back into the subscriber.
    for (let index = 0; index < 3; index += 1) {
      expect(deriveAuthState(store, 10_000)).toEqual(ANONYMOUS_AUTH);
    }
    expect(store.get('ls-auth-lawyer')).toBeNull();
    expect(authEventCount).toBe(0);
    expect(sessionGetCount).toBe(2);

    // Explicit auth mutations still notify exactly once.
    clearAuthSnapshot('lawyer', store);
    expect(authEventCount).toBe(1);
    expect(sessionGetCount).toBe(3);
    unsubscribe();
  });

  it('silently retires every invalid derive-time lawyer snapshot path', () => {
    const browserWindow = new EventTarget();
    vi.stubGlobal('window', browserWindow);
    let authEventCount = 0;
    const unsubscribe = subscribeAuthChange(() => { authEventCount += 1; });
    const cases: Array<{
      snapshot: AuthSnapshot;
      options?: { allowLegacyClientDemo: boolean };
    }> = [
      { snapshot: snap('verified', 10_000) },
      {
        snapshot: { ...snap('verified', 10_000), role: 'student' },
        options: legacyDemo,
      },
      {
        snapshot: snap('verified', 10_000, { subjectId: null }),
        options: legacyDemo,
      },
    ];

    for (const entry of cases) {
      const store = new InMemoryKvStore();
      store.set('ls-auth-lawyer', entry.snapshot);
      expect(deriveAuthState(store, 10_000, entry.options)).toEqual(ANONYMOUS_AUTH);
      expect(store.get('ls-auth-lawyer')).toBeNull();
    }
    expect(authEventCount).toBe(0);
    unsubscribe();
  });
});
