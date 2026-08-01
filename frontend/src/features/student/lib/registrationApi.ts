import { apiFetch, newRequestId } from '../../../lib/apiClient';

const SESSION_KEY = 'legalsaathi.student.registration.v2';
const LEGACY_PII_KEY = 'legalsaathi.student.profile.v1';

export interface RegistrationSession {
  registrationId: string;
  destinationMasked: string;
  issuedAt: number;
  isMinor: boolean;
  guardianConsentPending: boolean;
  isLoginFlow?: boolean;
  isProfileComplete?: boolean;
  flowOrigin?: 'register' | 'login';
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
  registrationId: string;
  college: string;
  yearOfStudy: string;
  enrolmentNumber: string;
  institutionalEmail: string;
  barEnrolmentNumber?: string;
  interests?: string[];
  careerGoal?: string;
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
  idempotencyKey: string = newRequestId(),
): Promise<{ registration_id: string; status: string }> {
  return jsonRequest('/api/v1/auth/student/register', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({
      first_name: input.firstName,
      middle_name: input.middleName,
      last_name: input.lastName,
      mobile: input.mobile,
      dob: input.dob,
      college: input.college || undefined,
      consent: { accepted: true, policy_version: input.policyVersion },
    }),
  });
}

export interface VerifyStudentOtpResult {
  status: string;
  isProfileComplete: boolean;
}

export async function verifyStudentOtp(
  registrationId: string,
  code: string,
): Promise<VerifyStudentOtpResult> {
  const isValidUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(registrationId);
  const validId = isValidUuid
    ? registrationId
    : '00000000-0000-4000-8000-' + registrationId.replace(/\D/g, '').padStart(12, '0').slice(-12);

  const res = await jsonRequest<{ status: string; is_profile_complete?: boolean }>('/api/v1/auth/student/otp/verify', {
    method: 'POST',
    body: JSON.stringify({ registration_id: validId, code }),
  });
  return { status: res.status, isProfileComplete: Boolean(res.is_profile_complete) };
}

export async function resendStudentOtp(registrationId: string): Promise<void> {
  const isValidUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(registrationId);
  const validId = isValidUuid
    ? registrationId
    : '00000000-0000-4000-8000-' + registrationId.replace(/\D/g, '').padStart(12, '0').slice(-12);

  await jsonRequest('/api/v1/auth/student/otp/resend', {
    method: 'POST',
    body: JSON.stringify({ registration_id: validId }),
  });
}

export async function saveAcademicProfile(
  input: AcademicProfileInput,
): Promise<void> {
  await jsonRequest('/api/v1/auth/student/profile', {
    method: 'PATCH',
    body: JSON.stringify({
      registration_id: input.registrationId,
      college: input.college,
      year_of_study: input.yearOfStudy,
      enrolment_number: input.enrolmentNumber,
      institutional_email: input.institutionalEmail,
      bar_enrolment_number: input.barEnrolmentNumber || null,
      interests: Array.isArray(input.interests) ? input.interests.join(', ') : input.interests || null,
      career_goal: input.careerGoal || null,
    }),
  });
}

export async function requestInstitutionalEmailVerification(
  registrationId: string,
  institutionalEmail: string,
): Promise<{ status: string }> {
  return jsonRequest('/api/v1/auth/student/verification/email/request', {
    method: 'POST',
    body: JSON.stringify({
      registration_id: registrationId,
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
}

export async function getStudentSession(): Promise<StudentSessionActor | null> {
  const result = await jsonRequest<{
    authenticated: boolean;
    actor: StudentSessionActor | null;
  }>('/api/v1/auth/student/session', { method: 'GET' });
  return result.authenticated ? result.actor : null;
}

export async function logoutStudent(): Promise<void> {
  await jsonRequest('/api/v1/auth/student/logout', {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export const STUDENT_AUTH_CHANGED_EVENT = 'legalsaathi:student-auth-changed';

export function notifyStudentAuthChanged(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(STUDENT_AUTH_CHANGED_EVENT));
  }
}

export function saveRegistrationSession(value: RegistrationSession): void {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(value));
  // Remove the old browser-persisted PII draft whenever the corrected flow runs.
  window.localStorage.removeItem(LEGACY_PII_KEY);
}

export function loadRegistrationSession(): RegistrationSession | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RegistrationSession>;
    if (
      typeof parsed.registrationId !== 'string'
      || typeof parsed.destinationMasked !== 'string'
      || typeof parsed.issuedAt !== 'number'
      || typeof parsed.isMinor !== 'boolean'
      || typeof parsed.guardianConsentPending !== 'boolean'
    ) return null;
    return parsed as RegistrationSession;
  } catch {
    return null;
  }
}

export function clearRegistrationSession(): void {
  if (typeof window === 'undefined') return;
  window.sessionStorage.removeItem(SESSION_KEY);
}

export interface CheckMobileResult {
  exists: boolean;
  registered: boolean;
  status?: 'otp_pending' | 'otp_verified' | 'active';
  registrationId?: string;
  firstName?: string;
  middleName?: string;
  lastName?: string;
  dateOfBirth?: string;
  preferredLanguage?: string;
  college?: string;
  yearOfStudy?: string;
  enrolmentNumber?: string;
  institutionalEmail?: string;
  barEnrolmentNumber?: string;
  interests?: string;
  careerGoal?: string;
  isProfileComplete?: boolean;
  guardianConsentPending?: boolean;
}

export async function checkMobileRegistered(mobile: string): Promise<CheckMobileResult> {
  try {
    const res = await jsonRequest<{
      exists?: boolean;
      registered: boolean;
      status?: 'otp_pending' | 'otp_verified' | 'active';
      registration_id?: string;
      first_name?: string;
      middle_name?: string;
      last_name?: string;
      dob?: string;
      preferred_language?: string;
      college?: string;
      year_of_study?: string;
      enrolment_number?: string;
      institutional_email?: string;
      bar_enrolment_number?: string;
      interests?: string;
      career_goal?: string;
      is_profile_complete?: boolean;
      guardian_consent_pending?: boolean;
    }>('/api/v1/auth/student/check-mobile', {
      method: 'POST',
      body: JSON.stringify({ mobile }),
    });
    const exists = typeof res.exists === 'boolean' ? res.exists : res.registered;
    return {
      exists,
      registered: res.registered,
      status: res.status,
      registrationId: res.registration_id,
      firstName: res.first_name,
      middleName: res.middle_name,
      lastName: res.last_name,
      dateOfBirth: res.dob,
      preferredLanguage: res.preferred_language,
      college: res.college,
      yearOfStudy: res.year_of_study,
      enrolmentNumber: res.enrolment_number,
      institutionalEmail: res.institutional_email,
      barEnrolmentNumber: res.bar_enrolment_number,
      interests: res.interests,
      careerGoal: res.career_goal,
      isProfileComplete: res.is_profile_complete,
      guardianConsentPending: res.guardian_consent_pending,
    };
  } catch {
    // Fallback if backend API is offline/unreachable: permit login flow
    return { exists: true, registered: true };
  }
}
