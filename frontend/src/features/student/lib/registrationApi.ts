import { newRequestId } from '../../../lib/apiClient';
import { studentApiFetch } from './studentApiClient';
import {
  clearRegistrationAttempt,
  getRegistrationAttempt,
  setRegistrationAttempt,
} from './registrationAttemptStore';
import {
  STUDENT_AUTH_CHANGED_EVENT,
  type StudentAuthTransition,
  clearStudentBrowserContext,
  finishStudentAuthTransition,
  notifyStudentAuthChanged,
  retireLegacyStudentRegistrationState,
  startStudentAuthTransition,
} from './studentBrowserContext';
import {
  getStudentProfileProjection,
  parseStudentProfileProjection,
  updateAcademicProfile,
  type StudentProfileProjection,
} from './profileApi';
import {
  clearProfileReauthHandoff,
  resolveProfileReauthActor,
} from '../profile/profileReauthHandoff';

export const STUDENT_SESSION_TIMEOUT_MS = 10_000;

// OTP-flow correlation is exclusively server-owned.  The browser receives only
// an HttpOnly cookie and relative, display-safe state from GET /otp/state.  In
// particular, JavaScript never receives or persists registration/login/recovery
// identifiers, counters anchored to wall-clock timestamps, or bearer material.
export type OtpFlowStatus = 'pending' | 'verified' | 'authenticated' | 'unavailable';
export type OtpFlowPurpose = 'signup' | 'login' | 'recovery' | null;

export interface OtpFlowState {
  status: OtpFlowStatus;
  purpose: OtpFlowPurpose;
  destinationMasked: string | null;
  attemptsLeft: number | null;
  expiresInSeconds: number | null;
  resendInSeconds: number | null;
  lockedForSeconds: number | null;
  resendAllowed: boolean;
}

export interface OtpVerificationResult extends OtpFlowState {
  onboarding: StudentProfileProjection;
}

interface OtpFlowStateWire {
  status: OtpFlowStatus;
  purpose: OtpFlowPurpose;
  destination_masked: string | null;
  attempts_left: number | null;
  expires_in_seconds: number | null;
  resend_in_seconds: number | null;
  locked_for_seconds: number | null;
  resend_allowed: boolean;
}

const OTP_FLOW_STATE_WIRE_KEYS = [
  'attempts_left',
  'destination_masked',
  'expires_in_seconds',
  'locked_for_seconds',
  'purpose',
  'resend_allowed',
  'resend_in_seconds',
  'status',
] as const;

const OTP_VERIFICATION_WIRE_KEYS = [
  'attempts_left',
  'destination_masked',
  'expires_in_seconds',
  'locked_for_seconds',
  'onboarding',
  'purpose',
  'resend_allowed',
  'resend_in_seconds',
  'status',
] as const;

export interface RegisterStudentInput {
  firstName: string;
  middleName: string | null;
  lastName: string;
  mobile: string;
  dob: string;
  termsAccepted: boolean;
  termsVersion: string;
  privacyNoticeAcknowledged: boolean;
  privacyNoticeVersion: string;
}

export interface RegistrationStartProjection {
  status: 'accepted';
  next: 'otp';
  expiresInSeconds: number;
  resendAfterSeconds: number;
}

interface RegistrationStartWire {
  status: 'accepted';
  next: 'otp';
  expires_in_seconds: number;
  resend_after_seconds: number;
}

const REGISTRATION_START_WIRE_KEYS = [
  'expires_in_seconds',
  'next',
  'resend_after_seconds',
  'status',
] as const;

export interface AcademicProfileInput {
  college: string;
  yearOfStudy: string;
  enrolmentNumber: string;
  institutionalEmail: string;
  barEnrolmentNumber?: string;
}

export interface StudentSessionActor {
  sub: string;
  roles: string[];
  student_profile_id: string | null;
  student_verification: 'draft' | 'verified';
  is_minor: boolean;
  consent_state: string[];
}

export class RegistrationApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly field?: string,
    readonly otpState?: OtpFlowState,
    readonly retryAfterSeconds?: number,
  ) {
    super(code);
  }

  get attemptsLeft(): number | undefined {
    return this.otpState?.attemptsLeft ?? undefined;
  }
}

function isOtpFlowStateWire(value: unknown): value is OtpFlowStateWire {
  if (!value || typeof value !== 'object') return false;
  const state = value as Partial<OtpFlowStateWire>;
  const keys = Object.keys(value as object).sort();
  if (
    keys.length !== OTP_FLOW_STATE_WIRE_KEYS.length
    || !keys.every((key, index) => key === OTP_FLOW_STATE_WIRE_KEYS[index])
    || !['pending', 'verified', 'authenticated', 'unavailable'].includes(String(state.status))
    || typeof state.resend_allowed !== 'boolean'
  ) return false;

  const relative = [
    state.attempts_left,
    state.expires_in_seconds,
    state.resend_in_seconds,
    state.locked_for_seconds,
  ];
  const hasNoCapabilities = state.destination_masked === null
    && relative.every((item) => item === null);

  if (state.status === 'pending') {
    const allRelative = relative.every((item) => Number.isSafeInteger(item) && Number(item) >= 0);
    if (
      !['signup', 'login', 'recovery'].includes(String(state.purpose))
      || typeof state.destination_masked !== 'string'
      || !/^••••••\d{4}$/u.test(state.destination_masked)
      || !allRelative
    ) return false;
    return !state.resend_allowed || (
      state.resend_in_seconds === 0
      && state.locked_for_seconds === 0
      && Number(state.attempts_left) > 0
    );
  }

  if (!hasNoCapabilities || state.resend_allowed) return false;
  if (state.status === 'verified') return state.purpose === 'recovery';
  if (state.status === 'authenticated') {
    return state.purpose === 'signup' || state.purpose === 'login';
  }
  return state.status === 'unavailable' && state.purpose === null;
}

function mapOtpFlowState(value: OtpFlowStateWire): OtpFlowState {
  return {
    status: value.status,
    purpose: value.purpose,
    destinationMasked: value.destination_masked,
    attemptsLeft: value.attempts_left,
    expiresInSeconds: value.expires_in_seconds,
    resendInSeconds: value.resend_in_seconds,
    lockedForSeconds: value.locked_for_seconds,
    resendAllowed: value.resend_allowed,
  };
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit,
  lifecycle: { notifyAuthChanged?: boolean; authTransition?: StudentAuthTransition } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  const response = await studentApiFetch(path, { ...init, headers }, lifecycle);
  const body = (await response.json().catch(() => ({}))) as {
    detail?: { code?: string; field?: string; otp_state?: OtpFlowStateWire } | string;
    error?: {
      code?: string;
      field?: string;
      otp_state?: OtpFlowStateWire;
      detail?: { code?: string; field?: string; otp_state?: OtpFlowStateWire };
    };
  } & T;
  if (!response.ok) {
    const detail = typeof body.detail === 'object'
      ? body.detail
      : body.error?.detail ?? body.error;
    if (
      detail
      && Object.prototype.hasOwnProperty.call(detail, 'otp_state')
      && !isOtpFlowStateWire(detail.otp_state)
    ) {
      throw new RegistrationApiError(502, 'invalid_otp_state');
    }
    throw new RegistrationApiError(
      response.status,
      detail?.code ?? `http_${response.status}`,
      detail?.field,
      detail?.otp_state ? mapOtpFlowState(detail.otp_state) : undefined,
      parseRetryAfterSeconds(response.headers.get('Retry-After')),
    );
  }
  return body;
}

function parseRetryAfterSeconds(value: string | null): number | undefined {
  if (value === null || !/^\d+$/.test(value.trim())) return undefined;
  return Number.parseInt(value, 10);
}

export async function getOtpFlowState(): Promise<OtpFlowState> {
  // Re-run at every reload/bootstrap boundary because tests, embedded webviews,
  // and privacy-restricted browsers may expose Storage after module evaluation.
  retireLegacyStudentRegistrationState();
  const result = await jsonRequest<OtpFlowStateWire>(
    '/api/v1/auth/student/otp/state',
    { method: 'GET' },
  );
  if (!isOtpFlowStateWire(result)) {
    throw new RegistrationApiError(502, 'invalid_otp_state');
  }
  return mapOtpFlowState(result);
}

function requireOtpFlowState(result: unknown): OtpFlowState {
  if (!isOtpFlowStateWire(result)) {
    throw new RegistrationApiError(502, 'invalid_otp_state');
  }
  return mapOtpFlowState(result);
}

function requireOtpVerificationResult(
  result: unknown,
  expectedPurpose: 'login' | 'signup',
): OtpVerificationResult {
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    throw new RegistrationApiError(502, 'invalid_otp_verification_projection');
  }
  const record = result as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  if (
    keys.length !== OTP_VERIFICATION_WIRE_KEYS.length
    || !keys.every((key, index) => key === OTP_VERIFICATION_WIRE_KEYS[index])
  ) {
    throw new RegistrationApiError(502, 'invalid_otp_verification_projection');
  }
  const { onboarding, ...flow } = record;
  if (
    !isOtpFlowStateWire(flow)
    || flow.status !== 'authenticated'
    || flow.purpose !== expectedPurpose
  ) {
    throw new RegistrationApiError(502, 'invalid_otp_verification_projection');
  }
  try {
    return {
      ...mapOtpFlowState(flow),
      onboarding: parseStudentProfileProjection(onboarding),
    };
  } catch {
    throw new RegistrationApiError(502, 'invalid_otp_verification_projection');
  }
}

function requireRegistrationStartProjection(result: unknown): RegistrationStartProjection {
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    throw new RegistrationApiError(502, 'invalid_registration_start_projection');
  }
  const wire = result as Partial<RegistrationStartWire> & Record<string, unknown>;
  const keys = Object.keys(wire).sort();
  const exact = keys.length === REGISTRATION_START_WIRE_KEYS.length
    && keys.every((key, index) => key === REGISTRATION_START_WIRE_KEYS[index]);
  if (
    !exact
    || wire.status !== 'accepted'
    || wire.next !== 'otp'
    || !Number.isSafeInteger(wire.expires_in_seconds)
    || Number(wire.expires_in_seconds) <= 0
    || !Number.isSafeInteger(wire.resend_after_seconds)
    || Number(wire.resend_after_seconds) < 0
  ) {
    throw new RegistrationApiError(502, 'invalid_registration_start_projection');
  }
  return {
    status: 'accepted',
    next: 'otp',
    expiresInSeconds: Number(wire.expires_in_seconds),
    resendAfterSeconds: Number(wire.resend_after_seconds),
  };
}

export async function registerStudent(
  input: RegisterStudentInput,
  idempotencyKey?: string,
): Promise<RegistrationStartProjection> {
  const body = JSON.stringify({
    first_name: input.firstName,
    middle_name: input.middleName,
    last_name: input.lastName,
    mobile: input.mobile,
    dob: input.dob,
    terms_accepted: input.termsAccepted,
    terms_version: input.termsVersion,
    privacy_notice_acknowledged: input.privacyNoticeAcknowledged,
    privacy_notice_version: input.privacyNoticeVersion,
  });
  const explicitKey = idempotencyKey !== undefined;
  if (!explicitKey && getRegistrationAttempt()?.body !== body) {
    setRegistrationAttempt({ body, key: newRequestId() });
  }
  const attemptKey = idempotencyKey ?? getRegistrationAttempt()?.key ?? newRequestId();

  try {
    const result = await jsonRequest<unknown>(
      '/api/v1/auth/student/register',
      {
        method: 'POST',
        headers: { 'Idempotency-Key': attemptKey },
        body,
      },
    );
    if (!explicitKey && getRegistrationAttempt()?.key === attemptKey) {
      clearRegistrationAttempt();
    }
    return requireRegistrationStartProjection(result);
  } catch (error) {
    // Transport failures retain the same page-memory key so an uncertain
    // request can replay safely. A typed terminal outcome is known and the
    // next user retry is a new logical attempt with a fresh key.
    if (
      !explicitKey
      && error instanceof RegistrationApiError
      && ['idempotency_conflict', 'otp_delivery_failed', 'registration_replay_expired']
        .includes(error.code)
      && getRegistrationAttempt()?.key === attemptKey
    ) {
      clearRegistrationAttempt();
    }
    throw error;
  }
}

export async function verifyStudentOtp(
  code: string,
): Promise<OtpVerificationResult> {
  return withStudentAuthTransition(async (transition) => {
    const result = await jsonRequest<unknown>('/api/v1/auth/student/otp/verify', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }, { notifyAuthChanged: false, authTransition: transition });
    return requireOtpVerificationResult(result, 'signup');
  });
}

export async function resendStudentOtp(): Promise<OtpFlowState> {
  const result = await jsonRequest<unknown>('/api/v1/auth/student/otp/resend', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  return requireOtpFlowState(result);
}

export async function saveAcademicProfile(
  input: AcademicProfileInput,
): Promise<void> {
  const current = await getStudentProfileProjection();
  await updateAcademicProfile({
    expectedProfileVersion: current.profileVersion,
    college: input.college,
    yearOfStudy: input.yearOfStudy,
    enrolmentNumber: input.enrolmentNumber,
    institutionalEmail: input.institutionalEmail || null,
    barEnrolmentNumber: input.barEnrolmentNumber || null,
  });
}

export async function startRecovery(mobile: string): Promise<OtpFlowState> {
  const result = await jsonRequest<unknown>(
    '/api/v1/auth/student/recovery/start',
    { method: 'POST', body: JSON.stringify({ mobile }) },
  );
  return requireOtpFlowState(result);
}

export async function verifyRecovery(
  code: string,
): Promise<OtpFlowState> {
  const result = await jsonRequest<unknown>('/api/v1/auth/student/recovery/verify', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
  return requireOtpFlowState(result);
}

export async function completeRecovery(): Promise<OtpFlowState> {
  const result = await jsonRequest<unknown>('/api/v1/auth/student/recovery/complete', {
    method: 'POST',
    body: JSON.stringify({}),
  });
  return requireOtpFlowState(result);
}

export async function startLoginOtp(mobile: string): Promise<OtpFlowState> {
  const result = await jsonRequest<unknown>(
    '/api/v1/auth/student/login/otp/start',
    { method: 'POST', body: JSON.stringify({ mobile }) },
  );
  return requireOtpFlowState(result);
}

export async function verifyLoginOtp(code: string): Promise<OtpVerificationResult> {
  try {
    return await withStudentAuthTransition(async (transition) => {
      const result = await jsonRequest<unknown>('/api/v1/auth/student/login/otp/verify', {
        method: 'POST',
        body: JSON.stringify({ code }),
      }, { notifyAuthChanged: false, authTransition: transition });
      return requireOtpVerificationResult(result, 'login');
    }, {
      preserveProfileReauthHandoff: true,
    });
  } catch (error) {
    clearProfileReauthHandoff();
    throw error;
  }
}

export async function getStudentSession(
  lifecycle: { authTransition?: StudentAuthTransition } = {},
): Promise<StudentSessionActor | null> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort('session_unavailable');
  }, STUDENT_SESSION_TIMEOUT_MS);
  let result: unknown;
  try {
    result = await jsonRequest<{
      authenticated: boolean;
      actor: StudentSessionActor | null;
    }>('/api/v1/auth/student/session', { method: 'GET', signal: controller.signal }, {
      notifyAuthChanged: false,
      authTransition: lifecycle.authTransition,
    });
  } catch (error) {
    if (timedOut) throw new RegistrationApiError(0, 'session_unavailable');
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
  }
  if (isAnonymousStudentSessionProjection(result)) {
    return null;
  }
  if (!isAuthenticatedStudentSessionProjection(result)) {
    throw new RegistrationApiError(502, 'invalid_student_session_projection');
  }
  return result.actor;
}

export async function withStudentAuthTransition<T>(
  operation: (transition: StudentAuthTransition) => Promise<T>,
  options: {
    requireAnonymousAfterSuccess?: boolean;
    preserveProfileReauthHandoff?: boolean;
  } = {},
): Promise<T> {
  const transition = startStudentAuthTransition({
    preserveProfileReauthHandoff: options.preserveProfileReauthHandoff,
  });
  let result: T | undefined;
  let operationError: unknown;
  try {
    await transition.run(async () => {
      try {
        try {
          result = await operation(transition);
        } catch (error) {
          operationError = error;
        }

        if (typeof window !== 'undefined') {
          try {
            const actor = await getStudentSession({ authTransition: transition });
            if (actor !== null) resolveProfileReauthActor(actor.sub);
            if (
              operationError === undefined
              && options.preserveProfileReauthHandoff
              && actor === null
            ) {
              operationError = new RegistrationApiError(
                503,
                'student_reauth_session_unavailable',
              );
            }
            if (
              operationError === undefined
              && options.requireAnonymousAfterSuccess
              && actor !== null
            ) {
              operationError = new RegistrationApiError(
                503,
                'student_auth_transition_not_anonymous',
              );
            }
          } catch (error) {
            if (
              operationError === undefined
              && (options.requireAnonymousAfterSuccess || options.preserveProfileReauthHandoff)
            ) {
              operationError = error;
            }
          }
        }
      } finally {
        // The exclusive lease remains held until the authoritative probe and
        // every result classification above has completed.
      }
    });
  } finally {
    await finishStudentAuthTransition(transition);
  }
  if (operationError !== undefined) throw operationError;
  return result as T;
}

export async function logoutStudent(): Promise<void> {
  await withStudentAuthTransition(async (transition) => {
    await jsonRequest('/api/v1/auth/student/logout', {
      method: 'POST',
      body: JSON.stringify({}),
    }, { notifyAuthChanged: false, authTransition: transition });
  });
}

export { STUDENT_AUTH_CHANGED_EVENT, notifyStudentAuthChanged };

export function clearRegistrationSession(): void {
  clearStudentBrowserContext();
}

function isStudentSessionActor(value: unknown): value is StudentSessionActor {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const actor = value as Partial<StudentSessionActor> & Record<string, unknown>;
  const keys = Object.keys(actor).sort();
  const expectedKeys = [
    'consent_state',
    'is_minor',
    'roles',
    'student_profile_id',
    'student_verification',
    'sub',
  ];
  const acceptedServerRoles = new Set([
    'admin',
    'legal_reviewer',
    'moderator',
    'safety_officer',
    'student',
  ]);
  if (
    keys.length !== expectedKeys.length
    || !keys.every((key, index) => key === expectedKeys[index])
    || !isCanonicalUuid(actor.sub)
  ) return false;
  if (
    !Array.isArray(actor.roles)
    || actor.roles.length !== 1
    || typeof actor.roles[0] !== 'string'
    || !acceptedServerRoles.has(actor.roles[0])
    || (actor.student_verification !== 'draft' && actor.student_verification !== 'verified')
    || typeof actor.is_minor !== 'boolean'
    || !Array.isArray(actor.consent_state)
  ) return false;

  const role = actor.roles[0];
  if (role === 'student') {
    return isCanonicalUuid(actor.student_profile_id)
      && isCanonicalStudentConsentState(actor.consent_state);
  }
  return actor.student_profile_id === null
    && actor.student_verification === 'draft'
    && actor.is_minor === false
    && actor.consent_state.length === 0;
}

function isCanonicalUuid(value: unknown): value is string {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u.test(value);
}

function isCanonicalStudentConsentState(value: unknown[]): value is string[] {
  if (!value.every((item) => typeof item === 'string')) return false;
  return (value.length === 1 && value[0] === 'registration')
    || (value.length === 2 && value[0] === 'privacy_notice' && value[1] === 'terms');
}

function hasExactSessionKeys(
  value: Record<string, unknown>,
): value is { authenticated: unknown; actor: unknown } {
  const keys = Object.keys(value).sort();
  return keys.length === 2 && keys[0] === 'actor' && keys[1] === 'authenticated';
}

function isAnonymousStudentSessionProjection(
  value: unknown,
): value is { authenticated: false; actor: null } {
  return Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
    && hasExactSessionKeys(value as Record<string, unknown>)
    && (value as Record<string, unknown>).authenticated === false
    && (value as Record<string, unknown>).actor === null;
}

function isAuthenticatedStudentSessionProjection(
  value: unknown,
): value is { authenticated: true; actor: StudentSessionActor } {
  return Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
    && hasExactSessionKeys(value as Record<string, unknown>)
    && (value as Record<string, unknown>).authenticated === true
    && isStudentSessionActor((value as Record<string, unknown>).actor);
}

// Erase retired browser-persisted registration/PII state as soon as the new
// bundle loads, even if the subsequent server-session probe cannot complete.
retireLegacyStudentRegistrationState();
