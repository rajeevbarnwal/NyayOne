/**
 * Profile draft persistence for SAATHI-55.
 * Keeps PII in memory only. Registration/profile PII must never be mirrored to
 * localStorage/sessionStorage; the server is the refresh-safe source of truth.
 */
import { EMPTY_PROFILE, type ProfileDraft } from './profile';
import { fullNameToParts } from './registration';

const STORAGE_KEY = 'legalsaathi.student.profile.v1';

/**
 * Migrate a legacy record that has only `fullName` (no split parts) into
 * First/Middle/Last so existing users are never stranded (SAATHI-388/421).
 */
function migrateName(parsed: Partial<ProfileDraft>): Partial<ProfileDraft> {
  const hasParts = !!(parsed.firstName || parsed.lastName);
  if (hasParts || !parsed.fullName) return parsed;
  const parts = fullNameToParts(parsed.fullName);
  return { ...parsed, firstName: parts.firstName, middleName: parts.middleName, lastName: parts.lastName };
}

let draft: ProfileDraft = { ...EMPTY_PROFILE, interests: [] };

import { composeDisplayName } from './registration';

export function getProfileDraft(): ProfileDraft {
  return draft;
}

export function updateProfileDraft(patch: Partial<ProfileDraft>): ProfileDraft {
  const migrated = migrateName(patch);
  const fn = migrated.firstName ?? draft.firstName;
  const mn = migrated.middleName ?? draft.middleName;
  const ln = migrated.lastName ?? draft.lastName;
  const computedFull = migrated.fullName ?? (fn || ln ? composeDisplayName({ firstName: fn, middleName: mn, lastName: ln }) : draft.fullName);
  draft = { ...draft, ...migrated, fullName: computedFull };
  return draft;
}

export function resetProfileDraft(): void {
  draft = { ...EMPTY_PROFILE, interests: [] };
  if (typeof window !== 'undefined') window.localStorage.removeItem(STORAGE_KEY);
}

/** Seed a partially-complete draft (used to demonstrate the S-13 resume path). */
export function seedResumeDraft(): ProfileDraft {
  // Preserve genuine registration/wizard data. Seed only an entirely empty
  // demo state so this showcase route cannot overwrite a real user's profile.
  if (!draft.fullName && !draft.dateOfBirth) {
    draft = {
      ...EMPTY_PROFILE,
      fullName: 'Student',
      preferredLanguage: 'en',
      dateOfBirth: '2004-03-14',
      college: '',
      interests: [],
    };
  }
  return draft;
}
