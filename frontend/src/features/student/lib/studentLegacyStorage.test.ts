import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  LEGACY_COMPATIBLE_DEVICE_LOCAL_EXACT_KEYS,
  LEGACY_LAWYER_AUTH_STORAGE_KEY,
  LEGACY_STUDENT_AUTH_STORAGE_KEY,
  LEGACY_STUDENT_LOCAL_EXACT_KEYS,
  LEGACY_STUDENT_LOCAL_PREFIXES,
  LEGACY_STUDENT_SESSION_EXACT_KEYS,
  MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH,
  STUDENT_REMINDER_PREF_STORAGE_KEY_PREFIX,
  STUDENT_REPORT_STORAGE_KEY_PREFIX,
  purgeCompleteLegacyBrowserLocalStorage,
  purgeLegacyStudentLocalStorage,
  purgeLegacyStudentSessionStorage,
  purgeLegacyStudentSessionStorageAtBootstrap,
} from './studentLegacyStorage';

type InstrumentedStorage = Storage & {
  readonly clearSpy: ReturnType<typeof vi.fn>;
  readonly getItemSpy: ReturnType<typeof vi.fn>;
  readonly keySpy: ReturnType<typeof vi.fn>;
  readonly removeBatches: string[][];
};

function instrumentedStorage(
  entries: Iterable<readonly [string, string]>,
  options: {
    failKeyAt?: number;
    failRemoval?: string;
    ignoreRemoval?: string;
    lengthOverride?: number;
    replenishMatching?: number;
  } = {},
): InstrumentedStorage {
  const values = new Map(entries);
  const clearSpy = vi.fn(() => values.clear());
  const getItemSpy = vi.fn((key: string) => values.get(key) ?? null);
  const removeBatches: string[][] = [];
  let batchIndex = 0;
  let removalsInBatch = 0;
  let replenished = 0;
  const keySpy = vi.fn((index: number) => {
    if (index === options.failKeyAt) throw new DOMException('denied');
    return [...values.keys()][index] ?? null;
  });
  return {
    get length() { return options.lengthOverride ?? values.size; },
    clear: clearSpy,
    clearSpy,
    getItem: getItemSpy,
    getItemSpy,
    key: keySpy,
    keySpy,
    removeBatches,
    removeItem: (key) => {
      if (removalsInBatch === MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH) {
        batchIndex += 1;
        removalsInBatch = 0;
      }
      (removeBatches[batchIndex] ??= []).push(key);
      removalsInBatch += 1;
      if (key === options.failRemoval) throw new DOMException('denied');
      if (key !== options.ignoreRemoval) {
        values.delete(key);
        if (replenished < (options.replenishMatching ?? 0)) {
          values.set(`ls-reports-replenished-${replenished}`, 'private');
          replenished += 1;
        }
      }
    },
    setItem: (key, value) => { values.set(key, value); },
  };
}

describe('NYAY-18 legacy student browser namespace retirement', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('owns the exact obsolete keys and prefixes without device preferences', () => {
    expect(LEGACY_STUDENT_AUTH_STORAGE_KEY).toBe('ls-auth-student');
    expect(LEGACY_LAWYER_AUTH_STORAGE_KEY).toBe('ls-auth-lawyer');
    expect(STUDENT_REPORT_STORAGE_KEY_PREFIX).toBe('nyayone.student.reports.v1.');
    expect(STUDENT_REMINDER_PREF_STORAGE_KEY_PREFIX).toBe(
      'nyayone.student.reminder-prefs.v1.',
    );
    expect(LEGACY_STUDENT_LOCAL_EXACT_KEYS).toEqual([
      'legalsaathi.student.profile.v1',
      'legalsaathi.student.onboarding.v34',
      'legalsaathi.internship.applications.v1',
      'legalsaathi.clinical.export-audit.v1',
      'legalsaathi.student.cleanup-registry.v1',
      'ls-auth-student',
      'ls-auth-lawyer',
      'ls-locale',
      'ls-reviewer',
      'ls-onboarding-seen',
    ]);
    expect(LEGACY_STUDENT_SESSION_EXACT_KEYS).toEqual([
      'legalsaathi.student.registration.v2',
      'legalsaathi.student.privacy.export.v1',
      'legalsaathi.student.privacy.delete.v1',
    ]);
    expect(LEGACY_STUDENT_LOCAL_PREFIXES).toEqual([
      'ls-reports-',
      'ls-reminder-prefs-',
      'ls-draftws-',
      'ls-review-',
      'ls-filing-',
    ]);
    expect(LEGACY_COMPATIBLE_DEVICE_LOCAL_EXACT_KEYS).toEqual([
      'ls-theme',
    ]);
    expect(LEGACY_STUDENT_LOCAL_EXACT_KEYS).not.toEqual(
      expect.arrayContaining([...LEGACY_COMPATIBLE_DEVICE_LOCAL_EXACT_KEYS]),
    );
  });

  it('deletes every owned local key in bounded batches without reading values or clearing storage', () => {
    const owned = Array.from(
      { length: (MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH * 2) + 17 },
      (_, index) => [`ls-reports-retired-${index}`, `private-${index}`] as const,
    );
    const storage = instrumentedStorage([
      ['unrelated-before', 'keep'],
      ...owned,
      ['legalsaathi.student.profile.v1', 'private-profile'],
      ['ls-onboarding-seen', 'obsolete'],
      ['ls-theme', 'dark'],
      ['unrelated-after', 'keep'],
    ]);

    expect(purgeLegacyStudentLocalStorage(storage)).toEqual({
      batches: 3,
      complete: true,
      maximumBatchSize: MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH,
      removed: owned.length + 2,
    });
    expect(storage.removeBatches.every(
      (batch) => batch.length <= MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH,
    )).toBe(true);
    expect(storage.getItemSpy).not.toHaveBeenCalled();
    expect(storage.clearSpy).not.toHaveBeenCalled();
    expect(storage.getItem('unrelated-before')).toBe('keep');
    expect(storage.getItem('unrelated-after')).toBe('keep');
    expect(storage.getItem('ls-theme')).toBe('dark');
  });

  it('finds owned keys after more than one batch of unrelated keys', () => {
    const entries: Array<readonly [string, string]> = [];
    for (let index = 0; index < MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH + 19; index += 1) {
      entries.push([`unrelated-${index}`, 'keep']);
    }
    entries.push(['ls-reminder-prefs-after-boundary', 'private']);
    const storage = instrumentedStorage(entries);

    expect(purgeLegacyStudentLocalStorage(storage)).toMatchObject({
      complete: true,
      removed: 1,
    });
    expect(storage.getItemSpy).not.toHaveBeenCalled();
    expect(storage.length).toBe(entries.length - 1);
  });

  it('retires session-only references while preserving unrelated session state', () => {
    const storage = instrumentedStorage([
      ['legalsaathi.student.registration.v2', 'private-registration'],
      ['legalsaathi.student.privacy.export.v1', 'private-export'],
      ['legalsaathi.student.privacy.delete.v1', 'private-delete'],
      ['unrelated-session', 'keep'],
    ]);

    expect(purgeLegacyStudentSessionStorage(storage)).toEqual({
      batches: 1,
      complete: true,
      maximumBatchSize: 3,
      removed: 3,
    });
    expect(storage.getItemSpy).not.toHaveBeenCalled();
    expect(storage.clearSpy).not.toHaveBeenCalled();
    expect(storage.getItem('unrelated-session')).toBe('keep');
  });

  it('runs session retirement safely at browser bootstrap', () => {
    const sessionStorage = instrumentedStorage([
      ['legalsaathi.student.registration.v2', 'private-registration'],
      ['unrelated-session', 'keep'],
    ]);
    vi.stubGlobal('window', { sessionStorage });

    expect(purgeLegacyStudentSessionStorageAtBootstrap()).toBe(true);
    expect(sessionStorage.getItem('legalsaathi.student.registration.v2')).toBeNull();
    expect(sessionStorage.getItem('unrelated-session')).toBe('keep');
    expect(sessionStorage.clearSpy).not.toHaveBeenCalled();
  });

  it('reports bootstrap session storage as incomplete without crashing public startup', () => {
    vi.stubGlobal('window', {
      get sessionStorage(): Storage { throw new DOMException('denied'); },
    });

    expect(purgeLegacyStudentSessionStorageAtBootstrap()).toBe(false);
  });

  it('performs the complete purge only after compatible device values have been migrated', () => {
    const storage = instrumentedStorage([
      ['ls-theme', 'dark'],
      ['ls-locale', 'hi'],
      ['ls-reviewer', '1'],
      ['ls-auth-lawyer', 'private-auth'],
      ['ls-draftws-current', 'private-draft'],
      ['ls-review-case-1', 'private-review'],
      ['ls-filing-case-1', 'private-filing'],
      ['unrelated', 'keep'],
    ]);

    expect(purgeCompleteLegacyBrowserLocalStorage(storage)).toEqual({
      batches: 1,
      complete: true,
      maximumBatchSize: 7,
      removed: 7,
    });
    expect(storage.clearSpy).not.toHaveBeenCalled();
    expect(storage.getItemSpy).not.toHaveBeenCalled();
    expect(storage.getItem('unrelated')).toBe('keep');
  });

  it('fails closed on a denied removal without claiming later keys were purged', () => {
    const storage = instrumentedStorage([
      ['ls-reports-denied', 'private'],
      ['ls-reminder-prefs-later', 'private'],
      ['unrelated', 'keep'],
    ], { failRemoval: 'ls-reports-denied' });

    expect(purgeLegacyStudentLocalStorage(storage)).toEqual({
      batches: 1,
      complete: false,
      maximumBatchSize: 2,
      removed: 1,
    });
    expect(storage.clearSpy).not.toHaveBeenCalled();
    expect(storage.getItemSpy).not.toHaveBeenCalled();
  });

  it('fails closed without mutation when key enumeration becomes unavailable', () => {
    const storage = instrumentedStorage([
      ['unrelated', 'keep'],
      ['ls-reports-private', 'private'],
    ], { failKeyAt: 1 });

    expect(purgeLegacyStudentLocalStorage(storage)).toEqual({
      batches: 0,
      complete: false,
      maximumBatchSize: 0,
      removed: 0,
    });
    expect(storage.removeBatches).toEqual([]);
    expect(storage.clearSpy).not.toHaveBeenCalled();
    expect(storage.getItemSpy).not.toHaveBeenCalled();
  });

  it.each([Infinity, -1, 1.5, Number.MAX_SAFE_INTEGER + 1])(
    'fails closed without reading or mutating for hostile storage length %s',
    (lengthOverride) => {
      const storage = instrumentedStorage([
        ['ls-reports-private', 'private'],
        ['unrelated', 'keep'],
      ], { lengthOverride });

      expect(purgeLegacyStudentLocalStorage(storage)).toEqual({
        batches: 0,
        complete: false,
        maximumBatchSize: 0,
        removed: 0,
      });
      expect(storage.keySpy).not.toHaveBeenCalled();
      expect(storage.getItemSpy).not.toHaveBeenCalled();
      expect(storage.removeBatches).toEqual([]);
      expect(storage.clearSpy).not.toHaveBeenCalled();
    },
  );

  it('fails closed instead of looping when removeItem silently makes no progress', () => {
    const storage = instrumentedStorage([
      ['ls-reports-stuck', 'private'],
      ['unrelated', 'keep'],
    ], { ignoreRemoval: 'ls-reports-stuck' });

    expect(purgeLegacyStudentLocalStorage(storage)).toEqual({
      batches: 1,
      complete: false,
      maximumBatchSize: 1,
      removed: 0,
    });
    expect(storage.removeBatches).toEqual([['ls-reports-stuck']]);
  });

  it('terminates deterministically when a writer replenishes matching keys after each batch', () => {
    const storage = instrumentedStorage([
      ['ls-reports-initial', 'private'],
      ['unrelated', 'keep'],
    ], { replenishMatching: (MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH * 2) + 1 });

    expect(purgeLegacyStudentLocalStorage(storage)).toEqual({
      batches: 1,
      complete: false,
      maximumBatchSize: 1,
      removed: 1,
    });
    expect(storage.removeBatches).toEqual([['ls-reports-initial']]);
    expect(storage.getItemSpy).not.toHaveBeenCalled();
    expect(storage.clearSpy).not.toHaveBeenCalled();
    expect(storage.getItem('unrelated')).toBe('keep');
  });
});
