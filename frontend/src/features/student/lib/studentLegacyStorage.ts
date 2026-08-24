/**
 * NYAY-18 browser namespace and legacy compatibility boundary.
 *
 * The current report/reminder key builders are centralized here so actor
 * teardown cannot drift from their writers. Every value in a LEGACY inventory
 * is obsolete private, actor-derived, or explicitly retired device state:
 * callers may enumerate its key name only for deletion and must never read,
 * parse, migrate, or rewrite its value. The sole compatible exception,
 * `ls-theme`, is isolated for the root one-shot migration before deletion.
 */

export const LEGACY_STUDENT_PROFILE_DRAFT_KEY = 'legalsaathi.student.profile.v1';
export const LEGACY_STUDENT_AUTH_STORAGE_KEY = 'ls-auth-student';
export const LEGACY_LAWYER_AUTH_STORAGE_KEY = 'ls-auth-lawyer';
export const STUDENT_REPORT_STORAGE_KEY_PREFIX = 'nyayone.student.reports.v1.';
export const STUDENT_REMINDER_PREF_STORAGE_KEY_PREFIX = 'nyayone.student.reminder-prefs.v1.';

export function studentReportStorageKey(actorId: string): string {
  return `${STUDENT_REPORT_STORAGE_KEY_PREFIX}${actorId}`;
}

export function studentReminderPrefStorageKey(actorId: string): string {
  return `${STUDENT_REMINDER_PREF_STORAGE_KEY_PREFIX}${actorId}`;
}

export const LEGACY_STUDENT_LOCAL_EXACT_KEYS = [
  LEGACY_STUDENT_PROFILE_DRAFT_KEY,
  'legalsaathi.student.onboarding.v34',
  'legalsaathi.internship.applications.v1',
  'legalsaathi.clinical.export-audit.v1',
  'legalsaathi.student.cleanup-registry.v1',
  LEGACY_STUDENT_AUTH_STORAGE_KEY,
  LEGACY_LAWYER_AUTH_STORAGE_KEY,
  'ls-locale',
  'ls-reviewer',
  'ls-onboarding-seen',
] as const;

/**
 * Root bootstrap reads these compatible device preferences through its
 * one-shot migration boundary before requesting the complete legacy purge.
 * Student module evaluation must not consume or delete them earlier.
 */
export const LEGACY_COMPATIBLE_DEVICE_LOCAL_EXACT_KEYS = [
  'ls-theme',
] as const;

export const LEGACY_STUDENT_SESSION_EXACT_KEYS = [
  'legalsaathi.student.registration.v2',
  'legalsaathi.student.privacy.export.v1',
  'legalsaathi.student.privacy.delete.v1',
] as const;

export const LEGACY_STUDENT_LOCAL_PREFIXES = [
  'ls-reports-',
  'ls-reminder-prefs-',
  'ls-draftws-',
  'ls-review-',
  'ls-filing-',
] as const;

export const MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH = 256;

export interface LegacyStudentStoragePurgeReport {
  readonly batches: number;
  readonly complete: boolean;
  readonly maximumBatchSize: number;
  readonly removed: number;
}

function collectOwnedKeysSnapshot(
  storage: Storage,
  exactKeys: ReadonlySet<string>,
  prefixes: readonly string[],
): string[] | null {
  let length: number;
  try {
    length = storage.length;
  } catch {
    return null;
  }
  if (!Number.isSafeInteger(length) || length < 0) return null;
  const ownedKeys: string[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < length; index += 1) {
    let key: string | null;
    try {
      key = storage.key(index);
    } catch {
      return null;
    }
    if (key === null) return null;
    if (seen.has(key)) continue;
    if (!exactKeys.has(key) && !prefixes.some((prefix) => key.startsWith(prefix))) continue;
    seen.add(key);
    ownedKeys.push(key);
  }
  return ownedKeys;
}

function keysStillPresent(storage: Storage, candidates: ReadonlySet<string>): Set<string> | null {
  let length: number;
  try {
    length = storage.length;
  } catch {
    return null;
  }
  if (!Number.isSafeInteger(length) || length < 0) return null;
  const remaining = new Set<string>();
  for (let index = 0; index < length; index += 1) {
    let key: string | null;
    try {
      key = storage.key(index);
    } catch {
      return null;
    }
    if (key === null) return null;
    if (candidates.has(key)) remaining.add(key);
  }
  return remaining;
}

function purgeLegacyStudentStorage(
  storage: Storage,
  exactKeyInventory: readonly string[],
  prefixInventory: readonly string[],
  additionalExactKeys: readonly string[] = [],
): LegacyStudentStoragePurgeReport {
  const exactKeys = new Set([...exactKeyInventory, ...additionalExactKeys]);
  let batches = 0;
  let maximumBatchSize = 0;
  let removed = 0;

  // Freeze one finite generation of owned key names before mutating Storage.
  // A concurrent or non-conforming writer may add/recreate keys while removal
  // runs, but it cannot extend this loop. One final name-only scan detects that
  // drift and fails closed instead of chasing an attacker-controlled stream.
  const snapshot = collectOwnedKeysSnapshot(storage, exactKeys, prefixInventory);
  if (snapshot === null) return { batches, complete: false, maximumBatchSize, removed };
  for (
    let index = 0;
    index < snapshot.length;
    index += MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH
  ) {
    const batch = snapshot.slice(index, index + MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH);
    batches += 1;
    maximumBatchSize = Math.max(maximumBatchSize, batch.length);
    let removalFailed = false;
    for (const key of batch) {
      try {
        storage.removeItem(key);
      } catch {
        removalFailed = true;
      }
    }

    // Verify progress by enumerating names only. This catches privacy-policy
    // changes and non-conforming Storage implementations without reading a
    // legacy value or risking an unbounded retry loop.
    const remaining = keysStillPresent(storage, new Set(batch));
    if (remaining === null) return { batches, complete: false, maximumBatchSize, removed };
    removed += batch.length - remaining.size;
    if (removalFailed || remaining.size > 0) {
      return { batches, complete: false, maximumBatchSize, removed };
    }
  }

  const nextGeneration = collectOwnedKeysSnapshot(storage, exactKeys, prefixInventory);
  if (nextGeneration === null || nextGeneration.length > 0) {
    return { batches, complete: false, maximumBatchSize, removed };
  }
  return { batches, complete: true, maximumBatchSize, removed };
}

export function purgeLegacyStudentLocalStorage(
  storage: Storage,
  additionalExactKeys: readonly string[] = [],
): LegacyStudentStoragePurgeReport {
  return purgeLegacyStudentStorage(
    storage,
    LEGACY_STUDENT_LOCAL_EXACT_KEYS,
    LEGACY_STUDENT_LOCAL_PREFIXES,
    additionalExactKeys,
  );
}

export function purgeLegacyStudentSessionStorage(
  storage: Storage,
): LegacyStudentStoragePurgeReport {
  return purgeLegacyStudentStorage(storage, LEGACY_STUDENT_SESSION_EXACT_KEYS, []);
}

/**
 * Best-effort public bootstrap, fail-closed at the private-session boundary.
 * Public startup must remain available when Storage is disabled; authenticated
 * discovery re-runs the same purge through clearStudentBrowserContext and
 * rejects private mounting unless that authoritative cleanup completes.
 */
export function purgeLegacyStudentSessionStorageAtBootstrap(): boolean {
  if (typeof window === 'undefined') return true;
  try {
    return purgeLegacyStudentSessionStorage(window.sessionStorage).complete;
  } catch {
    return false;
  }
}

/**
 * Finish the product-wide browser purge after the compatible device values
 * have been consumed by their one-shot migration. This function never reads a
 * value itself and is intentionally not called during student module import.
 */
export function purgeCompleteLegacyBrowserLocalStorage(
  storage: Storage,
): LegacyStudentStoragePurgeReport {
  return purgeLegacyStudentStorage(
    storage,
    [
      ...LEGACY_STUDENT_LOCAL_EXACT_KEYS,
      ...LEGACY_COMPATIBLE_DEVICE_LOCAL_EXACT_KEYS,
    ],
    LEGACY_STUDENT_LOCAL_PREFIXES,
  );
}
