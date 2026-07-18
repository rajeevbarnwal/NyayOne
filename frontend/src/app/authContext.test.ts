import { describe, expect, it } from 'vitest';
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
import { saveAuthSnapshot } from '../features/auth/lib/authPersistence';
import type { AuthSnapshot, AuthPhase } from '../features/auth/lib/authLifecycle';

const student: AuthState = {
  isAuthenticated: true,
  userId: 'u1',
  roles: ['student'],
  studentVerification: 'verified',
  lawyerVerification: 'draft',
  isMinor: false,
};

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

describe('deriveAuthState from persisted lawyer snapshot', () => {
  const snap = (phase: AuthPhase, updatedAt: number): AuthSnapshot => ({
    role: 'lawyer', phase, destinationMasked: '98******10', challenge: null, consentAt: null, updatedAt,
  });

  it('anonymous when there is no snapshot', () => {
    const store = new InMemoryKvStore();
    expect(deriveAuthState(store, 1000).isAuthenticated).toBe(false);
    expect(evaluateGuard(deriveAuthState(store, 1000), 'lawyer-features')).toBeTruthy();
  });

  it('a fresh verified snapshot yields a verified lawyer that passes the guard', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('verified', 10_000), store);
    const auth = deriveAuthState(store, 10_000);
    expect(auth.isAuthenticated).toBe(true);
    expect(auth.roles).toEqual(['lawyer']);
    expect(canUseLawyerFeatures(auth)).toBe(true);
    expect(evaluateGuard(auth, 'lawyer-features')).toBeNull();
  });

  it('a pending snapshot is authenticated but lawyer features stay locked', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('pending', 10_000), store);
    const auth = deriveAuthState(store, 10_000);
    expect(auth.isAuthenticated).toBe(true);
    expect(canUseLawyerFeatures(auth)).toBe(false);
    expect(evaluateGuard(auth, 'lawyer-features')).toBeTruthy();
  });

  it('an expired session (stale snapshot) is denied', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(snap('verified', 0), store);
    const auth = deriveAuthState(store, SESSION_MAX_AGE_MS + 1);
    expect(auth.isAuthenticated).toBe(false);
    expect(evaluateGuard(auth, 'lawyer-features')).toBeTruthy();
  });
});
