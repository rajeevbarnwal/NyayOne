import type {
  AcademicProfileInput,
  InterestsProfileInput,
} from '../lib/profileApi';

type AcademicConflictDraft = {
  section: 'academic';
  value: Omit<AcademicProfileInput, 'expectedProfileVersion'>;
};

type InterestsConflictDraft = {
  section: 'interests';
  value: Omit<InterestsProfileInput, 'expectedProfileVersion'>;
};

export type ProfileConflictDraft = AcademicConflictDraft | InterestsConflictDraft;

// One same-realm handoff only. It is cleared by the student lifecycle boundary
// and is never serialized to Web Storage, CacheStorage, IndexedDB, or a URL.
let conflictDraft: ProfileConflictDraft | null = null;

export function preserveProfileConflictDraft(draft: ProfileConflictDraft): void {
  conflictDraft = structuredClone(draft);
}

export function takeProfileConflictDraft<Section extends ProfileConflictDraft['section']>(
  section: Section,
): Extract<ProfileConflictDraft, { section: Section }> | null {
  if (conflictDraft?.section !== section) return null;
  const restored = structuredClone(conflictDraft) as Extract<
    ProfileConflictDraft,
    { section: Section }
  >;
  conflictDraft = null;
  return restored;
}

export function clearProfileConflictDraft(): void {
  conflictDraft = null;
}
