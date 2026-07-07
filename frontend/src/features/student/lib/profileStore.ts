/**
 * In-memory profile draft store (stub persistence for SAATHI-55).
 * Persists the three-step draft across route navigation so the wizard can
 * validate/save each step independently and resume from the last incomplete
 * step (S-13). Real persistence lands with the service-logic ticket.
 */
import { EMPTY_PROFILE, type ProfileDraft } from './profile';

let draft: ProfileDraft = { ...EMPTY_PROFILE, interests: [] };

export function getProfileDraft(): ProfileDraft {
  return draft;
}

export function updateProfileDraft(patch: Partial<ProfileDraft>): ProfileDraft {
  draft = { ...draft, ...patch };
  return draft;
}

export function resetProfileDraft(): void {
  draft = { ...EMPTY_PROFILE, interests: [] };
}

/** Seed a partially-complete draft (used to demonstrate the S-13 resume path). */
export function seedResumeDraft(): ProfileDraft {
  draft = {
    ...EMPTY_PROFILE,
    fullName: 'Aditi Nair',
    preferredLanguage: 'English',
    dateOfBirth: '2004-03-14',
    college: '',
    interests: [],
  };
  return draft;
}
