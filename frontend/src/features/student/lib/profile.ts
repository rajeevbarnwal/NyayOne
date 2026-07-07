/**
 * Three-step student profile model, validation, completeness and tier
 * derivation (SAATHI-55 / S2.1). Pure + testable; the client uses this to
 * drive step validation and to resume from the last incomplete step (S-13).
 * Persistence is a stub boundary in this batch (no domain migrations).
 */

export type ProfileStep = 1 | 2 | 3;

export interface ProfileDraft {
  // Step 1 — personal
  fullName: string;
  preferredLanguage: string;
  dateOfBirth: string; // yyyy-mm-dd
  // Step 2 — academic
  college: string;
  yearOfStudy: string;
  enrolmentNumber: string;
  institutionalEmail: string;
  barEnrolmentNumber?: string; // optional & private — never on public profile
  // Step 3 — preferences
  interests: string[];
  careerGoal: string;
}

export const EMPTY_PROFILE: ProfileDraft = {
  fullName: '',
  preferredLanguage: 'English',
  dateOfBirth: '',
  college: '',
  yearOfStudy: '',
  enrolmentNumber: '',
  institutionalEmail: '',
  barEnrolmentNumber: '',
  interests: [],
  careerGoal: '',
};

/** Full institutional email (must have a dotted domain). "aditi@nlsiu" fails. */
export const INSTITUTIONAL_EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
/** Enrolment format: state code / roll / year, e.g. "KA/1234/2023". */
export const ENROLMENT_RE = /^[A-Za-z]{2}\/\d+\/\d{4}$/;

export type FieldErrors = Record<string, string>;

export function validateStep1(d: ProfileDraft): FieldErrors {
  const e: FieldErrors = {};
  if (!d.fullName.trim()) e.fullName = 'Enter your full name.';
  if (!d.dateOfBirth) e.dateOfBirth = 'Enter your date of birth.';
  if (!d.preferredLanguage) e.preferredLanguage = 'Choose a language.';
  return e;
}

export function validateStep2(d: ProfileDraft): FieldErrors {
  const e: FieldErrors = {};
  if (!d.college.trim()) e.college = 'Select your college or university.';
  if (!d.yearOfStudy.trim()) e.yearOfStudy = 'Select your year of study.';
  if (!ENROLMENT_RE.test(d.enrolmentNumber.trim()))
    e.enrolmentNumber = 'Format: state code / roll / year.';
  if (!INSTITUTIONAL_EMAIL_RE.test(d.institutionalEmail.trim()))
    e.institutionalEmail = 'Enter your full institutional email — e.g. aditi.nair@nls.ac.in';
  // barEnrolmentNumber is optional & private — never required, never validated as public.
  return e;
}

export function validateStep3(d: ProfileDraft): FieldErrors {
  const e: FieldErrors = {};
  if (d.interests.length === 0) e.interests = 'Choose at least one area of interest.';
  if (!d.careerGoal.trim()) e.careerGoal = 'Select a career goal.';
  return e;
}

const VALIDATORS: Record<ProfileStep, (d: ProfileDraft) => FieldErrors> = {
  1: validateStep1,
  2: validateStep2,
  3: validateStep3,
};

export function validateStep(step: ProfileStep, d: ProfileDraft): FieldErrors {
  return VALIDATORS[step](d);
}

export function isStepComplete(step: ProfileStep, d: ProfileDraft): boolean {
  return Object.keys(validateStep(step, d)).length === 0;
}

/** Lowest incomplete step (for resume, S-13) or null when all complete. */
export function nextIncompleteStep(d: ProfileDraft): ProfileStep | null {
  const steps: ProfileStep[] = [1, 2, 3];
  for (const s of steps) {
    if (!isStepComplete(s, d)) return s;
  }
  return null;
}

export function isProfileComplete(d: ProfileDraft): boolean {
  return nextIncompleteStep(d) === null;
}

export type ProfileTier = 'incomplete' | 'verified_student';

/** Tier badge: "Verified Student" once the profile is complete. */
export function profileTier(d: ProfileDraft): ProfileTier {
  return isProfileComplete(d) ? 'verified_student' : 'incomplete';
}

export const TIER_LABELS: Record<ProfileTier, string> = {
  incomplete: 'Setup incomplete',
  verified_student: 'Verified Student',
};
