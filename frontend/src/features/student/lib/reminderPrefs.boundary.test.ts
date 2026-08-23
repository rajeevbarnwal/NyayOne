/**
 * Repo-native import of the independent boundary suite for SAATHI-292
 * (`saathi292_boundary_adversarial.test.ts` @ 5460998) — every assertion kept
 * verbatim — plus the mandated mixed-identifier / false-positive / malformed-actor
 * / duplicate-row / idempotency-key coverage. Fixes live in the production
 * service, not in these tests.
 */
import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import {
  ReminderPrefService,
  isIsoTimestamp,
  isValidState,
  maskedPreview,
  maskedPreviewForSource,
  redactIdentifiers,
  type ReminderPref,
} from './reminderPrefs';

const studentId = 'student-boundary-qa';
const timestamp = '2026-07-19T04:30:00.000Z';
const pref: ReminderPref = {
  sourceType: 'exam',
  channel: 'in_app',
  enabled: true,
  leadMinutes: 30,
  quietStartMin: 1320,
  quietEndMin: 420,
  timezone: 'Asia/Kolkata',
};

describe('Independent boundary QA — SAATHI-292 @ 5460998 (reproduced verbatim)', () => {
  it('rejects an impossible calendar date instead of normalizing it', () => {
    const impossible = '2026-02-30T04:30:00.000Z';
    expect(isIsoTimestamp(impossible)).toBe(false);
    const result = new ReminderPrefService(new InMemoryKvStore()).savePref(
      studentId,
      { subjectId: studentId, role: 'student' },
      pref,
      impossible,
    );
    expect(result).toEqual({ ok: false, reason: 'timestamp' });
  });

  it('rejects malformed audit entries at the persistence boundary', () => {
    expect(
      isValidState(
        {
          studentId,
          updatedAt: timestamp,
          prefs: [pref],
          audit: [
            {
              at: 'not-an-iso-timestamp',
              action: 'export-private-record',
              sourceType: 'carrier_pigeon',
              channel: 'sms',
              privateNarrative: 'Client email victim@example.com',
            },
          ],
          seenKeys: [],
        },
        studentId,
      ),
    ).toBe(false);
  });

  it('rejects non-string idempotency keys in persisted state', () => {
    expect(
      isValidState(
        {
          studentId,
          updatedAt: timestamp,
          prefs: [pref],
          audit: [],
          seenKeys: [42, { raw: 'request-secret' }],
        },
        studentId,
      ),
    ).toBe(false);
  });

  it('rejects duplicate source/channel rows in persisted state', () => {
    const store = new InMemoryKvStore();
    store.set(`nyayone.student.reminder-prefs.v1.${studentId}`, {
      studentId,
      updatedAt: timestamp,
      prefs: [pref, { ...pref, leadMinutes: 60 }],
      audit: [],
      seenKeys: [],
    });
    expect(new ReminderPrefService(store).read(studentId, { subjectId: studentId, role: 'student' })).toBeNull();
  });

  it('returns a safe authorization failure for a malformed runtime actor instead of throwing', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    expect(() => service.savePref(studentId, null as never, pref, timestamp)).not.toThrow();
    expect(service.savePref(studentId, null as never, pref, timestamp)).toEqual({
      ok: false,
      reason: 'unauthorized',
    });
  });

  it('redacts Indian legal case-number formats from a public preview', () => {
    const result = maskedPreview(
      { title: 'Hearing in W.P.(C) 123/2026 for the student', privacyClassification: 'public' },
      'Exam',
    );
    expect(result).not.toContain('W.P.(C) 123/2026');
  });
});

describe('SAATHI-292 boundary — additional privacy / actor / persistence coverage', () => {
  it('strict ISO accepts real dates and rejects impossible / out-of-range ones', () => {
    expect(isIsoTimestamp('2026-07-19T04:30:00.000Z')).toBe(true);
    expect(isIsoTimestamp('2024-02-29T00:00:00.000Z')).toBe(true); // leap year
    expect(isIsoTimestamp('2026-02-29T00:00:00.000Z')).toBe(false); // non-leap
    expect(isIsoTimestamp('2026-13-01T00:00:00.000Z')).toBe(false); // month
    expect(isIsoTimestamp('2026-04-31T00:00:00.000Z')).toBe(false); // 30-day month
    expect(isIsoTimestamp('2026-07-19T24:00:00.000Z')).toBe(false); // hour
    expect(isIsoTimestamp('2026-07-19T04:30:00.000+15:00')).toBe(false); // offset > 14h
    expect(isIsoTimestamp('2026-07-19T04:30:00.000+05:30')).toBe(true); // IST offset
  });

  it('redacts mixed identifiers (case-number, CNR, email, phone, docket) in one public title', () => {
    const out = maskedPreview(
      {
        title: 'Crl.A. 45/2025 CNR DLHC010012342026 call rajeev@example.com +91 98765 43210 diary 77/2026',
        privacyClassification: 'public',
      },
      'Exam',
    );
    expect(out).not.toMatch(/Crl\.A\. 45\/2025|DLHC010012342026|rajeev@example\.com|98765|77\/2026/i);
  });

  it('does not over-redact an ordinary public title (false-positive guard)', () => {
    expect(maskedPreviewForSource({ title: 'Constitutional Law Workshop', privacyClassification: 'public' }, 'exam')).toBe(
      'Exam prep: Constitutional Law Workshop',
    );
    expect(redactIdentifiers('Moot Court Finals')).toBe('Moot Court Finals');
  });

  it('maskedPreviewForSource redacts a legal case number via the trusted label enum', () => {
    const out = maskedPreviewForSource(
      { title: 'W.P.(C) 123/2026 hearing', privacyClassification: 'public' },
      'community',
    );
    expect(out.startsWith('Community')).toBe(true);
    expect(out).not.toContain('W.P.(C) 123/2026');
  });

  it('maps every malformed runtime actor to unauthorized without throwing', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    for (const bad of [null, undefined, [], {}, '', { subjectId: '', role: 'student' }, { subjectId: studentId, role: 'wizard' }]) {
      expect(() => service.savePref(studentId, bad as never, pref, timestamp)).not.toThrow();
      expect(service.savePref(studentId, bad as never, pref, timestamp)).toEqual({ ok: false, reason: 'unauthorized' });
      expect(service.read(studentId, bad as never)).toBeNull();
    }
    // valid owner still works; valid cross-user is forbidden (not unauthorized)
    expect(service.savePref(studentId, { subjectId: studentId, role: 'student' }, pref, timestamp).ok).toBe(true);
    expect(service.savePref(studentId, { subjectId: 'other', role: 'student' }, pref, timestamp)).toEqual({
      ok: false,
      reason: 'forbidden',
    });
  });

  it('accepts a well-formed persisted state with metadata-only audit and string keys', () => {
    const store = new InMemoryKvStore();
    const svc = new ReminderPrefService(store);
    const saved = svc.savePref(studentId, { subjectId: studentId, role: 'student' }, pref, timestamp, {
      idempotencyKey: 'req-1',
    });
    expect(saved.ok).toBe(true);
    expect(svc.read(studentId, { subjectId: studentId, role: 'student' })?.studentId).toBe(studentId);
  });
});
