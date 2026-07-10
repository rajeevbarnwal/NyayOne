/**
 * Lawyer authentication + BCI/State-Bar verification logic (SAATHI-2 · P0.1).
 *
 * Pure, framework-free domain logic mirroring the server rules. All checks here
 * are ALSO enforced server-side; the client only renders the resulting state.
 *
 * Guardrails (load-bearing):
 *  - The platform verifies ENROLMENT STATUS ONLY. It never certifies competence,
 *    endorsement, success rate, or outcome likelihood.
 *  - AI/automation can never clear a verification. A possible/failed check stays
 *    restricted unless an authorised human records an override with a reason.
 *  - BCI profile-display behaviour is disabled by default pending LCR-002.
 *
 * OTP TTL/attempt/lockout is reused from the shared student OTP state machine so
 * lawyers and students share one, tested implementation (no parallel system).
 */

import { OTP_TTL_MS, OTP_MAX_ATTEMPTS, OTP_LOCK_MS } from '../../student/lib/otp';

export type FieldErrors = Record<string, string>;

/** Verification status values (exactly as PRD P0.1 specifies). */
export type LawyerVerificationStatus = 'pending' | 'verified' | 'rejected' | 'manual_review';

/**
 * Config flag: BCI/State-Bar profile display is DISABLED BY DEFAULT pending the
 * LCR-002 legal review. Verification (gating access) still works; only the
 * public-facing enrolment/profile display is withheld until counsel signs off.
 */
export const BCI_PROFILE_DISPLAY_ENABLED = false;

export const ENROLMENT_STATUS_ONLY_NOTICE =
  'We verify Bar Council enrolment status only. This is not an endorsement of competence, and we never publish success rates or outcome predictions.';

/** Re-exported so the UI countdown and the server stay on identical numbers. */
export const LAWYER_OTP = { ttlMs: OTP_TTL_MS, maxAttempts: OTP_MAX_ATTEMPTS, lockMs: OTP_LOCK_MS } as const;

/** A representative (non-exhaustive) set of State Bar Councils for the picker. */
export const STATE_BAR_COUNCILS: readonly string[] = [
  'Bar Council of Delhi',
  'Bar Council of Maharashtra & Goa',
  'Bar Council of Uttar Pradesh',
  'Bar Council of Tamil Nadu & Puducherry',
  'Bar Council of Karnataka',
  'Bar Council of West Bengal',
  'Bar Council of Gujarat',
  'Bar Council of Rajasthan',
];

export interface LawyerProfile {
  fullName: string;
  enrolmentNumber: string;
  stateBarCouncil: string;
}

export const EMPTY_LAWYER_PROFILE: LawyerProfile = {
  fullName: '',
  enrolmentNumber: '',
  stateBarCouncil: '',
};

/** Enrolment numbers look like "D/1234/2015" (council/serial/year) across states. */
const ENROLMENT_RE = /^[A-Z]{1,3}\/\d{1,6}\/(19|20)\d{2}$/i;

export function validateLawyerProfile(p: LawyerProfile): FieldErrors {
  const e: FieldErrors = {};
  if (!p.fullName.trim()) e.fullName = 'Enter your full name as enrolled.';
  if (!p.enrolmentNumber.trim()) e.enrolmentNumber = 'Enter your Bar Council enrolment number.';
  else if (!ENROLMENT_RE.test(p.enrolmentNumber.trim())) e.enrolmentNumber = 'Use the format STATE/NUMBER/YEAR, e.g. D/1234/2015.';
  if (!p.stateBarCouncil.trim()) e.stateBarCouncil = 'Select your State Bar Council.';
  return e;
}

// --- Enrolment verification source (adapter boundary; local stub only) --------

export type EnrolmentLookup = 'active' | 'not_found' | 'unavailable';

export interface EnrolmentSource {
  /** NO network here — the shipped implementation is a deterministic stub. */
  lookup(enrolmentNumber: string, council: string): EnrolmentLookup;
}

/**
 * Local stub source. Deterministic for prototype/QA: an enrolment ending in an
 * even digit is "active", one containing "0000" is "unavailable" (→manual), and
 * anything else is "not_found". The real source runs server-side later.
 */
export function createStubEnrolmentSource(): EnrolmentSource {
  return {
    lookup(enrolmentNumber) {
      const serial = enrolmentNumber.split('/')[1] ?? '';
      if (serial.includes('0000')) return 'unavailable';
      const last = serial.slice(-1);
      return /[02468]/.test(last) ? 'active' : 'not_found';
    },
  };
}

export interface VerificationRecord {
  readonly status: LawyerVerificationStatus;
  readonly checker: string; // system id or human reviewer id
  readonly timestamp: string;
  readonly overrideReason?: string;
}

/** Map an enrolment lookup to a verification status. */
export function statusForLookup(r: EnrolmentLookup): LawyerVerificationStatus {
  switch (r) {
    case 'active':
      return 'verified';
    case 'not_found':
      return 'rejected';
    case 'unavailable':
      return 'manual_review';
  }
}

/** Run the enrolment check and produce a verification record. */
export function runEnrolmentCheck(
  profile: LawyerProfile,
  source: EnrolmentSource,
  now: string,
  checker = 'system:enrolment'
): VerificationRecord {
  const lookup = source.lookup(profile.enrolmentNumber.trim(), profile.stateBarCouncil.trim());
  return { status: statusForLookup(lookup), checker, timestamp: now };
}

export interface ManualOverride {
  readonly authorised: boolean; // must be an authorised human reviewer
  readonly reason: string;
  readonly reviewer: string;
}

/**
 * Record an authorised human override. Returns a `verified` record ONLY when the
 * reviewer is authorised AND a non-empty reason is supplied. Otherwise the prior
 * record is returned unchanged — automation can never produce a clearance.
 */
export function recordManualOverride(prev: VerificationRecord, override: ManualOverride, now: string): VerificationRecord {
  if (!override.authorised || !override.reason.trim()) return prev;
  return { status: 'verified', checker: override.reviewer, timestamp: now, overrideReason: override.reason.trim() };
}

/** Lawyer features unlock only when verification is server-authoritative verified. */
export function canAccessLawyerFeatures(rec: VerificationRecord | null): boolean {
  return !!rec && rec.status === 'verified';
}

/** Human-readable, restricted-state reason for the gate (used by the UI). */
export function lawyerGateReason(rec: VerificationRecord | null): string | null {
  if (canAccessLawyerFeatures(rec)) return null;
  switch (rec?.status) {
    case 'rejected':
      return 'Enrolment could not be verified. Contact support to submit a manual review.';
    case 'manual_review':
      return 'Your enrolment is in manual review. Lawyer features unlock once a reviewer confirms it.';
    default:
      return 'Lawyer features are locked until Bar Council enrolment verification is complete.';
  }
}

// --- Consent + audit ---------------------------------------------------------

export interface LawyerConsent {
  readonly acceptedTerms: boolean;
  readonly acceptedPrivacy: boolean;
  readonly timestamp: string;
}
export function lawyerConsentComplete(c: LawyerConsent): boolean {
  return c.acceptedTerms && c.acceptedPrivacy;
}

export interface LawyerAuditEvent {
  readonly type: 'lawyer_verification';
  readonly status: LawyerVerificationStatus;
  readonly checker: string;
  readonly timestamp: string;
  readonly overrideReason?: string;
}
export function toLawyerAuditEvent(rec: VerificationRecord): LawyerAuditEvent {
  return {
    type: 'lawyer_verification',
    status: rec.status,
    checker: rec.checker,
    timestamp: rec.timestamp,
    overrideReason: rec.overrideReason,
  };
}

/** Guardrail helper: reject any profile copy that implies competence/outcome. */
const OUTCOME_CLAIM_RE = /\b(win rate|success rate|guarantee|best lawyer|top rated|\d+%\s*win|assured outcome)\b/i;
export function containsOutcomeClaim(text: string): boolean {
  return OUTCOME_CLAIM_RE.test(text);
}

export const LAWYER_VERIFICATION_STATUS_LABELS: Record<LawyerVerificationStatus, string> = {
  pending: 'Pending',
  verified: 'Verified',
  rejected: 'Rejected',
  manual_review: 'Manual review',
};
