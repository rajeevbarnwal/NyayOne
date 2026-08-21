import { apiFetch, newRequestId } from '../../../lib/apiClient';

// OTP-flow correlation is exclusively server-owned.  The browser receives only
// an HttpOnly cookie and relative, display-safe state from GET /otp/state.  In
// particular, JavaScript never receives or persists registration/login/recovery
// identifiers, counters anchored to wall-clock timestamps, or bearer material.
const RETIRED_SESSION_KEY = 'legalsaathi.student.registration.v2';
const LEGACY_PII_KEY = 'legalsaathi.student.profile.v1';
const RETIRED_STUDENT_AUTH_KEY = 'ls-auth-student';

let registrationAttempt: { body: string; key: string } | null = null;

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

export interface RegisterStudentInput {
  firstName: string;
  middleName: string | null;
  lastName: string;
  mobile: string;
  dob: string;
  policyVersion: string;
  college?: string;
}

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
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, { ...init, headers });
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
    // A rejected authenticated boundary retires any pre-NYAY-4 storage. HTTP
    // 401 alone is insufficient: an incorrect OTP is also 401 and its HttpOnly
    // flow cookie must remain wholly server-owned for retry/resend decisions.
    if (response.status === 401 && detail?.code === 'authentication_required') {
      clearRegistrationSession();
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
  retireBrowserRegistrationState();
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

export async function registerStudent(
  input: RegisterStudentInput,
  idempotencyKey?: string,
): Promise<OtpFlowState> {
  const body = JSON.stringify({
    first_name: input.firstName,
    middle_name: input.middleName,
    last_name: input.lastName,
    mobile: input.mobile,
    dob: input.dob,
    college: input.college || undefined,
    consent: { accepted: true, policy_version: input.policyVersion },
  });
  const explicitKey = idempotencyKey !== undefined;
  if (!explicitKey && registrationAttempt?.body !== body) {
    registrationAttempt = { body, key: newRequestId() };
  }
  const attemptKey = idempotencyKey ?? registrationAttempt?.key ?? newRequestId();

  try {
    const result = await jsonRequest<unknown>(
      '/api/v1/auth/student/register',
      {
        method: 'POST',
        headers: { 'Idempotency-Key': attemptKey },
        body,
      },
    );
    if (!explicitKey && registrationAttempt?.key === attemptKey) {
      registrationAttempt = null;
    }
    return requireOtpFlowState(result);
  } catch (error) {
    // Transport failures retain the same page-memory key so an uncertain
    // request can replay safely. A typed terminal outcome is known and the
    // next user retry is a new logical attempt with a fresh key.
    if (
      !explicitKey
      && error instanceof RegistrationApiError
      && ['idempotency_conflict', 'otp_delivery_failed', 'registration_replay_expired']
        .includes(error.code)
      && registrationAttempt?.key === attemptKey
    ) {
      registrationAttempt = null;
    }
    throw error;
  }
}

export async function verifyStudentOtp(
  code: string,
): Promise<OtpFlowState> {
  const result = await jsonRequest<unknown>('/api/v1/auth/student/otp/verify', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
  return requireOtpFlowState(result);
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
  await jsonRequest('/api/v1/auth/student/profile', {
    method: 'PATCH',
    body: JSON.stringify({
      college: input.college,
      year_of_study: input.yearOfStudy,
      enrolment_number: input.enrolmentNumber,
      institutional_email: input.institutionalEmail,
      bar_enrolment_number: input.barEnrolmentNumber || null,
    }),
  });
}

export async function requestInstitutionalEmailVerification(
  institutionalEmail: string,
): Promise<{ status: string }> {
  return jsonRequest('/api/v1/auth/student/verification/email/request', {
    method: 'POST',
    body: JSON.stringify({
      institutional_email: institutionalEmail.trim(),
    }),
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

export async function verifyLoginOtp(code: string): Promise<OtpFlowState> {
  const result = await jsonRequest<unknown>('/api/v1/auth/student/login/otp/verify', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
  return requireOtpFlowState(result);
}

export async function getStudentSession(): Promise<StudentSessionActor | null> {
  const result = await jsonRequest<{
    authenticated: boolean;
    actor: StudentSessionActor | null;
  }>('/api/v1/auth/student/session', { method: 'GET' });
  // Session discovery is a bootstrap boundary in both directions. An upgraded
  // tab may still contain the retired UUID-bearing sessionStorage entry even
  // when its HttpOnly cookie is valid, so authenticated discovery must retire
  // it just as aggressively as anonymous discovery.
  retireBrowserRegistrationState();
  return result.authenticated ? result.actor : null;
}

export async function logoutStudent(): Promise<void> {
  try {
    await jsonRequest('/api/v1/auth/student/logout', {
      method: 'POST',
      body: JSON.stringify({}),
    });
  } finally {
    retireBrowserRegistrationState();
  }
}

export const STUDENT_AUTH_CHANGED_EVENT = 'legalsaathi:student-auth-changed';

export function notifyStudentAuthChanged(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(STUDENT_AUTH_CHANGED_EVENT));
  }
}

export function clearRegistrationSession(): void {
  registrationAttempt = null;
  retireBrowserRegistrationState();
}

function retireBrowserRegistrationState(): void {
  if (typeof window === 'undefined') return;
  // Delete both the old UUID-bearing session entry and the older PII draft on
  // every boundary crossing. Neither is migrated into a replacement store.
  try {
    window.sessionStorage.removeItem(RETIRED_SESSION_KEY);
  } catch {
    // Storage may be unavailable under strict browser privacy settings. The
    // active reference remains memory-only and is still cleared independently.
  }
  try {
    window.localStorage.removeItem(LEGACY_PII_KEY);
  } catch {
    // Same fail-safe handling for the retired legacy PII draft.
  }
  try {
    window.localStorage.removeItem(RETIRED_STUDENT_AUTH_KEY);
  } catch {
    // The server flow remains authoritative even when storage is inaccessible.
  }
}

// Erase retired browser-persisted registration/PII state as soon as the new
// bundle loads, even if the subsequent server-session probe cannot complete.
retireBrowserRegistrationState();
