/**
 * Profile draft persistence for SAATHI-55.
 * Keeps PII in memory only. Registration/profile PII must never be mirrored to
 * localStorage/sessionStorage; the server is the refresh-safe source of truth.
 */
import { EMPTY_PROFILE, type ProfileDraft } from './profile';
import { fullNameToParts } from './registration';
import { LEGACY_STUDENT_PROFILE_DRAFT_KEY } from './studentLegacyStorage';

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

export function getProfileDraft(): ProfileDraft {
  return draft;
}

export function updateProfileDraft(patch: Partial<ProfileDraft>): ProfileDraft {
  draft = { ...draft, ...migrateName(patch) };
  return draft;
}

export function resetProfileDraft(): void {
  draft = { ...EMPTY_PROFILE, interests: [] };
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(LEGACY_STUDENT_PROFILE_DRAFT_KEY);
  } catch {
    // Browser privacy policy must not prevent the in-memory PII reset above.
  }
}
