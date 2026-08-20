import { apiFetch, newRequestId } from '../../../lib/apiClient';

// A registration UUID is a pre-authentication OTP correlation reference, not an
// authorization capability. Keep it only in this page-lifetime module slot and
// never persist it in browser storage, cookies or URLs. A reload intentionally
// requires the user to restart signup rather than resurrect a bearer-like UUID.
const RETIRED_SESSION_KEY = 'legalsaathi.student.registration.v2';
const LEGACY_PII_KEY = 'legalsaathi.student.profile.v1';

let onboardingSession: RegistrationSession | null = null;
let registrationAttempt: { body: string; key: string } | null = null;

export interface RegistrationSession {
  registrationId: string;
  destinationMasked: string;
  issuedAt: number;
  isMinor: boolean;
  guardianConsentPending: boolean;
}

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
    readonly attemptsLeft?: number,
  ) {
    super(code);
  }
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, { ...init, headers });
  const body = (await response.json().catch(() => ({}))) as {
    detail?: { code?: string; field?: string; attempts_left?: number } | string;
    error?: {
      code?: string;
      field?: string;
      attempts_left?: number;
      detail?: { code?: string; field?: string; attempts_left?: number };
    };
  } & T;
  if (!response.ok) {
    const detail = typeof body.detail === 'object'
      ? body.detail
      : body.error?.detail ?? body.error;
    // A rejected authenticated boundary is also a revocation signal. Do not
    // leave any pre-auth correlation reference alive after the server denies
    // the browser session. HTTP 401 alone is not sufficient: a normal wrong
    // signup OTP is also 401 and must retain its memory-only correlation value
    // so the user can retry or resend within the server-owned attempt budget.
    if (response.status === 401 && detail?.code === 'authentication_required') {
      clearRegistrationSession();
    }
    throw new RegistrationApiError(
      response.status,
      detail?.code ?? `http_${response.status}`,
      detail?.field,
      detail?.attempts_left,
    );
  }
  return body;
}

export async function registerStudent(
  input: RegisterStudentInput,
  idempotencyKey?: string,
): Promise<{ registration_id: string; status: string }> {
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
    const result = await jsonRequest<{ registration_id: string; status: string }>(
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
    return result;
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
  registrationId: string,
  code: string,
): Promise<void> {
  await jsonRequest('/api/v1/auth/student/otp/verify', {
    method: 'POST',
    body: JSON.stringify({ registration_id: registrationId, code }),
  });
  // Successful signup verification establishes the server-owned authenticated
  // context. The client must no longer retain the registration reference.
  clearRegistrationSession();
}

export async function resendStudentOtp(registrationId: string): Promise<void> {
  await jsonRequest('/api/v1/auth/student/otp/resend', {
    method: 'POST',
    body: JSON.stringify({ registration_id: registrationId }),
  });
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

export async function startRecovery(mobile: string): Promise<string> {
  const result = await jsonRequest<{ recovery_id: string }>(
    '/api/v1/auth/student/recovery/start',
    { method: 'POST', body: JSON.stringify({ mobile }) },
  );
  return result.recovery_id;
}

export async function verifyRecovery(
  recoveryId: string,
  code: string,
): Promise<void> {
  await jsonRequest('/api/v1/auth/student/recovery/verify', {
    method: 'POST',
    body: JSON.stringify({ recovery_id: recoveryId, code }),
  });
}

export async function completeRecovery(recoveryId: string): Promise<void> {
  await jsonRequest('/api/v1/auth/student/recovery/complete', {
    method: 'POST',
    body: JSON.stringify({ recovery_id: recoveryId }),
  });
}

export async function startLoginOtp(mobile: string): Promise<string> {
  const result = await jsonRequest<{ login_id: string }>(
    '/api/v1/auth/student/login/otp/start',
    { method: 'POST', body: JSON.stringify({ mobile }) },
  );
  return result.login_id;
}

export async function verifyLoginOtp(loginId: string, code: string): Promise<void> {
  await jsonRequest('/api/v1/auth/student/login/otp/verify', {
    method: 'POST',
    body: JSON.stringify({ login_id: loginId, code }),
  });
  clearRegistrationSession();
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
  clearRegistrationSession();
  return result.authenticated ? result.actor : null;
}

export async function logoutStudent(): Promise<void> {
  try {
    await jsonRequest('/api/v1/auth/student/logout', {
      method: 'POST',
      body: JSON.stringify({}),
    });
  } finally {
    clearRegistrationSession();
  }
}

export const STUDENT_AUTH_CHANGED_EVENT = 'legalsaathi:student-auth-changed';

export function notifyStudentAuthChanged(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(STUDENT_AUTH_CHANGED_EVENT));
  }
}

export function saveRegistrationSession(value: RegistrationSession): void {
  onboardingSession = { ...value };
  retireBrowserRegistrationState();
}

export function loadRegistrationSession(): RegistrationSession | null {
  retireBrowserRegistrationState();
  return onboardingSession ? { ...onboardingSession } : null;
}

export function clearRegistrationSession(): void {
  onboardingSession = null;
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
}

// Erase retired browser-persisted registration/PII state as soon as the new
// bundle loads, even if the subsequent server-session probe cannot complete.
retireBrowserRegistrationState();
