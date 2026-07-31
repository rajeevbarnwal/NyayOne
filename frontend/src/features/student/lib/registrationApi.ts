import { apiFetch, newRequestId } from '../../../lib/apiClient';

const SESSION_KEY = 'legalsaathi.student.registration.v2';
const LEGACY_PII_KEY = 'legalsaathi.student.profile.v1';

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
  registrationId: string;
  college: string;
  yearOfStudy: string;
  enrolmentNumber: string;
  institutionalEmail: string;
  barEnrolmentNumber?: string;
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

export async function verifyStudentOtp(
  registrationId: string,
  code: string,
): Promise<void> {
  await jsonRequest('/api/v1/auth/student/otp/verify', {
    method: 'POST',
    body: JSON.stringify({ registration_id: registrationId, code }),
  });
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
      registration_id: input.registrationId,
      college: input.college,
      year_of_study: input.yearOfStudy,
      enrolment_number: input.enrolmentNumber,
      institutional_email: input.institutionalEmail,
      bar_enrolment_number: input.barEnrolmentNumber || null,
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
