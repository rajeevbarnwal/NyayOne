import { queryClient } from '../../../app/queryClient';
import { resetProfileDraft } from './profileStore';
import { clearRegistrationAttempt } from './registrationAttemptStore';

export const STUDENT_AUTH_CHANGED_EVENT = 'legalsaathi:student-auth-changed';

/**
 * The one actor whose browser-private dynamic keys belong to the current
 * authenticated session. Persisting this narrow registry lets a later reload
 * retire those exact keys after the server reports an expired/revoked session;
 * it never scans a prefix or guesses at another actor's records.
 */
export const STUDENT_CONTEXT_REGISTRY_KEY = 'legalsaathi.student.cleanup-registry.v1';
const REPORT_KEY_PREFIX = 'ls-reports-';
const REMINDER_KEY_PREFIX = 'ls-reminder-prefs-';
const SAFE_ACTOR_KEY_ID = /^[A-Za-z0-9_-]{1,128}$/;

const LOCAL_STUDENT_KEYS = [
  'legalsaathi.student.profile.v1',
  'legalsaathi.student.onboarding.v34',
  'legalsaathi.internship.applications.v1',
  'legalsaathi.clinical.export-audit.v1',
  'ls-auth-student',
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

let observedStudentActor: ObservedStudentActor | null = null;
// Survives ordinary clear calls without retaining an identifier, so a stale
// actor realm can never consume another tab's registry on a second refresh.
let realmHasObservedStudentActor = false;

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

function validatedRegisteredActorKeys(storage: Storage): string[] {
  let parsed: unknown;
  try {
    const raw = storage.getItem(STUDENT_CONTEXT_REGISTRY_KEY);
    if (raw === null) return [];
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed) || (parsed.length !== 2 && parsed.length !== 4)) return [];
  if (new Set(parsed).size !== parsed.length) return [];
  for (let index = 0; index < parsed.length; index += 2) {
    const reportKey = parsed[index];
    const reminderKey = parsed[index + 1];
    if (typeof reportKey !== 'string' || typeof reminderKey !== 'string') return [];
    if (!reportKey.startsWith(REPORT_KEY_PREFIX) || !reminderKey.startsWith(REMINDER_KEY_PREFIX)) return [];
    const reportId = reportKey.slice(REPORT_KEY_PREFIX.length);
    const reminderId = reminderKey.slice(REMINDER_KEY_PREFIX.length);
    if (reportId !== reminderId || !SAFE_ACTOR_KEY_ID.test(reportId)) return [];
  }
  return parsed as string[];
}

function persistCurrentActorRegistry(storage: Storage, actor: ObservedStudentActor): void {
  const keys = actorKeys(actor);
  const validKeys = keys.length === 2 || keys.length === 4
    ? keys.every((value, index) => {
      const prefix = index % 2 === 0 ? REPORT_KEY_PREFIX : REMINDER_KEY_PREFIX;
      return value.startsWith(prefix) && SAFE_ACTOR_KEY_ID.test(value.slice(prefix.length));
    })
    : false;
  try {
    if (validKeys) storage.setItem(STUDENT_CONTEXT_REGISTRY_KEY, JSON.stringify(keys));
    else storage.removeItem(STUDENT_CONTEXT_REGISTRY_KEY);
  } catch {
    // Current-page memory still owns cleanup when persistence is unavailable.
  }
}

export interface ClearStudentBrowserContextOptions {
  /** Notify the same-tab auth provider after the teardown is complete. */
  notifyAuthChanged?: boolean;
  /** A successful logout/deletion may consume the server-current registry. */
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
  // Keep the operations independent: inaccessible Storage cannot retain memory
  // or cache state, and one defensive failure cannot skip the later boundaries.
  try { clearRegistrationAttempt(); } catch { /* memory-only dependency */ }
  try { resetProfileDraft(); } catch { /* memory reset happens before storage */ }
  try { queryClient.clear(); } catch { /* continue through storage + event */ }

  const local = availableStorage('localStorage');
  if (local) {
    const registeredKeys = validatedRegisteredActorKeys(local);
    const registeredSubject = registeredKeys[0]?.slice(REPORT_KEY_PREFIX.length) ?? null;
    const consumeRegisteredKeys = registeredSubject !== null
      && (options.consumeRegisteredActor === true
        || (!realmHasObservedStudentActor && observedStudentActor === null)
        || registeredSubject === observedStudentActor?.subject);
    const actorOwnedKeys = new Set([
      ...currentActorKeys(),
      ...(consumeRegisteredKeys ? registeredKeys : []),
    ]);
    for (const key of [...LOCAL_STUDENT_KEYS, ...actorOwnedKeys]) removeKey(local, key);
    // A valid registry for a different actor can be installed by another tab
    // after session rotation. Preserve that actor's cleanup authority; invalid,
    // missing or same-actor registries are safe to retire here.
    if (registeredSubject === null || consumeRegisteredKeys) {
      removeKey(local, STUDENT_CONTEXT_REGISTRY_KEY);
    }
  }
  const session = availableStorage('sessionStorage');
  if (session) {
    for (const key of SESSION_STUDENT_KEYS) removeKey(session, key);
  }

  observedStudentActor = null;
  if (options.notifyAuthChanged) notifyStudentAuthChanged();
}

/** Record the actor owning the singleton cache, clearing it before rotation. */
export function observeStudentSessionActor(actor: ObservedStudentActor): void {
  const local = availableStorage('localStorage');
  const registeredKeys = local ? validatedRegisteredActorKeys(local) : [];
  const registeredSubject = registeredKeys[0]?.slice(REPORT_KEY_PREFIX.length) ?? null;
  if (
    (observedStudentActor !== null && observedStudentActor.subject !== actor.subject)
    || (observedStudentActor === null
      && registeredSubject !== null
      && registeredSubject !== actor.subject)
  ) {
    clearStudentBrowserContext();
  }
  observedStudentActor = actor;
  realmHasObservedStudentActor = true;
  const currentLocal = availableStorage('localStorage');
  if (currentLocal) persistCurrentActorRegistry(currentLocal, actor);
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
  }
  const session = availableStorage('sessionStorage');
  if (session) removeKey(session, 'legalsaathi.student.registration.v2');
}
