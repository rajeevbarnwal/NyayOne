/**
 * Age gate, guardian consent, and DPDP consent logic (SAATHI-53 / SAATHI-58).
 *
 * All checks here are also enforced server-side; the client only displays the
 * resulting state (TDD §8.3.1). Under-18 accounts stay in a restricted
 * onboarding state until guardian consent is verified.
 */

export const AGE_OF_MAJORITY = 18;
export const CONSENT_VERSION = 'dpdp-2023.v1';

/** Age in whole years from an ISO date (yyyy-mm-dd) at a reference instant. */
export function computeAge(dobISO: string, nowISO: string): number {
  const dob = new Date(dobISO);
  const now = new Date(nowISO);
  let age = now.getUTCFullYear() - dob.getUTCFullYear();
  const m = now.getUTCMonth() - dob.getUTCMonth();
  if (m < 0 || (m === 0 && now.getUTCDate() < dob.getUTCDate())) age -= 1;
  return age;
}

/** A registration DOB must be a real calendar date and cannot be in the future. */
export function isValidDateOfBirth(dobISO: string, nowISO: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dobISO)) return false;
  const dob = new Date(`${dobISO}T00:00:00.000Z`);
  const now = new Date(nowISO);
  if (Number.isNaN(dob.getTime()) || Number.isNaN(now.getTime())) return false;
  // Reject normalised invalid dates such as 2026-02-31.
  if (dob.toISOString().slice(0, 10) !== dobISO) return false;
  return dob.getTime() <= now.getTime();
}

export function isMinor(dobISO: string, nowISO: string): boolean {
  return computeAge(dobISO, nowISO) < AGE_OF_MAJORITY;
}

export type GuardianVerification = 'pending' | 'verified' | 'rejected';

/** Separate consent record for a minor's guardian (TDD §8.3.1). */
export interface GuardianConsent {
  readonly guardianName: string;
  readonly relationship: string;
  readonly consentVersion: string;
  readonly channel: string;
  readonly timestamp: string;
  readonly verificationStatus: GuardianVerification;
  readonly withdrawn: boolean;
}

export function guardianConsentRequired(dobISO: string, nowISO: string): boolean {
  return isMinor(dobISO, nowISO);
}

export function guardianConsentSatisfied(gc?: GuardianConsent | null): boolean {
  return !!gc && gc.verificationStatus === 'verified' && !gc.withdrawn;
}

/** Capabilities blocked for an under-18 account until guardian consent clears. */
export type Capability =
  | 'ai_research'
  | 'community_post'
  | 'public_profile'
  | 'payments'
  | 'internship_reporting'
  | 'credential_sharing';

export const MINOR_RESTRICTED_CAPABILITIES: readonly Capability[] = [
  'ai_research',
  'community_post',
  'public_profile',
  'payments',
  'internship_reporting',
  'credential_sharing',
];

export interface MinorContext {
  readonly isMinor: boolean;
  readonly guardianConsent?: GuardianConsent | null;
}

/** Whether a capability is allowed given minor status + guardian consent. */
export function capabilityAllowed(cap: Capability, ctx: MinorContext): boolean {
  if (!ctx.isMinor) return true;
  if (guardianConsentSatisfied(ctx.guardianConsent)) return true;
  return !MINOR_RESTRICTED_CAPABILITIES.includes(cap);
}

/** Registration-time DPDP consent record (mandatory terms + privacy). */
export interface RegistrationConsent {
  readonly version: string;
  readonly acceptedTerms: boolean;
  readonly acceptedPrivacy: boolean;
  readonly lawStudentDeclared: boolean;
  readonly timestamp: string;
}

/** All mandatory consents present (Terms + Privacy + law-student declaration). */
export function registrationConsentComplete(rec: RegistrationConsent): boolean {
  return rec.acceptedTerms && rec.acceptedPrivacy && rec.lawStudentDeclared;
}

/** Human-readable onboarding gate outcome for an account. */
export type OnboardingGate = 'ok' | 'guardian_consent_pending';

export function onboardingGate(ctx: MinorContext): OnboardingGate {
  if (ctx.isMinor && !guardianConsentSatisfied(ctx.guardianConsent)) {
    return 'guardian_consent_pending';
  }
  return 'ok';
}
