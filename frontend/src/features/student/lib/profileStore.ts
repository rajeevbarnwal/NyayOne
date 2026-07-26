/**
 * Profile draft persistence for SAATHI-55.
 * Keeps an in-memory copy for SSR/tests and mirrors it to localStorage in the
 * browser so registration data and wizard progress survive route changes and
 * refreshes. This boundary contains no secrets or verification documents.
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

function loadDraft(): ProfileDraft {
  if (typeof window === 'undefined') return { ...EMPTY_PROFILE, interests: [] };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...EMPTY_PROFILE, interests: [] };
    const parsed = migrateName(JSON.parse(raw) as Partial<ProfileDraft>);
    return { ...EMPTY_PROFILE, ...parsed, interests: Array.isArray(parsed.interests) ? parsed.interests : [] };
  } catch {
    return { ...EMPTY_PROFILE, interests: [] };
  }
}

function persistDraft(value: ProfileDraft): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Private browsing/quota errors must not break profile setup.
  }
}

let draft: ProfileDraft = loadDraft();

export function getProfileDraft(): ProfileDraft {
  return draft;
}

export function updateProfileDraft(patch: Partial<ProfileDraft>): ProfileDraft {
  draft = { ...draft, ...patch };
  persistDraft(draft);
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
      preferredLanguage: 'English',
      dateOfBirth: '2004-03-14',
      college: '',
      interests: [],
    };
    persistDraft(draft);
  }
  return draft;
}
