import { describe, expect, it } from 'vitest';
import {
  ANONYMOUS_AUTH,
  canUseLawyerFeatures,
  evaluateGuard,
  hasRole,
  isStudentVerified,
  type AuthState,
} from './authContext';

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
});
