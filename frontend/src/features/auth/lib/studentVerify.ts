/**
 * Student authentication + institutional verification logic (SAATHI-3 · P0.2).
 *
 * Reuses the shared identity primitives — the OTP state machine (`otp.ts`) and
 * the age-gate / guardian-consent / DPDP consent rules (`consent.ts`). This does
 * NOT create a parallel account system; it adds the institutional-verification
 * lifecycle on top of the existing student identity.
 *
 * Rules (PRD P0.2):
 *  - Institutional-email verification is the PREFERRED path.
 *  - College-ID fallback routes to manual_review (ID stored under access control).
 *  - Under-18 users hit an age-gate + guardian-consent flow before full processing.
 *  - Student Pro gates apply ONLY after the account state is valid.
 *
 * Minor rules are counsel-dependent (LCR): the default is CONSERVATIVE — a minor
 * is restricted until guardian consent is verified (never permissive-by-default).
 */

import {
  isMinor,
  onboardingGate,
  guardianConsentSatisfied,
  type GuardianConsent,
  type MinorContext,
} from '../../student/lib/consent';

export type FieldErrors = Record<string, string>;

export type StudentVerificationStatus = 'pending' | 'verified' | 'rejected' | 'manual_review';

export type VerifyMethod = 'institutional_email' | 'college_id';

/**
 * Config: minor onboarding follows the conservative default (restrict until
 * guardian consent). Flip only when counsel confirms the minor rule-set (LCR).
 */
export const MINOR_RULES_MODE: 'conservative' | 'counsel_confirmed' = 'conservative';

export const DPDP_MINIMISATION_NOTICE =
  'We collect only what is needed to verify student status and follow DPDP data-minimisation. Uploaded IDs are access-controlled and used solely for verification.';

/** Institutional email domains that auto-verify (representative allowlist). */
const INSTITUTIONAL_DOMAIN_RE = /\.(ac\.in|edu|edu\.in)$/i;

export function isInstitutionalEmail(email: string): boolean {
  const at = email.indexOf('@');
  if (at <= 0) return false;
  const domain = email.slice(at + 1).trim().toLowerCase();
  return INSTITUTIONAL_DOMAIN_RE.test(domain);
}

export interface StudentVerifyInput {
  method: VerifyMethod;
  institutionalEmail: string;
  collegeName: string;
  idDocumentRef: string; // opaque storage ref; never the file bytes or PII
}

export const EMPTY_STUDENT_VERIFY: StudentVerifyInput = {
  method: 'institutional_email',
  institutionalEmail: '',
  collegeName: '',
  idDocumentRef: '',
};

export function validateStudentVerify(v: StudentVerifyInput): FieldErrors {
  const e: FieldErrors = {};
  if (v.method === 'institutional_email') {
    if (!v.institutionalEmail.trim()) e.institutionalEmail = 'Enter your institutional email.';
    else if (!isInstitutionalEmail(v.institutionalEmail)) e.institutionalEmail = 'Use your college email (.ac.in / .edu). Otherwise upload your college ID.';
  } else {
    if (!v.collegeName.trim()) e.collegeName = 'Enter your college / university name.';
    if (!v.idDocumentRef.trim()) e.idDocumentRef = 'Upload your college ID to continue.';
  }
  return e;
}

export interface StudentVerificationRecord {
  readonly status: StudentVerificationStatus;
  readonly method: VerifyMethod;
  readonly checker: string;
  readonly timestamp: string;
}

/**
 * Decide the verification outcome from the chosen method. Institutional email on
 * a recognised domain auto-verifies; the college-ID fallback always routes to
 * manual_review (a human confirms the securely-stored ID).
 */
export function decideStudentVerification(v: StudentVerifyInput, now: string): StudentVerificationRecord {
  if (v.method === 'institutional_email' && isInstitutionalEmail(v.institutionalEmail)) {
    return { status: 'verified', method: 'institutional_email', checker: 'system:institutional_email', timestamp: now };
  }
  if (v.method === 'college_id') {
    return { status: 'manual_review', method: 'college_id', checker: 'queue:manual_review', timestamp: now };
  }
  // Non-institutional email supplied on the email path → cannot auto-verify.
  return { status: 'rejected', method: 'institutional_email', checker: 'system:institutional_email', timestamp: now };
}

export interface AccountState {
  readonly verification: StudentVerificationRecord | null;
  readonly minor: MinorContext;
}

/** Build the minor context from a DOB (conservative default handling). */
export function minorContextFromDob(dobISO: string, nowISO: string, guardianConsent?: GuardianConsent | null): MinorContext {
  return { isMinor: isMinor(dobISO, nowISO), guardianConsent: guardianConsent ?? null };
}

/**
 * A student account is "valid" (fully processed) only when verification succeeded
 * AND — for minors — the guardian-consent gate is satisfied. This is the state on
 * which Student Pro entitlement gates.
 */
export function accountValid(state: AccountState): boolean {
  if (!state.verification || state.verification.status !== 'verified') return false;
  return onboardingGate(state.minor) === 'ok';
}

/** Student Pro features gate ONLY after the account state is valid. */
export function proFeaturesUnlocked(state: AccountState): boolean {
  return accountValid(state);
}

/** Human-readable reason when the account is not yet valid (for UI state). */
export function studentGateReason(state: AccountState): string | null {
  if (accountValid(state)) return null;
  const v = state.verification;
  if (state.minor.isMinor && !guardianConsentSatisfied(state.minor.guardianConsent)) {
    return 'Guardian consent is required before this account can be fully activated.';
  }
  if (!v || v.status === 'pending') return 'Complete student verification to unlock student features.';
  if (v.status === 'manual_review') return 'Your college ID is in manual review. Features unlock once it is confirmed.';
  if (v.status === 'rejected') return 'We could not verify your student status. Try your institutional email or upload your college ID.';
  return 'Student verification pending.';
}

export interface StudentAuditEvent {
  readonly type: 'student_verification';
  readonly status: StudentVerificationStatus;
  readonly method: VerifyMethod;
  readonly checker: string;
  readonly timestamp: string;
  readonly minor: boolean;
}
export function toStudentAuditEvent(rec: StudentVerificationRecord, minor: boolean): StudentAuditEvent {
  return { type: 'student_verification', status: rec.status, method: rec.method, checker: rec.checker, timestamp: rec.timestamp, minor };
}

export const STUDENT_VERIFICATION_STATUS_LABELS: Record<StudentVerificationStatus, string> = {
  pending: 'Pending',
  verified: 'Verified',
  rejected: 'Rejected',
  manual_review: 'Manual review',
};

export const VERIFY_METHOD_LABELS: Record<VerifyMethod, string> = {
  institutional_email: 'Institutional email (recommended)',
  college_id: 'College ID upload',
};
