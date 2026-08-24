/**
 * One bounded same-realm handoff for an unsaved NYAY-5 profile form.
 *
 * This module is deliberately process-memory only. It stores no server
 * projection and grants no authority: the prior actor tag is used solely for
 * equality after a fresh authoritative session discovery.
 */

export const PROFILE_REAUTH_HANDOFF_TTL_MS = 5 * 60 * 1_000;

export type ProfileReauthSection = 'personal' | 'academic' | 'interests';

export interface PersonalProfileReauthDraft {
  firstName: string;
  middleName: string | null;
  lastName: string;
  dateOfBirth: string;
  preferredLanguage: string;
  city: string;
  pronouns: string | null;
}

export interface AcademicProfileReauthDraft {
  college: string;
  yearOfStudy: string;
  enrolmentNumber: string;
  institutionalEmail: string | null;
  barEnrolmentNumber: string | null;
}

export interface InterestsProfileReauthDraft {
  interests: string[];
  goals: string[];
}

export interface ProfileReauthDraftValueBySection {
  personal: PersonalProfileReauthDraft;
  academic: AcademicProfileReauthDraft;
  interests: InterestsProfileReauthDraft;
}

export type ProfileReauthDraft =
  | { section: 'personal'; value: PersonalProfileReauthDraft }
  | { section: 'academic'; value: AcademicProfileReauthDraft }
  | { section: 'interests'; value: InterestsProfileReauthDraft };

export interface CapturedProfileReauthDraft {
  readonly actorSubject: string;
  readonly draft: ProfileReauthDraft;
}

interface ActiveProfileReauthDraft extends CapturedProfileReauthDraft {
  sequence: number;
}

interface RetainedProfileReauthDraft extends CapturedProfileReauthDraft {
  expiresAt: number;
  resolved: boolean;
}

const activeDrafts = new Map<symbol, ActiveProfileReauthDraft>();
let sequence = 0;
let retained: RetainedProfileReauthDraft | null = null;
let expiryTimer: ReturnType<typeof globalThis.setTimeout> | null = null;

function cloneDraft(draft: ProfileReauthDraft): ProfileReauthDraft {
  if (draft.section === 'personal') {
    return { section: draft.section, value: { ...draft.value } };
  }
  if (draft.section === 'academic') {
    return { section: draft.section, value: { ...draft.value } };
  }
  return {
    section: draft.section,
    value: {
      interests: [...draft.value.interests],
      goals: [...draft.value.goals],
    },
  };
}

function clearExpiryTimer(): void {
  if (expiryTimer !== null) globalThis.clearTimeout(expiryTimer);
  expiryTimer = null;
}

function clearRetained(): void {
  clearExpiryTimer();
  retained = null;
}

function liveRetained(now: number = Date.now()): RetainedProfileReauthDraft | null {
  if (retained !== null && retained.expiresAt <= now) clearRetained();
  return retained;
}

function canonicalRoute(section: ProfileReauthSection): string {
  if (section === 'personal' || section === 'academic') {
    return `/s-10?section=${section}`;
  }
  return '/s-11';
}

/** Track the latest mounted profile form without turning it into authority. */
export function stageActiveProfileReauthDraft(
  owner: symbol,
  actorSubject: string,
  draft: ProfileReauthDraft,
): void {
  const actor = actorSubject.trim();
  if (!actor) {
    activeDrafts.delete(owner);
    return;
  }
  sequence += 1;
  activeDrafts.set(owner, {
    actorSubject: actor,
    draft: cloneDraft(draft),
    sequence,
  });
}

/** Remove one normal unmount without touching a separately retained handoff. */
export function releaseActiveProfileReauthDraft(owner: symbol): void {
  activeDrafts.delete(owner);
}

/** Clone the most recently updated mounted form before auth teardown clears it. */
export function captureActiveProfileReauthDraft(): CapturedProfileReauthDraft | null {
  let latest: ActiveProfileReauthDraft | null = null;
  for (const candidate of activeDrafts.values()) {
    if (latest === null || candidate.sequence > latest.sequence) latest = candidate;
  }
  return latest === null ? null : {
    actorSubject: latest.actorSubject,
    draft: cloneDraft(latest.draft),
  };
}

/** Install exactly one captured form after the ordinary teardown has completed. */
export function restoreCapturedProfileReauthDraft(
  captured: CapturedProfileReauthDraft,
  now: number = Date.now(),
): void {
  clearRetained();
  activeDrafts.clear();
  retained = {
    actorSubject: captured.actorSubject,
    draft: cloneDraft(captured.draft),
    expiresAt: now + PROFILE_REAUTH_HANDOFF_TTL_MS,
    resolved: false,
  };
  expiryTimer = globalThis.setTimeout(
    clearRetained,
    PROFILE_REAUTH_HANDOFF_TTL_MS,
  );
}

/** Erase active and retained PII for logout, deletion, failure, or actor change. */
export function clearProfileReauthHandoff(): void {
  activeDrafts.clear();
  clearRetained();
}

export function hasProfileReauthHandoff(now: number = Date.now()): boolean {
  return liveRetained(now) !== null;
}

/**
 * Mark the handoff usable only after a fresh server session proves the same
 * actor. A different actor destroys it without returning any value.
 */
export function resolveProfileReauthActor(
  actorSubject: string,
  now: number = Date.now(),
): boolean {
  const current = liveRetained(now);
  if (current === null) return false;
  if (current.actorSubject !== actorSubject) {
    clearProfileReauthHandoff();
    return false;
  }
  current.resolved = true;
  return true;
}

export function profileReauthResumeRoute(
  actorSubject: string,
  now: number = Date.now(),
): string | null {
  const current = liveRetained(now);
  if (current === null || !current.resolved || current.actorSubject !== actorSubject) return null;
  return canonicalRoute(current.draft.section);
}

/** Route-only continuation after authoritative resolution; contains no PII. */
export function resolvedProfileReauthResumeRoute(
  now: number = Date.now(),
): string | null {
  const current = liveRetained(now);
  if (current === null || !current.resolved) return null;
  return canonicalRoute(current.draft.section);
}

/** Consume one exact section draft after same-actor resolution. */
export function takeResolvedProfileReauthDraft<Section extends ProfileReauthSection>(
  actorSubject: string,
  section: Section,
  now: number = Date.now(),
): ProfileReauthDraftValueBySection[Section] | null {
  const current = liveRetained(now);
  if (
    current === null
    || !current.resolved
    || current.actorSubject !== actorSubject
    || current.draft.section !== section
  ) return null;
  const value = cloneDraft(current.draft).value as ProfileReauthDraftValueBySection[Section];
  clearProfileReauthHandoff();
  return value;
}
