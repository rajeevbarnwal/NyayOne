import { queryClient } from '../../../app/queryClient';
import { resetProfileDraft } from './profileStore';
import { clearRegistrationAttempt } from './registrationAttemptStore';

export const STUDENT_AUTH_CHANGED_EVENT = 'legalsaathi:student-auth-changed';

const REPORT_KEY_PREFIX = 'ls-reports-';
const REMINDER_KEY_PREFIX = 'ls-reminder-prefs-';
const RETIRED_ACTOR_PREFIXES = [REPORT_KEY_PREFIX, REMINDER_KEY_PREFIX] as const;

// Cleanup is deliberately bounded. These are retired app-owned namespaces,
// not an authority registry and never a reason to clear unrelated storage.
export const MAX_RETIRED_STUDENT_KEYS_PER_PURGE = 256;

// This projection is anonymous and contains only the server-approved public
// aggregate. Every other query root remains actor-sensitive by default.
const ACTOR_INDEPENDENT_QUERY_ROOTS = new Set(['public-internship-risk-labels']);

const LOCAL_STUDENT_KEYS = [
  'legalsaathi.student.profile.v1',
  'legalsaathi.student.onboarding.v34',
  'legalsaathi.internship.applications.v1',
  'legalsaathi.clinical.export-audit.v1',
  'ls-auth-student',
  // Retire the former browser-backed actor registry without reading it.
  'legalsaathi.student.cleanup-registry.v1',
] as const;

const SESSION_STUDENT_KEYS = [
  'legalsaathi.student.registration.v2',
  'legalsaathi.student.privacy.export.v1',
  'legalsaathi.student.privacy.delete.v1',
] as const;

interface ObservedStudentActor {
  subject: string;
  studentProfileId: string | null;
}

// Actor identity is held only in this JS realm. It is never copied to
// localStorage/sessionStorage, including indirectly inside a cleanup registry.
let observedStudentActor: ObservedStudentActor | null = null;

function availableStorage(kind: 'localStorage' | 'sessionStorage'): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window[kind];
  } catch {
    return null;
  }
}

function removeKey(storage: Storage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    // Storage can become unavailable after access under strict privacy policy.
  }
}

function actorKeys(actor: ObservedStudentActor): string[] {
  const ids = new Set([
    actor.subject,
    actor.studentProfileId,
  ].filter((value): value is string => Boolean(value)));
  return [...ids].flatMap((id) => [`ls-reports-${id}`, `ls-reminder-prefs-${id}`]);
}

function currentActorKeys(): string[] {
  return observedStudentActor ? actorKeys(observedStudentActor) : [];
}

function retiredActorKeys(storage: Storage): string[] {
  const keys: string[] = [];
  let length: number;
  try {
    length = Math.min(storage.length, MAX_RETIRED_STUDENT_KEYS_PER_PURGE);
  } catch {
    return keys;
  }
  for (let index = 0; index < length; index += 1) {
    let key: string | null = null;
    try { key = storage.key(index); } catch { break; }
    if (key !== null && RETIRED_ACTOR_PREFIXES.some((prefix) => key.startsWith(prefix))) {
      keys.push(key);
    }
  }
  return keys;
}

function clearActorSensitiveQueryState(): void {
  queryClient.removeQueries({
    predicate: (query) => !ACTOR_INDEPENDENT_QUERY_ROOTS.has(String(query.queryKey[0] ?? '')),
  });
  queryClient.getMutationCache().clear();
}

export interface ClearStudentBrowserContextOptions {
  /** Notify the same-tab auth provider after the teardown is complete. */
  notifyAuthChanged?: boolean;
  /** Retained API compatibility; cleanup no longer consumes browser actor state. */
  consumeRegisteredActor?: boolean;
}

/**
 * Fail-closed identity boundary for logout, expiry, actor rotation and accepted
 * account deletion. The whole singleton TanStack cache is actor-sensitive
 * because current private query keys are not actor-scoped.
 */
export function clearStudentBrowserContext(
  options: ClearStudentBrowserContextOptions = {},
): void {
  try { clearRegistrationAttempt(); } catch { /* memory-only dependency */ }
  try { resetProfileDraft(); } catch { /* memory reset happens before storage */ }
  try { clearActorSensitiveQueryState(); } catch { /* continue through storage + event */ }

  const local = availableStorage('localStorage');
  if (local) {
    const keys = new Set([
      ...LOCAL_STUDENT_KEYS,
      ...currentActorKeys(),
      ...retiredActorKeys(local),
    ]);
    for (const key of keys) removeKey(local, key);
  }
  const session = availableStorage('sessionStorage');
  if (session) {
    for (const key of SESSION_STUDENT_KEYS) removeKey(session, key);
  }

  observedStudentActor = null;
  if (options.notifyAuthChanged) notifyStudentAuthChanged();
}

/** Record the actor owning singleton memory, clearing before actor rotation. */
export function observeStudentSessionActor(actor: ObservedStudentActor): void {
  if (observedStudentActor !== null && observedStudentActor.subject !== actor.subject) {
    clearStudentBrowserContext();
  }
  observedStudentActor = actor;
}

export function notifyStudentAuthChanged(): void {
  if (typeof window === 'undefined') return;
  try {
    window.dispatchEvent(new Event(STUDENT_AUTH_CHANGED_EVENT));
  } catch {
    // Context is already gone; an incomplete webview EventTarget is non-fatal.
  }
}

/** Narrow bundle-load cleanup that preserves current onboarding and caches. */
export function retireLegacyStudentRegistrationState(): void {
  const local = availableStorage('localStorage');
  if (local) {
    removeKey(local, 'legalsaathi.student.profile.v1');
    removeKey(local, 'ls-auth-student');
    removeKey(local, 'legalsaathi.student.cleanup-registry.v1');
  }
  const session = availableStorage('sessionStorage');
  if (session) removeKey(session, 'legalsaathi.student.registration.v2');
}
