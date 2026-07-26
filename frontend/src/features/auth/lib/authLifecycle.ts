/**
 * Shared Phase-0 authentication lifecycle (SAATHI-2 / SAATHI-3 remediation).
 *
 * A pure, testable reducer that both the lawyer (P0.1) and student (P0.2)
 * verification workbenches drive. The OTP sub-state is delegated to the shared
 * `otp.ts` state machine (no duplication); this reducer only sequences the
 * higher-level lifecycle phases and records a redacted, persistable snapshot.
 *
 * Persistence rule: the snapshot NEVER contains the OTP code, passwords or any
 * secret — only a redacted challenge (timings + attempts) and masked destination.
 */
import type { OtpChallenge } from '../../student/lib/otp';

export type AuthRole = 'lawyer' | 'student';

export type AuthPhase =
  | 'entry' // role / context
  | 'register' // capture name/mobile/email (+ college for student)
  | 'otp_sent'
  | 'otp_entry'
  | 'consent' // explicit DPDP affirmative consent
  | 'details' // BCI enrolment (lawyer) / institutional email or ID (student)
  | 'pending'
  | 'manual_review'
  | 'rejected'
  | 'verified';

export type AuthEvent =
  | 'select_role'
  | 'submit_registration'
  | 'otp_delivered'
  | 'begin_otp_entry'
  | 'otp_verified'
  | 'give_consent'
  | 'submit_details'
  | 'result_pending'
  | 'result_manual'
  | 'result_rejected'
  | 'result_verified'
  | 'retry'
  | 'reset';

/** Allowed forward transitions. Unknown (phase,event) pairs are no-ops. */
const TRANSITIONS: Partial<Record<AuthPhase, Partial<Record<AuthEvent, AuthPhase>>>> = {
  entry: { select_role: 'register' },
  register: { submit_registration: 'otp_sent' },
  otp_sent: { begin_otp_entry: 'otp_entry' },
  otp_entry: { otp_verified: 'consent', retry: 'otp_sent' },
  consent: { give_consent: 'details' },
  details: {
    submit_details: 'pending',
    result_pending: 'pending',
    result_manual: 'manual_review',
    result_rejected: 'rejected',
    result_verified: 'verified',
  },
  pending: {
    result_manual: 'manual_review',
    result_rejected: 'rejected',
    result_verified: 'verified',
  },
  manual_review: { result_verified: 'verified', result_rejected: 'rejected' },
  rejected: { retry: 'details' },
};

export function nextPhase(phase: AuthPhase, event: AuthEvent): AuthPhase {
  if (event === 'reset') return 'entry';
  return TRANSITIONS[phase]?.[event] ?? phase;
}

export const AUTH_PHASE_ORDER: readonly AuthPhase[] = [
  'entry', 'register', 'otp_sent', 'otp_entry', 'consent', 'details', 'pending', 'verified',
];

export const AUTH_PHASE_LABELS: Record<AuthPhase, string> = {
  entry: 'Get started',
  register: 'Register',
  otp_sent: 'OTP sent',
  otp_entry: 'Verify OTP',
  consent: 'Consent',
  details: 'Verification',
  pending: 'Pending',
  manual_review: 'Manual review',
  rejected: 'Rejected',
  verified: 'Verified',
};

/** A redacted OTP challenge — the code is intentionally omitted for persistence. */
export type RedactedChallenge = Omit<OtpChallenge, 'code'>;
export function redactChallenge(ch: OtpChallenge): RedactedChallenge {
  const { code: _omit, ...rest } = ch;
  void _omit;
  return rest;
}

/** Persistable, secret-free snapshot of an in-flight auth lifecycle. */
export interface AuthSnapshot {
  readonly role: AuthRole;
  readonly phase: AuthPhase;
  readonly destinationMasked: string | null;
  readonly challenge: RedactedChallenge | null;
  readonly consentAt: string | null;
  /**
   * Stable opaque authenticated subject id, issued by the verified identity
   * lifecycle. This is the ONLY value used as the downstream audit actor id — it
   * is never a masked contact, name or BCI number.
   */
  readonly subjectId?: string | null;
  /**
   * Verified legal-workspace authorisation claim (functional role: lawyer /
   * senior_advocate / firm_partner / associate / clerk / billing_admin). Distinct
   * from the identity `role`; absent → treated as base 'lawyer' once verified.
   */
  readonly filingRole?: string | null;
  readonly updatedAt: number;
}

/**
 * Mint a stable opaque subject id from a non-reversible fingerprint of the
 * identity seed. Never derived from, and never reveals, contact/BCI/name values.
 */
export function makeSubjectId(seed: string): string {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return `subj_${h.toString(16)}`;
}

/** Guard: assert a snapshot carries no secret material (used in tests). */
export function snapshotHasNoSecret(snap: AuthSnapshot): boolean {
  const s = JSON.stringify(snap);
  return !/"code"\s*:/.test(s) && !/password|otpCode|token/i.test(s);
}
