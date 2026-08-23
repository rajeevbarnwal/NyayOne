import { expect, it } from 'vitest';
import {
  STUDENT_AUTH_SESSION_LOCK,
  STUDENT_AUTH_TRANSITION_CHANNEL,
  STUDENT_AUTH_TRANSITION_STARTED_EVENT,
  withStudentAuthRequestLease,
} from './studentBrowserContext';

it('exposes the NyayOne Web-Locks auth barrier contract', () => {
  expect(STUDENT_AUTH_SESSION_LOCK).toBe('nyayone.student.auth-session.v1');
  expect(STUDENT_AUTH_TRANSITION_CHANNEL).toBe('nyayone.student.auth-transition.v2');
  expect(STUDENT_AUTH_TRANSITION_STARTED_EVENT).toBe('nyayone:student-auth-transition-started');
  expect(withStudentAuthRequestLease).toBeTypeOf('function');
});
