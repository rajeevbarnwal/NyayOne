import {
  exchangeMentorCeremony,
  revokeMentorSession,
  rotateMentorSession,
  verifyMentorIdentity,
  withServerProvenMentorSession,
} from '../../src/features/mentor/lib/mentorCeremonyApi';
import { subscribeStudentAuthTransitions } from '../../src/features/student/lib/studentBrowserContext';

const observed = {
  starts: 0,
  ends: 0,
  unavailable: 0,
  privateMounts: 0,
};

const HARNESS_FAILURE_CODES = new Set([
  'MENTOR_RESPONSE_INVALID',
  'MENTOR_SESSION_POSTCONDITION_FAILED',
  'MENTOR_SESSION_REQUIRED',
  'MENTOR_BROWSER_ORIGIN_UNAVAILABLE',
  'student_auth_transition_active',
  'student_auth_transition_unavailable',
  'student_context_changed',
]);

const subscription = subscribeStudentAuthTransitions({
  onStart: () => { observed.starts += 1; },
  onEnd: () => { observed.ends += 1; },
  onUnavailable: () => { observed.unavailable += 1; },
});

function safeError(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  return HARNESS_FAILURE_CODES.has(code) ? code : 'MENTOR_CLIENT_FAILURE';
}

const lifecycle = {
  expectedSessionState: 'active' as const,
  purposeCode: 'student_guidance' as const,
};

const harness = Object.freeze({
  ready: async () => {
    await subscription.ready;
    return { available: subscription.available, unavailable: observed.unavailable };
  },
  status: () => ({ ...observed }),
  verify: async () => {
    const result = await verifyMentorIdentity({
      expectedCeremonyState: 'challenge_issued',
    }, 'nyay22-browser-verification-key');
    return {
      schema: result.value.schemaVersion,
      status: result.value.status,
      state: result.value.ceremonyState,
      session: result.session?.state ?? 'absent',
    };
  },
  exchange: async () => {
    const result = await exchangeMentorCeremony({
      intent: 'mentor_session',
      expectedCeremonyState: 'proof_verified',
      acceptPurpose: true,
      purposeCode: 'student_guidance',
      consentReceiptVersion: 'mentor-consent.v1',
      acceptanceTextVersion: 'mentor-acceptance.v1',
    }, 'nyay22-browser-exchange-key');
    return { schema: result.value.schemaVersion, state: result.session?.state ?? 'absent' };
  },
  rotate: async () => {
    const result = await rotateMentorSession({
      ...lifecycle,
      reasonCode: 'routine_rotation',
    }, 'nyay22-browser-rotation-key');
    return { schema: result.value.schemaVersion, state: result.session?.state ?? 'absent' };
  },
  revoke: async () => {
    const result = await revokeMentorSession({
      ...lifecycle,
      reasonCode: 'mentor_requested',
    }, 'nyay22-browser-revocation-key');
    return { action: result.value.action, state: result.session?.state ?? 'absent' };
  },
  privateMount: async () => {
    try {
      return await withServerProvenMentorSession((projection) => {
        observed.privateMounts += 1;
        document.body.dataset.privateMounted = 'true';
        return { mounted: true, state: projection.state };
      });
    } catch (error) {
      return { mounted: false, code: safeError(error) };
    }
  },
});

Object.defineProperty(window, 'nyay22Harness', {
  configurable: false,
  enumerable: false,
  writable: false,
  value: harness,
});

document.body.dataset.harnessReady = 'true';
