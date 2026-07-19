/**
 * Repo-native reproduction of the independent-QA adversarial suite for SAATHI-292
 * (`adversarial_reminderPrefs.test.ts` @ 083d1c76), plus the additionally-mandated
 * wrong-role, stale-write, duplicate-retry and malformed-storage recovery cases.
 *
 * These cover the five failures the independent adversarial run flagged
 * (7 passed / 5 failed at 083d1c76) and lock in the remediation contract.
 */
import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import { CALENDAR_SOURCE_TYPES } from './calendar';
import {
  ReminderPrefService,
  isValidTimezone,
  maskedPreview,
  maskedPreviewForSource,
  validatePref,
  type Actor,
  type ReminderPref,
} from './reminderPrefs';

const student = 'stu-qa';
const TS = '2026-07-19T04:30:00.000Z';
const valid: ReminderPref = {
  sourceType: 'exam',
  channel: 'in_app',
  enabled: true,
  leadMinutes: 30,
  quietStartMin: 1320,
  quietEndMin: 420,
  timezone: 'Asia/Kolkata',
};

describe('Independent adversarial QA — SAATHI-292 (reproduced natively)', () => {
  it('TC-290-01 loads safe defaults and a returning saved preference', () => {
    const store = new InMemoryKvStore();
    const service = new ReminderPrefService(store);
    expect(service.load(student).prefs).toHaveLength(CALENDAR_SOURCE_TYPES.length);
    expect(service.savePref(student, student, valid, TS).ok).toBe(true);
    expect(new ReminderPrefService(store).read(student, student)?.updatedAt).toBe(TS);
  });

  it('TC-290-02 enables/disables every supported source and persists it', () => {
    const store = new InMemoryKvStore();
    const service = new ReminderPrefService(store);
    for (const sourceType of CALENDAR_SOURCE_TYPES) {
      expect(service.savePref(student, student, { ...valid, sourceType, enabled: false }, TS).ok).toBe(true);
    }
    const reloaded = new ReminderPrefService(store).read(student, student);
    expect(reloaded?.prefs.every((pref) => pref.enabled === false)).toBe(true);
  });

  it('TC-290-03 rejects invalid lead, quiet-hour, channel and timezone values', () => {
    expect(validatePref({ ...valid, leadMinutes: 45 })).toBe('lead_time');
    expect(validatePref({ ...valid, quietStartMin: 1440 })).toBe('quiet_range');
    expect(validatePref({ ...valid, channel: 'carrier_pigeon' as never })).toBe('channel');
    expect(validatePref({ ...valid, timezone: 'Mars/Phobos' })).toBe('timezone');
  });

  it('TC-290-04 proves repeated saves are idempotent', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    service.savePref(student, student, valid, TS);
    const second = service.savePref(student, student, { ...valid, leadMinutes: 60 }, '2026-07-19T04:31:00.000Z');
    expect(second.ok && second.state.prefs.filter((p) => p.sourceType === 'exam' && p.channel === 'in_app')).toHaveLength(1);
  });

  it('TC-290-05 suppresses eligibility after opt-out', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    const result = service.savePref(student, student, { ...valid, enabled: false }, TS);
    expect(result.ok && service.isPreviewEligible(result.state, 'exam', 'in_app')).toBe(false);
  });

  it('TC-290-06 masks personal and restricted titles (canonical trusted-label API)', () => {
    expect(maskedPreviewForSource({ title: 'Private title', privacyClassification: 'personal' }, 'exam')).toBe(
      'Exam prep: You have an upcoming item',
    );
    expect(maskedPreviewForSource({ title: 'Restricted title', privacyClassification: 'restricted' }, 'exam')).toBe(
      'Exam prep: You have an upcoming item',
    );
  });

  it('TC-290-07 refuses cross-user read/write', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    expect(service.savePref(student, 'attacker', valid, TS)).toEqual({ ok: false, reason: 'forbidden' });
    expect(service.read(student, 'attacker')).toBeNull();
  });

  // ---- The five previously-failing adversarial cases ----

  it('rejects a malformed enabled flag with a typed validation result', () => {
    const malformed = { ...valid, enabled: 'yes' as unknown as boolean };
    expect(validatePref(malformed)).not.toBeNull();
    expect(validatePref(malformed)).toBe('enabled');
  });

  it('never exposes email/phone/private identifiers even when an event is marked public', () => {
    const preview = maskedPreview(
      { title: 'Call rajeev@example.com at +91 98765 43210 about EV-99177', privacyClassification: 'public' },
      'Exam',
    );
    expect(preview).not.toMatch(/rajeev@example\.com|98765|EV-99177/i);
  });

  it('does not seed invalid timezone values into a new-user state', () => {
    const state = new ReminderPrefService(new InMemoryKvStore()).load(student, 'Mars/Phobos');
    expect(state.prefs.every((pref) => isValidTimezone(pref.timezone))).toBe(true);
  });

  it('does not accept a malformed audit timestamp as persisted updatedAt', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    const result = service.savePref(student, student, valid, 'not-an-iso-timestamp');
    expect(result.ok).toBe(false);
    expect(result.ok === false && result.reason).toBe('timestamp');
  });

  it('does not trust malformed persisted preference state on read', () => {
    const store = new InMemoryKvStore();
    store.set(`ls-reminder-prefs-${student}`, {
      studentId: student,
      updatedAt: 'not-an-iso-timestamp',
      prefs: [{ ...valid, channel: 'carrier_pigeon', enabled: 'yes', timezone: 'Mars/Phobos' }],
    });
    expect(new ReminderPrefService(store).read(student, student)).toBeNull();
  });
});

describe('SAATHI-292 authorization / concurrency / recovery (added)', () => {
  const studentActor: Actor = { subjectId: student, role: 'student' };
  const moderator: Actor = { subjectId: 'mod-1', role: 'moderator' };
  const guestAsSelf: Actor = { subjectId: student, role: 'guest' };

  it('accepts the owning student actor object (role + subject)', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    expect(service.savePref(student, studentActor, valid, TS).ok).toBe(true);
    expect(service.read(student, studentActor)?.studentId).toBe(student);
  });

  it('rejects a wrong role with a typed unauthorized error, not merely a different id', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    // Same subjectId as the owner but a non-owner role ⇒ unauthorized (role, not id).
    expect(service.savePref(student, guestAsSelf, valid, TS)).toEqual({ ok: false, reason: 'unauthorized' });
    // A moderator acting on a student's private prefs is also unauthorized.
    expect(service.savePref(student, moderator, valid, TS)).toEqual({ ok: false, reason: 'unauthorized' });
    expect(service.read(student, moderator)).toBeNull();
  });

  it('preserves cross-user isolation for actor objects', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    const otherStudent: Actor = { subjectId: 'stu-2', role: 'student' };
    expect(service.savePref(student, otherStudent, valid, TS)).toEqual({ ok: false, reason: 'forbidden' });
    expect(service.read(student, otherStudent)).toBeNull();
  });

  it('rejects a stale write with a typed conflict (optimistic concurrency)', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    // First write: expected baseline is null.
    const first = service.savePref(student, student, valid, TS, { expectedUpdatedAt: null });
    expect(first.ok).toBe(true);
    // A writer holding the stale (null) baseline must be rejected.
    const stale = service.savePref(student, student, { ...valid, leadMinutes: 60 }, '2026-07-19T05:00:00.000Z', {
      expectedUpdatedAt: null,
    });
    expect(stale).toEqual({ ok: false, reason: 'conflict' });
    // A writer with the current token succeeds.
    const fresh = service.savePref(student, student, { ...valid, leadMinutes: 60 }, '2026-07-19T05:01:00.000Z', {
      expectedUpdatedAt: TS,
    });
    expect(fresh.ok).toBe(true);
  });

  it('an idempotent retry (same key) creates no duplicate audit effect', () => {
    const service = new ReminderPrefService(new InMemoryKvStore());
    const a = service.savePref(student, student, valid, TS, { idempotencyKey: 'req-1' });
    const b = service.savePref(student, student, valid, '2026-07-19T06:00:00.000Z', { idempotencyKey: 'req-1' });
    expect(a.ok && b.ok).toBe(true);
    expect(a.ok && a.state.audit).toHaveLength(1);
    expect(b.ok && b.state.audit).toHaveLength(1); // replay: no second audit entry
    expect(b.ok && b.state.updatedAt).toBe(TS); // unchanged by the replay
  });

  it('safely recovers on save over corrupt persisted state without trusting bad rows', () => {
    const store = new InMemoryKvStore();
    store.set(`ls-reminder-prefs-${student}`, {
      studentId: student,
      updatedAt: 'garbage',
      prefs: [{ ...valid, channel: 'carrier_pigeon' }],
    });
    const service = new ReminderPrefService(store);
    const saved = service.savePref(student, student, valid, TS);
    expect(saved.ok).toBe(true);
    // The rebuilt state contains only validated rows — the corrupt channel is gone.
    expect(saved.ok && saved.state.prefs.every((p) => validatePref(p) === null)).toBe(true);
    expect(saved.ok && saved.state.prefs.some((p) => (p.channel as string) === 'carrier_pigeon')).toBe(false);
  });

  it('maskedPreviewForSource uses the trusted label enum (no caller-supplied label)', () => {
    const out = maskedPreviewForSource({ title: 'AMA rajeev@example.com', privacyClassification: 'public' }, 'community');
    expect(out).not.toMatch(/rajeev@example\.com/i);
    expect(out.startsWith('Community')).toBe(true);
  });
});
