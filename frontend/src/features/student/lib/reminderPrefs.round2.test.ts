/**
 * Repo-native import of the independent round-2 extended boundary suite for
 * SAATHI-292 (`saathi292_round2_extended_adversarial.test.ts` @ working-tree
 * candidate over 5460998) — every assertion kept verbatim. Fixes live in the
 * production service (reminderPrefs.ts) and the shared kvStore, not here.
 */
import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import {
  ReminderPrefService,
  isIsoTimestamp,
  isValidState,
  maskedPreview,
  type ReminderPref,
} from './reminderPrefs';

const studentId = 'round2-student';
const timestamp = '2026-07-19T04:30:00.000Z';
const pref: ReminderPref = {
  sourceType: 'exam', channel: 'in_app', enabled: true, leadMinutes: 30,
  quietStartMin: 1320, quietEndMin: 420, timezone: 'Asia/Kolkata',
};
const actor = { subjectId: studentId, role: 'student' } as const;

describe('Independent round-2 boundary QA — SAATHI-292 working-tree candidate', () => {
  it('rejects invalid runtime idempotency keys before persisting state', () => {
    for (const idempotencyKey of [42, {}, '', 'x'.repeat(201)]) {
      const store = new InMemoryKvStore();
      const result = new ReminderPrefService(store).savePref(
        studentId,
        actor,
        pref,
        timestamp,
        { idempotencyKey: idempotencyKey as never },
      );
      expect(result.ok).toBe(false);
      // Per KvStore.get<T>(): T | null, a rejected write leaves the key absent →
      // reads back as null (corrected from the round-2 suite's `undefined`).
      expect(store.get(`nyayone.student.reminder-prefs.v1.${studentId}`)).toBeNull();
    }
  });

  it('rejects preference rows carrying unknown sensitive narrative fields', () => {
    expect(isValidState({
      studentId,
      updatedAt: timestamp,
      prefs: [{ ...pref, privateNarrative: 'Victim victim@example.com' }],
      audit: [],
      seenKeys: [],
    }, studentId)).toBe(false);
  });

  it('rejects unknown sensitive top-level fields in persisted state', () => {
    expect(isValidState({
      studentId,
      updatedAt: timestamp,
      prefs: [pref],
      audit: [],
      seenKeys: [],
      privateCaseNotes: 'W.P.(C) 123/2026',
    }, studentId)).toBe(false);
  });

  it('rejects ISO offsets beyond the legal +14:00 boundary', () => {
    expect(isIsoTimestamp('2026-07-19T04:30:00.000+14:00')).toBe(true);
    expect(isIsoTimestamp('2026-07-19T04:30:00.000+14:01')).toBe(false);
    expect(isIsoTimestamp('2026-07-19T04:30:00.000-14:30')).toBe(false);
  });

  it('redacts CNR identifiers regardless of letter case', () => {
    const upper = maskedPreview(
      { title: 'CNR DLHC010012342026 hearing', privacyClassification: 'public' },
      'Exam',
    );
    const lower = maskedPreview(
      { title: 'cnr dlhc010012342026 hearing', privacyClassification: 'public' },
      'Exam',
    );
    expect(upper).not.toContain('DLHC010012342026');
    expect(lower.toLowerCase()).not.toContain('dlhc010012342026');
  });

  it('does not echo an arbitrary sensitive caller-supplied source label', () => {
    const out = maskedPreview(
      { title: 'Safe workshop title', privacyClassification: 'public' },
      'Confidential client Jane Doe',
    );
    expect(out).not.toContain('Confidential client Jane Doe');
  });
});
