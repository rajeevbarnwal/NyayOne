import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ANONYMOUS_AUTH,
  canUseLawyerFeatures,
  evaluateGuard,
  hasRole,
  isStudentVerified,
  deriveAuthState,
  SESSION_MAX_AGE_MS,
  type AuthState,
} from './authContext';
import { InMemoryKvStore } from '../lib/kvStore';
import {
  clearAuthSnapshot,
  saveAuthSnapshot,
  subscribeAuthChange,
} from '../features/auth/lib/authPersistence';
import type { AuthSnapshot, AuthPhase } from '../features/auth/lib/authLifecycle';

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
